"""Pure functions: validation, conservative matching, grounded tailoring."""
import hashlib
import json
import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


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


PLATFORM_TRACKING_QUERY_KEYS = {
    "boss": {"ka", "lid", "securityid", "sessionid", "session_id", "sourcetype"},
    "liepin": {"pgref", "mscid", "sessionid", "session_id", "sourcetype"},
}


def job_identity_url(url):
    """Remove known navigation trackers while retaining job-identifying queries."""
    p = urlsplit(canonical_url(url))
    host = (p.hostname or "").lower()
    platform = "boss" if host == "zhipin.com" or host.endswith(".zhipin.com") else "liepin" if host == "liepin.com" or host.endswith(".liepin.com") else "other"
    tracking = PLATFORM_TRACKING_QUERY_KEYS.get(platform, set())
    query = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                   if k.casefold() not in tracking and not k.casefold().startswith("utm_"))
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query, doseq=True), ""))


def _identity_text(value):
    return re.sub(r"[\s\-—_·•|｜]+", "", str(value or "")).casefold()


def job_cluster_id(job):
    """Conservative duplicate group: exact normalized identity and JD text."""
    value = {k: _identity_text(job.get(k)) for k in ("company", "title", "city", "description")}
    return digest(value)[:20]


RISK_PATTERNS = {
    "fee": ("要求付费/押金", r"押金|保证金|培训费|服装费|建档费|入职费|报名费"),
    "training_loan": ("培训或贷款", r"培训贷|分期贷款|先培训后就业|付费培训"),
    "financial_task": ("刷单/垫付/转账", r"刷单|垫付|充值返利|先行转账"),
    "off_platform_contact": ("引导站外联系", r"加微信|微信联系|加QQ|QQ联系"),
    "pyramid_scheme": ("疑似拉人头", r"拉人头|发展下线|发展下级|面试.*带行李"),
}


def detect_risk_flags(text):
    """Surface review signals; a text hit alone never proves misconduct."""
    result = []
    for code, (label, pattern) in RISK_PATTERNS.items():
        for match_ in re.finditer(pattern, text, re.I):
            prefix = text[max(0, match_.start() - 8):match_.start()]
            if re.search(r"(?:不|无须|无需|不会|严禁|禁止|不收|不交|零)\s*$", prefix):
                continue
            result.append({"code": code, "label": label, "term": match_.group(0),
                           "note": "文本信号，仅提示人工核查上下文"})
            break
    return result


def validate_profile(p):
    required_text(p, "name")
    required_text(p, "headline")
    if p.get("confirmed") is not True:
        raise ValueError("请核对简历事实，并将 confirmed 设为 true")
    if p.get("years_experience") is not None and (type(p["years_experience"]) not in (int, float) or not math.isfinite(p["years_experience"]) or p["years_experience"] < 0):
        raise ValueError("years_experience 必须为非负数或 null")
    if p.get("education_level") is not None and (not isinstance(p["education_level"], str) or not p["education_level"].strip()):
        raise ValueError("education_level 必须是非空文本或 null")
    if p.get("education_full_time") is not None and type(p["education_full_time"]) is not bool:
        raise ValueError("education_full_time 必须为 true、false 或 null")
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
    j["identity_url"] = job_identity_url(j["url"])
    j["id"] = digest(j["identity_url"])[:20]
    j.setdefault("city", "")
    for field in ("district", "business_district", "industry", "company_size", "funding_stage",
                  "company_nature", "experience_band", "required_education", "job_type", "work_mode",
                  "work_schedule", "recruiter_type", "recruiter_name", "recruiter_activity",
                  "salary_text", "published_at", "captured_at"):
        value = j.setdefault(field, "")
        if not isinstance(value, str):
            raise ValueError(field + " 必须是文本")
        j[field] = value.strip()
    from .platforms import normalize_platform, normalize_recruiter_type
    j["source_platform"] = normalize_platform(j.get("source_platform"), j["url"])
    j["recruiter_type"] = normalize_recruiter_type(j["recruiter_type"])
    j.setdefault("requirements", [])
    if not isinstance(j["requirements"], list) or any(not isinstance(v, str) or not v.strip() for v in j["requirements"]):
        raise ValueError("requirements 必须是关键词数组")
    j["requirements"] = list(dict.fromkeys(v.strip() for v in j["requirements"]))
    for field in ("benefits", "tags"):
        values = j.setdefault(field, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(field + " 必须是非空文本数组")
        j[field] = list(dict.fromkeys(v.strip() for v in values))
    if j["salary_text"]:
        from .preferences import parse_salary
        salary = parse_salary(j["salary_text"])
        j.setdefault("salary_basis", salary["basis"])
        if salary["basis"] == "monthly":
            if j.get("salary_min") is None:
                j["salary_min"] = salary["min"]
            if j.get("salary_max") is None:
                j["salary_max"] = salary["max"]
        if j.get("salary_months") is None:
            j["salary_months"] = salary["months"]
        if j.get("annual_salary_min") is None:
            j["annual_salary_min"] = salary["annual_min"]
        if j.get("annual_salary_max") is None:
            j["annual_salary_max"] = salary["annual_max"]
    else:
        j.setdefault("salary_basis", "monthly" if j.get("salary_min") is not None or j.get("salary_max") is not None else "unknown")
        j.setdefault("salary_months", None)
        j.setdefault("annual_salary_min", None)
        j.setdefault("annual_salary_max", None)
    for k in ("salary_min", "salary_max"):
        if j.get(k) is not None and (type(j[k]) not in (int, float) or not math.isfinite(j[k]) or j[k] < 0):
            raise ValueError(f"{k} 必须为非负月薪数值（元）或 null")
    if j.get("salary_min") is not None and j.get("salary_max") is not None and j["salary_min"] > j["salary_max"]:
        raise ValueError("岗位薪资上下限颠倒")
    if j.get("salary_basis") not in ("monthly", "yearly", "daily", "hourly", "negotiable", "unknown"):
        raise ValueError("salary_basis 不合法")
    for k in ("annual_salary_min", "annual_salary_max"):
        if j.get(k) is not None and (type(j[k]) not in (int, float) or not math.isfinite(j[k]) or j[k] < 0):
            raise ValueError(f"{k} 必须为非负年薪数值（元）或 null")
    if j.get("annual_salary_min") is not None and j.get("annual_salary_max") is not None and j["annual_salary_min"] > j["annual_salary_max"]:
        raise ValueError("岗位年薪上下限颠倒")
    if j.get("salary_months") is not None and (type(j["salary_months"]) is not int or not 1 <= j["salary_months"] <= 24):
        raise ValueError("salary_months 必须是 1 到 24 的整数或 null")
    if j.get("recruiter_active_days") is None and j["recruiter_activity"]:
        from .preferences import recruiter_activity_days
        j["recruiter_active_days"] = recruiter_activity_days(j["recruiter_activity"])
    for field in ("min_experience_years", "recruiter_active_days"):
        if j.get(field) is not None and (type(j[field]) not in (int, float) or not math.isfinite(j[field]) or j[field] < 0):
            raise ValueError(field + " 必须为非负数或 null")
    if j.get("is_active") is not None and type(j["is_active"]) is not bool:
        raise ValueError("is_active 必须为 true、false 或 null")
    j.setdefault("is_active", None)
    j["cluster_id"] = job_cluster_id(j)
    j["risk_flags"] = detect_risk_flags(j["title"] + "\n" + j["description"])
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
