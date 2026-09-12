"""Platform differences that affect search, matching and action receipts.

This module deliberately stores semantic capabilities, not CSS selectors.  A
selector adapter still has to be checked against the user's logged-in page.
"""
from urllib.parse import urlencode, urlsplit


PLATFORM_SPECS = {
    "boss": {
        "name": "BOSS直聘",
        "entry_url": "https://www.zhipin.com/web/geek/job",
        "query_parameter": "query",
        "interaction_model": "direct_chat",
        "actors": ["boss", "company_hr"],
        "action_note": "“发起沟通”、消息发送和附件发送是三个不同回执，不能把打开会话当作已投简历。",
        "filter_coverage": {
            "cities": "site_exact",
            "districts": "site_exact",
            "salary": "site_band",
            "industries": "site_exact",
            "company_sizes": "site_exact",
            "funding_stages": "site_exact",
            "experience_bands": "site_exact",
            "education_requirements": "site_exact",
            "job_types": "site_or_local",
            "company_natures": "local_only",
            "recruiter_types": "local_only",
            "required_benefits": "local_only",
            "work_modes": "local_only",
            "work_schedules": "local_only",
            "freshness": "local_only",
            "recruiter_activity": "local_only",
        },
        "workflow": [
            "discovered", "shortlisted", "submitted", "contacted", "message_sent",
            "resume_requested", "attachment_sent", "replied", "interview",
            "offer", "rejected", "closed", "uncertain",
        ],
    },
    "liepin": {
        "name": "猎聘",
        "entry_url": "https://www.liepin.com/zhaopin/",
        "query_parameter": None,
        "interaction_model": "application_and_chat",
        "actors": ["company_hr", "headhunter"],
        "action_note": "“投递简历”和在线沟通是两条入口；需记录企业招聘方或猎头身份，并分别核对投递与消息回执。",
        "filter_coverage": {
            "cities": "site_exact",
            "districts": "site_exact",
            "salary": "site_band",
            "industries": "site_exact",
            "company_sizes": "site_exact",
            "funding_stages": "site_or_local",
            "experience_bands": "site_exact",
            "education_requirements": "site_exact",
            "job_types": "site_or_local",
            "company_natures": "site_or_local",
            "recruiter_types": "local_only",
            "required_benefits": "local_only",
            "work_modes": "local_only",
            "work_schedules": "local_only",
            "freshness": "local_only",
            "recruiter_activity": "local_only",
        },
        "workflow": [
            "discovered", "shortlisted", "submitted", "contacted",
            "message_sent", "resume_requested", "attachment_sent", "replied", "interview",
            "offer", "rejected", "closed", "uncertain",
        ],
    },
    "other": {
        "name": "其他来源",
        "entry_url": "",
        "query_parameter": None,
        "interaction_model": "unknown",
        "actors": [],
        "action_note": "需按站点实际页面区分投递、沟通和附件回执。",
        "filter_coverage": {},
        "workflow": [
            "discovered", "shortlisted", "submitted", "contacted",
            "message_sent", "attachment_sent", "replied", "interview",
            "offer", "rejected", "closed", "uncertain",
        ],
    },
}

ALIASES = {
    "boss直聘": "boss", "zhipin": "boss", "boss": "boss",
    "猎聘": "liepin", "liepin": "liepin", "other": "other", "其他": "other",
}

FILTER_LABELS = {
    "cities": "城市", "districts": "区域/商圈", "salary": "薪酬",
    "industries": "行业", "company_sizes": "公司规模", "funding_stages": "融资阶段",
    "experience_bands": "岗位经验", "education_requirements": "学历",
    "job_types": "用工形式", "company_natures": "企业性质",
    "recruiter_types": "招聘者类型", "required_benefits": "必须福利",
    "work_modes": "办公方式", "work_schedules": "休息安排",
    "freshness": "发布时间", "recruiter_activity": "招聘者活跃度",
    "availability": "岗位状态", "risk_flags": "风险信号",
}


def infer_platform(url):
    host = (urlsplit(url).hostname or "").lower()
    if host == "zhipin.com" or host.endswith(".zhipin.com"):
        return "boss"
    if host == "liepin.com" or host.endswith(".liepin.com"):
        return "liepin"
    return "other"


def normalize_platform(value=None, url=""):
    if value is None or (isinstance(value, str) and not value.strip()):
        return infer_platform(url)
    if not isinstance(value, str) or value.strip().casefold() not in ALIASES:
        raise ValueError("source_platform 仅支持 boss、liepin 或 other")
    platform = ALIASES[value.strip().casefold()]
    inferred = infer_platform(url) if url else "other"
    if inferred in ("boss", "liepin") and platform != inferred:
        raise ValueError("source_platform 与岗位 URL 域名不一致")
    return platform


def platform_spec(platform):
    platform = normalize_platform(platform)
    return PLATFORM_SPECS[platform]


def normalize_recruiter_type(value):
    text = str(value or "").strip()
    folded = text.casefold()
    if not text:
        return ""
    if "猎头" in text or folded == "headhunter":
        return "headhunter"
    if folded in ("boss", "老板", "创始人", "负责人"):
        return "boss"
    if folded in ("hr", "company_hr") or any(term in text for term in ("人事", "招聘", "人才")):
        return "company_hr"
    return text


def search_entry(platform, query):
    spec = platform_spec(platform)
    if not spec["entry_url"]:
        raise ValueError("该来源没有配置公开搜索入口")
    parameter = spec["query_parameter"]
    return spec["entry_url"] + ("?" + urlencode({parameter: query}) if parameter else "")


def platform_filter_plan(platform, policy, city=""):
    """Describe what the site may narrow and what must be checked locally.

    `site_*` is a semantic plan only.  Live labels and selectors come from a
    verified adapter, and the original policy is always applied after capture.
    """
    spec = platform_spec(platform)
    coverage = spec["filter_coverage"]
    requested = {
        "cities": [city] if city else policy.get("cities", []),
        "districts": policy.get("districts", []),
        "industries": policy.get("industries", []),
        "company_sizes": policy.get("company_sizes", []),
        "funding_stages": policy.get("funding_stages", []),
        "experience_bands": policy.get("experience_bands", []),
        "education_requirements": policy.get("education_requirements", []),
        "job_types": policy.get("job_types", []),
        "company_natures": policy.get("company_natures", []),
        "recruiter_types": policy.get("recruiter_types", []),
        "required_benefits": policy.get("required_benefits", []),
        "work_modes": policy.get("work_modes", []),
        "work_schedules": policy.get("work_schedules", []),
    }
    if policy.get("min_monthly_salary") or policy.get("max_monthly_salary") is not None or policy.get("min_annual_salary") or policy.get("min_salary_months") is not None:
        requested["salary"] = {
            "monthly_min": policy.get("min_monthly_salary", 0),
            "monthly_max": policy.get("max_monthly_salary"),
            "annual_min": policy.get("min_annual_salary", 0),
            "minimum_months": policy.get("min_salary_months"),
            "mode": policy.get("salary_mode", "floor"),
        }
    if policy.get("max_job_age_days") is not None:
        requested["freshness"] = {"max_days": policy["max_job_age_days"]}
    if policy.get("max_recruiter_inactive_days") is not None:
        requested["recruiter_activity"] = {"max_days": policy["max_recruiter_inactive_days"]}
    if policy.get("active_jobs_only"):
        requested["availability"] = ["招聘中"]
    if policy.get("exclude_risk_flags"):
        requested["risk_flags"] = policy["exclude_risk_flags"]
    result = []
    for field, values in requested.items():
        if values in ([], {}, None, ""):
            continue
        mode = coverage.get(field, "local_only")
        note = {
            "site_exact": "可尝试在网页选择；采集后仍回读并复核",
            "site_band": "网页通常是粗区间；只作候选集缩小，采集后按原始数值复核",
            "site_or_local": "不同页面可能没有此筛选；缺少映射时转本地复核",
            "local_only": "不依赖网页筛选，采集后本地复核",
        }[mode]
        result.append({"field": field, "label": FILTER_LABELS[field], "values": values, "coverage": mode, "note": note})
    return result


def allowed_receipt_states(platform):
    return set(platform_spec(platform)["workflow"])
