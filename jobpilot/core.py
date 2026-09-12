"""Pure functions: validation, conservative matching, grounded tailoring."""
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit


def read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def required_text(obj, field):
    value = obj.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空文本")
    return value.strip()


def canonical_url(url):
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("岗位 URL 必须是无账号密码的 HTTP(S) 链接")
    # Preserve query: some ATS use query parameters as the actual job identity.
    return urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", p.query, ""))


def validate_profile(p):
    required_text(p, "name")
    required_text(p, "headline")
    if p.get("confirmed") is not True:
        raise ValueError("请核对简历事实，并将 confirmed 设为 true")
    facts = p.get("facts", [])
    if not facts:
        raise ValueError("至少提供一条已确认的经历事实")
    ids = set()
    for f in facts:
        fid = required_text(f, "id")
        if fid in ids:
            raise ValueError(f"重复经历 ID: {fid}")
        ids.add(fid)
        for k in ("text", "organization", "role", "period", "project"):
            required_text(f, k)
        if f.get("confirmed") is not True:
            raise ValueError(f"经历 {fid} 尚未确认")
        if f.get("stage") not in ("production", "pilot", "prototype", "research"):
            raise ValueError(f"经历 {fid} 的 stage 不合法")
        for k in ("keywords", "approved_variants"):
            if not isinstance(f.get(k, []), list) or any(not isinstance(v, str) or not v.strip() for v in f.get(k, [])):
                raise ValueError(f"经历 {fid}: {k} 必须是非空文本数组")
    return p


def validate_job(j):
    j = dict(j)
    for k in ("title", "company", "description", "url"):
        j[k] = required_text(j, k)
    j["url"] = canonical_url(j["url"])
    j["id"] = digest(j["url"])[:20]
    j.setdefault("city", "")
    j.setdefault("requirements", [])
    if not isinstance(j["requirements"], list) or any(not isinstance(v, str) or not v.strip() for v in j["requirements"]):
        raise ValueError("requirements 必须是关键词数组")
    for k in ("salary_min", "salary_max"):
        if j.get(k) is not None and (type(j[k]) not in (int, float) or j[k] < 0):
            raise ValueError(f"{k} 必须为非负月薪数值（元）或 null")
    if j.get("salary_min") is not None and j.get("salary_max") is not None and j["salary_min"] > j["salary_max"]:
        raise ValueError("岗位薪资上下限颠倒")
    return j


def contains(text, term):
    text, term = text.casefold(), term.casefold().strip()
    if not term:
        return False
    if re.fullmatch(r"[a-z0-9+#. -]+", term):
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text))
    return term in text


def match(p, j, policy):
    """Score is coverage, not an interview probability. Unknown hard facts never pass."""
    validate_profile(p)
    j = validate_job(j)
    from .preferences import evaluate_conditions, normalize_policy
    policy = normalize_policy(policy)
    reject, unknown, preferred = evaluate_conditions(p, j, policy)
    if not j.get("requirements"):
        unknown.append("尚未整理岗位技能要求 requirements")
    evidence, missing = {}, []
    for term in j.get("requirements", []):
        ids = [f["id"] for f in p["facts"] if any(contains(k, term) or contains(term, k) for k in f.get("keywords", []))]
        if ids:
            evidence[term] = ids
        else:
            missing.append(term)
    score = round(100 * len(evidence) / max(1, len(set(j.get("requirements", [])))))
    threshold = policy.get("min_score", 70)
    if not 0 <= threshold <= 100:
        raise ValueError("min_score 需要在 0 到 100 之间")
    status = "rejected" if reject else "needs_review" if unknown or score < threshold else "matched"
    return {"status": status, "score": score, "evidence": evidence, "missing": missing, "rejected_reasons": reject, "unknown": unknown, "preferred_hits": preferred}


def tailor(p, j, assessment, selection=None):
    """Model may select/order only, never add unverified claims or free-form prose."""
    byid = {f["id"]: f for f in p["facts"]}
    hits = [fid for ids in assessment["evidence"].values() for fid in ids]
    default = sorted(p["facts"], key=lambda f: hits.count(f["id"]), reverse=True)
    if selection is None:
        selection = {"items": [{"id": f["id"], "variant": 0} for f in default], "keywords": list(assessment["evidence"])}
    items = selection.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("模型未返回合法经历选择")
    selected, seen = [], set()
    for item in items:
        fid, index = item.get("id"), item.get("variant", 0)
        if fid not in byid or fid in seen:
            raise ValueError("模型返回未知或重复经历 ID")
        fact = byid[fid]
        variants = [fact["text"], *fact.get("approved_variants", [])]
        if type(index) is not int or not 0 <= index < len(variants):
            raise ValueError("模型返回未确认的改写版本")
        seen.add(fid)
        selected.append({**fact, "text": variants[index], "variant": index})
    keywords = selection.get("keywords", [])
    if not isinstance(keywords, list) or any(not isinstance(k, str) or k not in assessment["evidence"] for k in keywords):
        raise ValueError("模型增加了无证据支持的关键词")
    if any(not set(assessment["evidence"][k]).intersection(seen) for k in keywords):
        raise ValueError("关键词证据未包含在本版简历中")
    greeting = f"您好，我关注贵公司的{j['title']}岗位。{p['headline']}。"
    if selected:
        greeting += "相关经历：" + selected[0]["text"]
    greeting += "。希望进一步了解岗位要求。"
    return {"name": p["name"], "headline": p["headline"], "contact": p.get("contact", ""), "education": p.get("education", []), "employment": p.get("employment", []), "keywords": list(dict.fromkeys(keywords)), "facts": selected, "greeting": greeting, "job": j, "assessment": assessment, "profile_hash": digest(p)}
