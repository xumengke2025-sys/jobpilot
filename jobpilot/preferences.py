"""Shared search preferences: browser requests and local verification use one schema."""
import math
import re
from .core import contains

LIST_FIELDS = {
    "cities": "期望城市", "target_titles": "目标岗位", "industries": "行业",
    "company_sizes": "公司规模", "funding_stages": "融资阶段", "experience_bands": "岗位经验区间",
    "education_requirements": "岗位学历要求", "job_types": "用工形式", "work_modes": "办公方式",
    "work_schedules": "休息安排", "excluded_companies": "排除公司", "excluded_terms": "排除关键词",
    "preferred_terms": "优先关注关键词",
}
JOB_FIELDS = {"cities": "city", "industries": "industry", "company_sizes": "company_size", "funding_stages": "funding_stage",
              "experience_bands": "experience_band", "education_requirements": "required_education", "job_types": "job_type",
              "work_modes": "work_mode", "work_schedules": "work_schedule"}


def parse_monthly_salary(text):
    """Only explicit K/monthly ranges; do not turn annual/day/hour pay into monthly."""
    if not isinstance(text, str) or re.search(r"[万Kk元]/?(年|天|日|小时|时)|年薪|时薪|日薪|面议", text):
        return None, None
    m = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[-–~]\s*(\d+(?:\.\d+)?)\s*([Kk])", text)
    multiplier = 1000
    if not m:
        m = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[-–~]\s*(\d+(?:\.\d+)?)\s*元/月", text)
        multiplier = 1
    if not m:
        return None, None
    low, high = float(m[1]) * multiplier, float(m[2]) * multiplier
    return (low, high) if 0 <= low <= high else (None, None)


def normalize_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("求职设置必须是 JSON 对象")
    p = dict(policy)
    for field, label in LIST_FIELDS.items():
        values = p.get(field, [])
        if not isinstance(values, list) or len(values) > 30 or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(label + "必须是最多30项的非空文本数组")
        p[field] = list(dict.fromkeys(v.strip() for v in values))
    for field, default in (("min_monthly_salary", 0), ("max_monthly_salary", None), ("min_score", 70)):
        value = p.get(field, default)
        if value is None and field == "max_monthly_salary":
            p[field] = value
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(field + "必须为有限非负数")
        p[field] = value
    if p["min_score"] > 100:
        raise ValueError("min_score 需要在 0 到 100 之间")
    if p["max_monthly_salary"] is not None and p["max_monthly_salary"] < p["min_monthly_salary"]:
        raise ValueError("期望月薪上限不能低于下限")
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
    if p["target_titles"] and not any(contains(job["title"], t) for t in p["target_titles"]):
        rejected.append("岗位名称不在目标范围")
    for term in p["excluded_terms"]:
        if contains(job["title"] + "\n" + job["description"], term):
            rejected.append(f"含排除词：{term}（请检查是否是否定表述）")
    # Candidate constraints and the candidate's actual qualifications are different.
    required_years = job.get("min_experience_years")
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
    levels = {"不限": 0, "高中": 1, "中专": 1, "大专": 2, "本科": 3, "硕士": 4, "博士": 5}
    required_degree = job.get("required_education")
    if required_degree and required_degree != "不限":
        actual_degree = profile.get("education_level")
        if required_degree not in levels or actual_degree not in levels:
            unknown.append("岗位学历门槛与实际学历尚未完成核对")
        elif levels[actual_degree] < levels[required_degree]:
            rejected.append("已确认学历不满足门槛")
    preferred = [term for term in p["preferred_terms"] if contains(job["title"] + "\n" + job["description"], term)]
    if p["unknown_policy"] == "exclude" and unknown:
        rejected.extend("信息缺失按设置排除：" + reason for reason in unknown)
    return rejected, unknown, preferred
