"""Shared search preferences: browser requests and local verification use one schema."""
import math
import re
from datetime import datetime, timezone
from .core import contains

LIST_FIELDS = {
    "platforms": "求职平台", "cities": "期望城市", "districts": "期望区域/商圈",
    "target_titles": "目标岗位", "industries": "行业",
    "company_sizes": "公司规模", "funding_stages": "融资阶段", "experience_bands": "岗位经验区间",
    "education_requirements": "岗位学历要求", "job_types": "用工形式", "work_modes": "办公方式",
    "work_schedules": "休息安排", "company_natures": "企业性质", "recruiter_types": "招聘者类型",
    "required_benefits": "必须福利", "excluded_companies": "排除公司", "excluded_terms": "排除关键词",
    "exclude_risk_flags": "排除的风险信号", "preferred_terms": "优先关注关键词",
}
JOB_FIELDS = {"platforms": "source_platform", "cities": "city", "districts": "district",
              "industries": "industry", "company_sizes": "company_size", "funding_stages": "funding_stage",
              "experience_bands": "experience_band", "education_requirements": "required_education", "job_types": "job_type",
              "work_modes": "work_mode", "work_schedules": "work_schedule", "company_natures": "company_nature",
              "recruiter_types": "recruiter_type"}


def parse_salary(text):
    """Parse the pay unit without silently converting day/hour/year to month."""
    result = {"basis": "unknown", "min": None, "max": None, "months": None,
              "annual_min": None, "annual_max": None, "currency": "CNY"}
    if not isinstance(text, str) or not text.strip():
        return result
    if "面议" in text:
        result["basis"] = "negotiable"
        return result
    match_ = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[-–—~～至]\s*(\d+(?:\.\d+)?)\s*(K|k|万|元)", text)
    if not match_:
        return result
    low, high = float(match_[1]), float(match_[2])
    if low > high:
        return result
    unit = match_[3]
    multiplier = 1000 if unit.casefold() == "k" else 10000 if unit == "万" else 1
    low, high = low * multiplier, high * multiplier
    if re.search(r"年薪|/(?:年)", text):
        basis = "yearly"
    elif re.search(r"日薪|/(?:天|日)", text):
        basis = "daily"
    elif re.search(r"时薪|/(?:小时|时)", text):
        basis = "hourly"
    elif re.search(r"月薪|/(?:月)", text) or unit.casefold() == "k":
        basis = "monthly"
    else:
        return result
    result.update(basis=basis, min=low, max=high)
    months = re.search(r"(?:[·x×*]\s*)?(1[0-9]|2[0-4])\s*薪", text, re.I)
    if months and basis == "monthly":
        result["months"] = int(months[1])
        result["annual_min"] = low * result["months"]
        result["annual_max"] = high * result["months"]
    elif basis == "yearly":
        result["annual_min"], result["annual_max"] = low, high
    return result


def parse_monthly_salary(text):
    salary = parse_salary(text)
    return (salary["min"], salary["max"]) if salary["basis"] == "monthly" else (None, None)


def education_level(value):
    for label, rank in (("博士", 5), ("硕士", 4), ("本科", 3), ("大专", 2), ("中专", 1), ("高中", 1), ("不限", 0)):
        if label in str(value or ""):
            return rank
    return None


def experience_min(value):
    text = str(value or "")
    if not text:
        return None
    if any(term in text for term in ("不限", "应届", "在校", "1年以内")):
        return 0
    match_ = re.search(r"(\d+(?:\.\d+)?)\s*(?:年|年以上|-)", text)
    return float(match_[1]) if match_ else None


def recruiter_activity_days(value):
    text = str(value or "").strip()
    if not text:
        return None
    if any(term in text for term in ("刚刚活跃", "当前在线", "今日活跃", "今天活跃")):
        return 0
    match_ = re.search(r"(\d+)\s*(?:天|日)(?:前|内)?活跃|(?:活跃于)?\s*(\d+)\s*(?:天|日)前", text)
    if match_:
        return int(match_[1] or match_[2])
    if "本周活跃" in text:
        return 7
    if "本月活跃" in text:
        return 30
    return None


def age_in_days(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).days)
    except ValueError:
        return None


def normalize_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("求职设置必须是 JSON 对象")
    p = dict(policy)
    for field, label in LIST_FIELDS.items():
        values = p.get(field, [])
        if not isinstance(values, list) or len(values) > 30 or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(label + "必须是最多30项的非空文本数组")
        p[field] = list(dict.fromkeys(v.strip() for v in values))
    if p["platforms"]:
        from .platforms import normalize_platform
        p["platforms"] = list(dict.fromkeys(normalize_platform(v) for v in p["platforms"]))
        if "other" in p["platforms"]:
            raise ValueError("求职平台请使用 boss 或 liepin；other 只用于导入来源")
    if p["recruiter_types"]:
        from .platforms import normalize_recruiter_type
        p["recruiter_types"] = list(dict.fromkeys(normalize_recruiter_type(v) for v in p["recruiter_types"]))
    if p["exclude_risk_flags"]:
        from .core import RISK_PATTERNS
        unknown_risks = [value for value in p["exclude_risk_flags"] if value not in RISK_PATTERNS]
        if unknown_risks:
            raise ValueError("未知风险信号：" + "、".join(unknown_risks))
    for field, default in (("min_monthly_salary", 0), ("max_monthly_salary", None),
                           ("min_annual_salary", 0), ("min_score", 70),
                           ("min_salary_months", None), ("max_job_age_days", None),
                           ("max_recruiter_inactive_days", None), ("market_min_jobs", 2)):
        value = p.get(field, default)
        if value is None and field in ("max_monthly_salary", "min_salary_months", "max_job_age_days", "max_recruiter_inactive_days"):
            p[field] = value
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(field + "必须为有限非负数")
        p[field] = value
    if p["min_score"] > 100:
        raise ValueError("min_score 需要在 0 到 100 之间")
    if p["max_monthly_salary"] is not None and p["max_monthly_salary"] < p["min_monthly_salary"]:
        raise ValueError("期望月薪上限不能低于下限")
    if p["min_salary_months"] is not None and (type(p["min_salary_months"]) is not int or not 1 <= p["min_salary_months"] <= 24):
        raise ValueError("min_salary_months 必须是 1 到 24 的整数或 null")
    if type(p["market_min_jobs"]) is not int or not 1 <= p["market_min_jobs"] <= 50:
        raise ValueError("market_min_jobs 必须是 1 到 50 的整数")
    p.setdefault("active_jobs_only", False)
    if type(p["active_jobs_only"]) is not bool:
        raise ValueError("active_jobs_only 必须为 true 或 false")
    p.setdefault("salary_mode", "floor")
    p.setdefault("unknown_policy", "review")
    if p["salary_mode"] not in ("floor", "overlap"):
        raise ValueError("salary_mode 只支持 floor 或 overlap")
    if p["unknown_policy"] not in ("review", "exclude"):
        raise ValueError("unknown_policy 只支持 review 或 exclude")
    return p


def evaluate_conditions(profile, job, policy):
    p = normalize_policy(policy)
    rejected, unknown = [], []
    if any(contains(job["company"], company) for company in p["excluded_companies"]):
        rejected.append("公司在排除名单")
    for field, job_field in JOB_FIELDS.items():
        values = p[field]
        if not values:
            continue
        value = job.get(job_field)
        if not value:
            unknown.append(LIST_FIELDS[field] + "未知")
        elif field == "education_requirements" and education_level(value) in {education_level(v) for v in values}:
            pass
        elif field == "recruiter_types" and str(value).casefold() in {str(v).casefold() for v in values}:
            pass
        elif value not in values:
            rejected.append(LIST_FIELDS[field] + "不符合要求")
    low, high = job.get("salary_min"), job.get("salary_max")
    if p["min_monthly_salary"] or p["max_monthly_salary"] is not None:
        if p["salary_mode"] == "floor":
            if low is None:
                unknown.append("月薪下限未知（不从宣传文字猜测）")
            elif low < p["min_monthly_salary"]:
                rejected.append("岗位月薪下限低于要求")
        else:
            if low is None or high is None:
                unknown.append("岗位月薪区间不完整")
            elif high < p["min_monthly_salary"] or (p["max_monthly_salary"] is not None and low > p["max_monthly_salary"]):
                rejected.append("岗位月薪与期望区间不重叠")
    if p["min_salary_months"] is not None:
        if job.get("salary_months") is None:
            unknown.append("薪资月数未知")
        elif job["salary_months"] < p["min_salary_months"]:
            rejected.append("薪资月数低于要求")
    if p["min_annual_salary"]:
        annual = job.get("annual_salary_min")
        if annual is None:
            unknown.append("年薪下限未知（不把未说明奖金计入）")
        elif annual < p["min_annual_salary"]:
            rejected.append("岗位年薪下限低于要求")
    if p["required_benefits"]:
        benefits = job.get("benefits", [])
        if not benefits:
            unknown.append("岗位福利未知")
        else:
            missing_benefits = [wanted for wanted in p["required_benefits"] if not any(contains(actual, wanted) or contains(wanted, actual) for actual in benefits)]
            if missing_benefits:
                rejected.append("缺少必须福利：" + "、".join(missing_benefits))
    risk_codes = {item.get("code") for item in job.get("risk_flags", []) if isinstance(item, dict)}
    blocked_risks = [code for code in p["exclude_risk_flags"] if code in risk_codes]
    if blocked_risks:
        rejected.append("命中已设置排除的风险信号：" + "、".join(blocked_risks))
    if p["active_jobs_only"]:
        if job.get("is_active") is None:
            unknown.append("岗位是否仍在招聘未知")
        elif job["is_active"] is False:
            rejected.append("岗位已暂停或关闭")
    if p["max_job_age_days"] is not None:
        age = age_in_days(job.get("published_at"))
        if age is None:
            unknown.append("岗位发布时间未知")
        elif age > p["max_job_age_days"]:
            rejected.append("岗位发布时间早于要求")
    if p["max_recruiter_inactive_days"] is not None:
        inactive = job.get("recruiter_active_days")
        if inactive is None:
            unknown.append("招聘者活跃时间未知")
        elif inactive > p["max_recruiter_inactive_days"]:
            rejected.append("招聘者活跃度低于要求")
    if p["target_titles"] and not any(contains(job["title"], t) for t in p["target_titles"]):
        rejected.append("岗位名称不在目标范围")
    for term in p["excluded_terms"]:
        if contains(job["title"] + "\n" + job["description"], term):
            rejected.append(f"含排除词：{term}（请检查是否是否定表述）")
    # Candidate constraints and the candidate's actual qualifications are different.
    required_years = job.get("min_experience_years")
    if required_years is None:
        required_years = experience_min(job.get("experience_band"))
    if required_years is not None:
        actual = profile.get("years_experience")
        if type(required_years) not in (int, float) or required_years < 0:
            unknown.append("岗位最低工作年限格式待核对")
        elif actual is None:
            unknown.append("简历尚未确认总工作年限")
        elif type(actual) not in (int, float) or actual < 0:
            raise ValueError("years_experience 必须为非负数")
        elif actual < required_years:
            rejected.append("已确认工作年限不足")
    required_degree = job.get("required_education")
    if required_degree and required_degree != "不限":
        actual_degree = profile.get("education_level")
        required_level, actual_level = education_level(required_degree), education_level(actual_degree)
        if required_level is None or actual_level is None:
            unknown.append("岗位学历门槛与实际学历尚未完成核对")
        elif actual_level < required_level:
            rejected.append("已确认学历不满足门槛")
        if "统招" in required_degree:
            if profile.get("education_full_time") is None:
                unknown.append("岗位要求统招学历，简历尚未确认学历性质")
            elif profile["education_full_time"] is False:
                rejected.append("已确认学历性质不满足统招要求")
    searchable = "\n".join([job["title"], job["description"], *job.get("benefits", []), job.get("industry", "")])
    preferred = [term for term in p["preferred_terms"] if contains(searchable, term)]
    if p["unknown_policy"] == "exclude" and unknown:
        rejected.extend("信息缺失按设置排除：" + reason for reason in unknown)
    return rejected, unknown, preferred
