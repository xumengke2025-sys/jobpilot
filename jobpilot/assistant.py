"""Resume -> search -> diagnose -> confirm -> new version -> re-match.

This assistant never sends applications or changes the source resume in place.
Capability coverage is based on confirmed keywords, independent of rewritten text.
"""
import copy
import json
import re
import uuid
from collections import Counter
from pathlib import Path

from .core import contains, digest, match, read_json, tailor, validate_job, validate_profile
from .export import export_bundle
from .platforms import PLATFORM_SPECS, platform_filter_plan, search_entry
from .store import now

# A bounded vocabulary is a fallback, not an exhaustive understanding of a JD.
VOCABULARY = ["需求分析", "产品规划", "产品设计", "数据分析", "项目管理", "验收", "知识库", "知识图谱", "RAG", "Agent", "多智能体", "大模型", "机器学习", "Python", "SQL", "Java", "CUDA", "分布式训练", "模型训练", "算法研发", "风险管理", "合规", "反洗钱", "数据治理", "金融", "证券", "用户研究", "商业化", "销售", "Figma", "PRD", "B端", "C端"]


def init_cycles(store):
    store.db.executescript("""
      CREATE TABLE IF NOT EXISTS resume_cycles(
        id TEXT PRIMARY KEY, parent_id TEXT, profile_hash TEXT NOT NULL,
        report TEXT NOT NULL, created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS resume_revisions(
        cycle_id TEXT PRIMARY KEY, profile_hash TEXT NOT NULL,
        result_hash TEXT NOT NULL, decisions TEXT NOT NULL,
        profile TEXT NOT NULL, created_at TEXT NOT NULL);
    """)


def load_cycle(store, cycle_id):
    init_cycles(store)
    row = store.db.execute("SELECT report FROM resume_cycles WHERE id=?", (cycle_id,)).fetchone()
    if not row:
        raise ValueError("找不到这一轮分析，请核对 cycle_id 和 --db")
    return json.loads(row[0])


def search_plan(profile, policy):
    validate_profile(profile)
    from .preferences import normalize_policy
    policy = normalize_policy(policy)
    titles = list(dict.fromkeys(policy.get("target_titles") or [f["role"] for f in profile["facts"]]))
    if not titles or any(not isinstance(t, str) or not t.strip() for t in titles):
        raise ValueError("请填写至少一个目标岗位名称")
    skills = Counter(k for f in profile["facts"] for k in set(f.get("keywords", [])))
    combinations, seen = [], set()
    for title in titles[:4]:
        for term in ["", *[k for k, _ in skills.most_common(3)]]:
            query = f"{title} {term}".strip()
            if query not in seen:
                seen.add(query)
                combinations.append((query, term))
    platforms = policy["platforms"] or ["boss", "liepin"]
    plan = []
    for platform in platforms:
        spec = PLATFORM_SPECS[platform]
        for query, term in combinations:
            ids = [f["id"] for f in profile["facts"] if not term or term in f.get("keywords", [])]
            for city in policy["cities"] or [""]:
                plan.append({
                    "platform": platform,
                    "platform_name": spec["name"],
                    "interaction_model": spec["interaction_model"],
                    "action_note": spec["action_note"],
                    "query": query,
                    "city": city,
                    "evidence_ids": ids,
                    "cities": [city] if city else [],
                    "url": search_entry(platform, query),
                    "filters": platform_filter_plan(platform, policy, city),
                })
    return {
        "profile_hash": digest(profile), "policy_hash": digest(policy), "conditions": policy,
        "platforms": [{"id": p, "name": PLATFORM_SPECS[p]["name"], "interaction_model": PLATFORM_SPECS[p]["interaction_model"],
                       "action_note": PLATFORM_SPECS[p]["action_note"]} for p in platforms],
        "queries": plan,
        "note": "搜索任务按平台和城市分开。网页筛选只负责缩小候选集；薪酬粗区间、福利、活跃度等仍按原始条件本地复核。猎聘入口可能不预填关键词，页面执行器会填写搜索框。",
    }


def job_completeness(job):
    checks = {
        "city": bool(job.get("city")),
        "salary": job.get("salary_min") is not None or job.get("annual_salary_min") is not None,
        "experience": job.get("min_experience_years") is not None or bool(job.get("experience_band")),
        "education": bool(job.get("required_education")),
        "industry": bool(job.get("industry")),
        "company_size": bool(job.get("company_size")),
        "availability": job.get("is_active") is not None,
        "captured_at": bool(job.get("captured_at")),
    }
    missing = [field for field, present in checks.items() if not present]
    return {"score": round(100 * (len(checks) - len(missing)) / len(checks)), "missing": missing}


def market_insights(rows, min_jobs=2):
    """Aggregate requirements by exact job cluster so cross-site copies count once."""
    candidates = [row for row in rows if row["assessment"]["status"] != "rejected"]
    clusters = {}
    platform_counts = Counter()
    for row in candidates:
        job = row["job"]
        platform_counts[job["source_platform"]] += 1
        cluster = clusters.setdefault(job["cluster_id"], {"rows": [], "requirements": set(), "platforms": set()})
        cluster["rows"].append(row)
        cluster["requirements"].update(job.get("requirements", []))
        cluster["platforms"].add(job["source_platform"])
    terms = {}
    for cluster_id, cluster in clusters.items():
        for term in cluster["requirements"]:
            key = re.sub(r"\s+", " ", term.strip()).casefold()
            item = terms.setdefault(key, {"term": term, "clusters": set(), "verified_clusters": set(), "jobs": set(), "platforms": set(), "supported": False, "explicit": False})
            item["clusters"].add(cluster_id)
            for row in cluster["rows"]:
                if term in row["job"].get("requirements", []):
                    item["jobs"].add(row["job"]["id"])
                    item["platforms"].add(row["job"]["source_platform"])
                    if row.get("requirements_origin", "provided") == "provided":
                        item["verified_clusters"].add(cluster_id)
                    item["supported"] = item["supported"] or term in row["assessment"]["evidence"]
                    item["explicit"] = item["explicit"] or term in row["expression"]["explicit"]
    total_clusters = len(clusters)
    requirements = []
    for item in terms.values():
        term = item["term"]
        state = "expressed" if item["explicit"] else "supported_hidden" if item["supported"] else "gap"
        count, verified = len(item["clusters"]), len(item["verified_clusters"])
        requirements.append({
            "term": term, "cluster_count": count, "verified_cluster_count": verified, "job_count": len(item["jobs"]),
            "share": round(100 * count / total_clusters) if total_clusters else 0,
            "platforms": sorted(item["platforms"]), "state": state,
            "recurring": verified >= min_jobs,
        })
    state_order = {"supported_hidden": 0, "gap": 1, "expressed": 2}
    requirements.sort(key=lambda x: (-x["cluster_count"], state_order[x["state"]], x["term"].casefold()))
    duplicate_groups = [{"cluster_id": cid, "job_ids": [r["job"]["id"] for r in value["rows"]],
                         "platforms": sorted(value["platforms"]), "count": len(value["rows"])}
                        for cid, value in clusters.items() if len(value["rows"]) > 1]
    return {
        "candidate_jobs": len(candidates), "distinct_job_clusters": total_clusters,
        "platform_counts": dict(sorted(platform_counts.items())), "minimum_clusters": min_jobs,
        "sample_sufficient": total_clusters >= min_jobs,
        "requirements": requirements[:30], "recurring_requirements": [x for x in requirements if x["recurring"]][:30],
        "duplicate_groups": duplicate_groups,
        "note": "重复发布只计一个岗位簇，只有已核对 requirements 的岗位计入高频门槛。高频要求用于确定修改优先级；单个 JD 的词不会自动写入简历。",
    }


def annotate_suggestions(suggestions, market):
    terms = {re.sub(r"\s+", " ", item["term"].strip()).casefold(): item for item in market["requirements"]}
    for suggestion in suggestions:
        related = [terms[key] for t in suggestion.get("terms", []) if (key := re.sub(r"\s+", " ", t.strip()).casefold()) in terms]
        count = max((item["verified_cluster_count"] for item in related), default=1)
        suggestion["market_cluster_count"] = count
        suggestion["market_total_clusters"] = market["distinct_job_clusters"]
        suggestion["scope"] = "recurring" if count >= market["minimum_clusters"] else "job_specific"
    suggestions.sort(key=lambda s: (s["scope"] != "recurring", -s["market_cluster_count"], s["kind"], s["id"]))
    return suggestions


def inferred_job(profile, job):
    j = validate_job(job)
    if j["requirements"]:
        j["requirements"] = list(dict.fromkeys(j["requirements"]))
        return j, "provided"
    terms = list(dict.fromkeys(VOCABULARY + [k for f in profile["facts"] for k in f.get("keywords", [])]))
    j["requirements"] = [k for k in terms if contains(j["description"], k)]
    return j, "inferred_partial"


def expression_coverage(profile, assessment):
    """Measure how well the current wording exposes *supported* requirements."""
    byid = {f["id"]: f for f in profile["facts"]}
    evidence = assessment["evidence"]
    explicit = [term for term, ids in evidence.items() if any(contains(byid[fid]["text"], term) for fid in ids)]
    return {"score": round(100 * len(explicit) / len(evidence)) if evidence else None,
            "explicit": explicit, "implicit": [k for k in evidence if k not in explicit]}


def add_suggestion(result, **data):
    data["id"] = digest(data)[:16]
    if all(s["id"] != data["id"] for s in result):
        result.append(data)


def diagnose(profile, job, assessment):
    suggestions = []
    if assessment["status"] == "rejected":
        return suggestions
    for fact in profile["facts"]:
        relevant = [k for k, ids in assessment["evidence"].items() if fact["id"] in ids]
        if not relevant:
            continue
        before = fact["text"]
        current = sum(contains(before, k) for k in relevant)
        variants = fact.get("approved_variants", [])
        best = max(variants, key=lambda v: sum(contains(v, k) for k in relevant), default=before)
        if sum(contains(best, k) for k in relevant) > current:
            add_suggestion(suggestions, kind="rewrite", source="approved_variant", job_id=job["id"], fact_id=fact["id"], before=before, after=best,
                           reason="已确认的另一种表述更清楚地呈现岗位关注的能力", terms=relevant, question="", requirement_quote="")
        else:
            implicit = [k for k in relevant if not contains(before, k)]
            if implicit:
                add_suggestion(suggestions, kind="clarify", source="rules", job_id=job["id"], fact_id=fact["id"], before=before, after="",
                               reason="能力标签已有记录，但项目描述中没有清楚说明", terms=implicit,
                               question="请补充你在" + "、".join(implicit) + "方面实际做过什么；有可核实结果再补充，没有就保留空缺。", requirement_quote="")
    for term in assessment["missing"]:
        add_suggestion(suggestions, kind="gap", source="rules", job_id=job["id"], fact_id=None, before="", after="", reason="现有底稿没有支持该岗位要求的证据，不能只靠改写补齐", terms=[term], question=f"是否有遗漏的 {term} 经历？如有，单独补充并核对事实；如无，保留为能力缺口。", requirement_quote="")
    return suggestions


def validate_rewrite(before, after, fact):
    if not isinstance(after, str) or not after.strip() or len(after) > 3000:
        raise ValueError("改写建议需要 1 到 3000 字的具体文本")
    if after == before:
        raise ValueError("改写与原文相同")
    # These are conservative guards, not a substitute for user confirmation.
    numbers = lambda s: set(re.findall(r"\d+(?:\.\d+)?%?", s))
    if numbers(after) - numbers(before):
        raise ValueError("改写增加了未经原文支持的数字，请先在底稿中核对该事实")
    for term in ("主导", "独立负责", "精通", "专家", "全面负责", "已上线", "正式上线", "规模化落地", "生产部署"):
        if term in after and term not in before:
            raise ValueError("改写可能提高责任或成果等级，请先核对事实")
    supported = " ".join([before, *fact.get("keywords", [])])
    for term in VOCABULARY:
        if contains(after, term) and not contains(supported, term):
            raise ValueError(f"改写新增无证据能力：{term}")
    return after.strip()


def validated_ai_suggestions(profile, jobs, payload):
    byfact, byjob = {f["id"]: f for f in profile["facts"]}, {j["id"]: j for j in jobs}
    if not isinstance(payload, dict) or not isinstance(payload.get("suggestions"), list) or len(payload["suggestions"]) > 6:
        raise ValueError("AI 建议格式错误或超过 6 条")
    result = []
    for raw in payload["suggestions"]:
        if not isinstance(raw, dict):
            raise ValueError("AI 建议必须是对象")
        fid, jid = raw.get("fact_id"), raw.get("job_id")
        if fid not in byfact or jid not in byjob:
            raise ValueError("AI 建议引用了不存在的经历或岗位")
        quote = raw.get("requirement_quote")
        if not isinstance(quote, str) or not quote.strip() or quote not in byjob[jid]["description"]:
            raise ValueError("AI 建议未引用真实岗位原句")
        after = validate_rewrite(byfact[fid]["text"], raw.get("after"), byfact[fid])
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("AI 建议缺少修改理由")
        add_suggestion(result, kind="rewrite", source="ai_draft", job_id=jid, fact_id=fid, before=byfact[fid]["text"], after=after,
                       reason=reason, terms=[], question="请核对改写是否完全符合实际经历。", requirement_quote=quote)
    return result


def compare_cycles(previous, profile, policy, rows):
    if not previous:
        return None
    prior = {r["job"]["id"]: r for r in previous["jobs"]}
    changes, incomparable = [], []
    same_policy = digest(policy) == previous["policy_hash"]
    for r in rows:
        old = prior.get(r["job"]["id"])
        if not old:
            continue
        if not same_policy or digest(old["job"]) != digest(r["job"]):
            incomparable.append(r["job"]["id"])
            continue
        old_expr, new_expr = old["expression"]["score"], r["expression"]["score"]
        changes.append({"job_id": r["job"]["id"], "title": r["job"]["title"], "capability_before": old["assessment"]["score"], "capability_after": r["assessment"]["score"],
                        "expression_before": old_expr, "expression_after": new_expr,
                        "expression_delta": new_expr - old_expr if old_expr is not None and new_expr is not None else None})
    return {"parent_id": previous["id"], "same_policy": same_policy, "comparable_jobs": changes, "changed_job_or_policy": incomparable,
            "note": "只比较岗位内容与筛选规则未变化的共同岗位；表达提升不等于能力增长，也不等于回复率提升。"}


def create_cycle(store, profile, policy, output, parent_id=None, ai=False, top=10):
    validate_profile(profile)
    from .preferences import normalize_policy
    policy = normalize_policy(policy)
    if not 1 <= top <= 50:
        raise ValueError("top 应在 1 到 50 之间")
    init_cycles(store)
    previous = load_cycle(store, parent_id) if parent_id else None
    if previous:
        # Prevent accidentally comparing a different person's profile.
        if previous["profile"]["name"] != profile["name"]:
            raise ValueError("上一轮与当前简历姓名不同")
    rows = []
    for source in store.jobs():
        job, origin = inferred_job(profile, source)
        assessment = match(profile, job, policy)
        if origin == "inferred_partial":
            assessment["unknown"].append("岗位要求由有限词表提取，可能遗漏硬条件，须核对 JD")
            if assessment["status"] != "rejected":
                assessment["status"] = "rejected" if policy["unknown_policy"] == "exclude" else "needs_review"
                if policy["unknown_policy"] == "exclude":
                    assessment["rejected_reasons"].append("岗位要求尚未核实，按设置排除")
        rows.append({"job": job, "requirements_origin": origin, "assessment": assessment,
                     "expression": expression_coverage(profile, assessment), "completeness": job_completeness(job)})
    rows.sort(key=lambda r: (r["assessment"]["status"] == "rejected", bool(r["job"].get("risk_flags")),
                             -r["assessment"]["score"], -len(r["assessment"]["preferred_hits"]),
                             -r["completeness"]["score"], r["job"]["id"]))
    candidates = [r for r in rows if r["assessment"]["status"] != "rejected"][:top]
    market = market_insights(rows, policy["market_min_jobs"])
    suggestions = []
    for row in candidates:
        suggestions.extend(diagnose(profile, row["job"], row["assessment"]))
    if ai and candidates:
        from .llm import propose_rewrites
        jobs = [r["job"] for r in candidates[:5]]
        suggestions.extend(validated_ai_suggestions(profile, jobs, propose_rewrites(profile, jobs)))
    suggestions = annotate_suggestions(suggestions, market)
    cycle_id = uuid.uuid4().hex[:16]
    directory = Path(output).resolve() / cycle_id
    report = {"schema_version": 2, "id": cycle_id, "created_at": now(), "parent_id": parent_id, "profile_hash": digest(profile), "policy_hash": digest(policy),
              "profile": copy.deepcopy(profile), "policy": copy.deepcopy(policy), "search_plan": search_plan(profile, policy), "jobs": rows, "suggestions": suggestions,
              "market": market, "comparison": compare_cycles(previous, profile, policy, rows), "engine": "rules+ai_drafts" if ai else "rules",
              "summary": {"total": len(rows), "candidates": len(candidates), "matched": sum(r["assessment"]["status"] == "matched" for r in rows),
                          "needs_review": sum(r["assessment"]["status"] == "needs_review" for r in rows),
                          "rejected": sum(r["assessment"]["status"] == "rejected" for r in rows),
                          "risk_flagged": sum(bool(r["job"].get("risk_flags")) for r in rows),
                          "duplicate_clusters": len(market["duplicate_groups"])}}
    directory.mkdir(parents=True, exist_ok=False)
    # Generate previews only; do not change the application queue or enable sending.
    for row in candidates:
        row["resume_preview"] = "resumes/" + row["job"]["id"] + "/resume.html"
        export_bundle(tailor(profile, row["job"], row["assessment"]), directory / "resumes" / row["job"]["id"])
    from .assistant_report import render_report
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "report.html").write_text(render_report(report), encoding="utf-8")
    (directory / "decisions.template.json").write_text(json.dumps({"cycle_id": cycle_id, "profile_hash": digest(profile), "decisions": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    with store.db:
        store.db.execute("INSERT INTO resume_cycles VALUES (?,?,?,?,?)", (cycle_id, parent_id, digest(profile), json.dumps(report, ensure_ascii=False), now()))
    return {"cycle_id": cycle_id, "report": str(directory / "report.html"), "json": str(directory / "report.json"), "summary": report["summary"]}


def revise_profile(store, cycle_id, current, decisions, output):
    report = load_cycle(store, cycle_id)
    validate_profile(current)
    if digest(current) != report["profile_hash"] or decisions.get("profile_hash") != report["profile_hash"]:
        raise ValueError("简历已变更或决策不属于此版本，请重新分析")
    if decisions.get("cycle_id") != cycle_id:
        raise ValueError("决策文件不属于这一轮分析")
    if store.db.execute("SELECT 1 FROM resume_revisions WHERE cycle_id=?", (cycle_id,)).fetchone():
        raise ValueError("本轮已处理，请对新版本开始下一轮")
    actions = decisions.get("decisions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("没有待处理的建议决策")
    proposals = {s["id"]: s for s in report["suggestions"]}
    updated = copy.deepcopy(current)
    facts = {f["id"]: f for f in updated["facts"]}
    seen, changed_facts = set(), set()
    for action in actions:
        sid = action.get("suggestion_id")
        if sid not in proposals or sid in seen:
            raise ValueError("未知或重复的建议 ID")
        seen.add(sid)
        if action.get("action") not in ("accept", "reject"):
            raise ValueError("决策只支持 accept 或 reject")
        if action["action"] == "reject":
            continue
        s = proposals[sid]
        if s["kind"] not in ("rewrite", "clarify"):
            raise ValueError("能力缺口不能通过接受建议添加为事实")
        if action.get("confirmed") is not True:
            raise ValueError("接受改写前需要确认符合真实经历：confirmed=true")
        fid = s["fact_id"]
        if fid in changed_facts:
            raise ValueError("同一经历有多条改写，请本轮只选择其中一条")
        after = action.get("text", s["after"])
        # Already-approved variants may include verified metrics that weren't in this particular wording.
        if after not in facts[fid].get("approved_variants", []):
            after = validate_rewrite(s["before"], after, facts[fid])
        if not isinstance(after, str) or not after.strip() or after == s["before"]:
            raise ValueError("请填写不同于原文的实际改写")
        variants = facts[fid].setdefault("approved_variants", [])
        if s["before"] not in variants:
            variants.append(s["before"])
        if after not in variants:
            variants.append(after)
        facts[fid]["text"] = after
        changed_facts.add(fid)
    validate_profile(updated)
    destination = Path(output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting the original resume or prior revision.
    with destination.open("x", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
    try:
        with store.db:
            store.db.execute("INSERT INTO resume_revisions VALUES (?,?,?,?,?,?)", (cycle_id, digest(current), digest(updated), json.dumps(decisions, ensure_ascii=False), json.dumps(updated, ensure_ascii=False), now()))
    except Exception:
        destination.unlink()
        raise
    return {"profile": str(destination), "profile_hash": digest(updated), "changed_facts": sorted(changed_facts), "parent_cycle": cycle_id,
            "next": "用新 profile 运行 analyze，并传入 --parent " + cycle_id}
