import unittest
from pathlib import Path

from jobpilot.core import match, read_json, validate_job
from jobpilot.preferences import normalize_policy, parse_monthly_salary, parse_salary, recruiter_activity_days
from jobpilot.search_filters import apply_search_conditions, salary_band_keys

ROOT = Path(__file__).resolve().parents[1]


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.profile = read_json(ROOT / "examples/profile.json")
        self.job = read_json(ROOT / "examples/jobs.json")[0]
        self.policy = read_json(ROOT / "examples/policy.json")

    def test_salary_floor_does_not_use_advertised_maximum(self):
        self.job.update(salary_min=10000, salary_max=40000)
        self.assertEqual(match(self.profile, self.job, self.policy)["status"], "rejected")

    def test_salary_overlap_is_explicit(self):
        self.job.update(salary_min=10000, salary_max=40000)
        policy = {**self.policy, "max_monthly_salary": 30000, "salary_mode": "overlap"}
        self.assertEqual(match(self.profile, self.job, policy)["status"], "matched")

    def test_unknown_requested_work_mode_is_not_assumed(self):
        self.assertEqual(match(self.profile, self.job, {**self.policy, "work_modes": ["远程"]})["status"], "needs_review")

    def test_unknown_can_be_excluded_by_preference(self):
        self.assertEqual(match(self.profile, self.job, {**self.policy, "work_modes": ["远程"], "unknown_policy": "exclude"})["status"], "rejected")

    def test_industry_and_job_type_are_both_checked(self):
        self.job.update(industry="证券", job_type="实习")
        self.assertEqual(match(self.profile, self.job, {**self.policy, "industries": ["证券"], "job_types": ["全职"]})["status"], "rejected")

    def test_education_is_candidate_qualification_not_just_filter(self):
        self.profile["education_level"] = "本科"
        self.job["required_education"] = "硕士"
        self.assertEqual(match(self.profile, self.job, {**self.policy, "education_requirements": ["硕士"]})["status"], "rejected")

    def test_years_experience_is_verified(self):
        self.profile["years_experience"] = 2
        self.job["min_experience_years"] = 5
        self.assertEqual(match(self.profile, self.job, self.policy)["status"], "rejected")

    def test_preferred_terms_do_not_increase_evidence_score(self):
        a = match(self.profile, self.job, self.policy)
        b = match(self.profile, self.job, {**self.policy, "preferred_terms": ["RAG"]})
        self.assertEqual(a["score"], b["score"])
        self.assertEqual(b["preferred_hits"], ["RAG"])

    def test_invalid_ranges_and_nan_are_rejected(self):
        for p in ({"min_monthly_salary": 50000, "max_monthly_salary": 20000}, {"min_score": float("nan")}, {"cities": "上海"}):
            with self.assertRaises(ValueError):
                normalize_policy(p)

    def test_salary_units(self):
        self.assertEqual(parse_monthly_salary("20-30K·13薪"), (20000, 30000))
        self.assertEqual(parse_monthly_salary("20000-30000元/月"), (20000, 30000))
        for text in ("20-30万/年", "100-200元/天", "20-30K/年", "面议", "30-20K"):
            self.assertEqual(parse_monthly_salary(text), (None, None))

    def test_platform_salary_formats_keep_period_and_salary_months(self):
        monthly = parse_salary("20-30k·14薪")
        self.assertEqual((monthly["basis"], monthly["min"], monthly["months"], monthly["annual_min"]),
                         ("monthly", 20000, 14, 280000))
        self.assertEqual(parse_salary("2-3万/月")["min"], 20000)
        self.assertEqual(parse_salary("20-30万/年")["basis"], "yearly")
        self.assertEqual(parse_salary("100-200元/天")["basis"], "daily")
        self.assertEqual(parse_salary("20-30元/时")["basis"], "hourly")

    def test_salary_text_populates_structured_fields_and_annual_policy(self):
        job = validate_job({**self.job, "salary_min": None, "salary_max": None, "salary_text": "20-30k·13薪"})
        self.assertEqual(job["annual_salary_min"], 260000)
        self.assertEqual(match(self.profile, job, {**self.policy, "min_annual_salary": 270000})["status"], "rejected")

    def test_liepin_full_time_degree_is_not_silently_assumed(self):
        self.profile["education_level"] = "本科"
        self.profile.pop("education_full_time", None)
        self.job["required_education"] = "统招本科"
        result = match(self.profile, self.job, self.policy)
        self.assertEqual(result["status"], "needs_review")
        self.assertTrue(any("学历性质" in reason for reason in result["unknown"]))

    def test_benefit_activity_and_job_availability_preferences(self):
        job = {**self.job, "benefits": ["五险一金", "补充医疗"], "recruiter_active_days": 12, "is_active": False}
        policy = {**self.policy, "required_benefits": ["五险一金"], "max_recruiter_inactive_days": 7, "active_jobs_only": True}
        reasons = match(self.profile, job, policy)["rejected_reasons"]
        self.assertIn("招聘者活跃度低于要求", reasons)
        self.assertIn("岗位已暂停或关闭", reasons)

    def test_platform_activity_labels_are_parsed_conservatively(self):
        self.assertEqual(recruiter_activity_days("刚刚活跃"), 0)
        self.assertEqual(recruiter_activity_days("3日内活跃"), 3)
        self.assertEqual(recruiter_activity_days("本周活跃"), 7)
        self.assertIsNone(recruiter_activity_days("近期活跃"))


class FilterLocator:
    def __init__(self, page, key):
        self.page, self.key = page, key
    def count(self):
        return 1
    def wait_for(self, **kwargs):
        pass
    def fill(self, value):
        self.page.values[self.key] = value
        self.page.actions.append(("fill", self.key, value))
    def input_value(self):
        return self.page.values.get(self.key, "")
    def inner_text(self):
        return self.page.values.get(self.key, "")
    def select_option(self, label):
        self.page.actions.append(("select", self.key, label))
        self.page.values[self.key] = label if self.page.readback else "错误选项"
    def click(self):
        self.page.actions.append(("click", self.key))


class FilterPage:
    url = "https://example.invalid/jobs"
    def __init__(self):
        self.values, self.actions, self.readback = {}, [], True
    def locator(self, key):
        return FilterLocator(self, key)


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.page = FilterPage()
        self.config = {"allowed_hosts": ["example.invalid"], "search": {
            "query": {"css": "#query"}, "submit": {"css": "#search"}, "reset_filters": {"css": "#reset"},
            "filters": {"cities": {"kind": "select", "locator": {"css": "#city"}, "selected": {"css": "#city"}, "options": {"上海": "上海"}}}}}
        self.request = {"query": "AI 产品经理 RAG", "city": "上海"}
    def test_search_and_select_have_verified_receipts(self):
        result = apply_search_conditions(self.page, self.config, self.request, {"cities": ["上海"]})
        self.assertEqual(result["applied"][0]["selected"], ["上海"])
        self.assertIn(("fill", "#query", "AI 产品经理 RAG"), self.page.actions)
    def test_unmapped_salary_is_explicitly_local_only(self):
        result = apply_search_conditions(self.page, self.config, self.request, {"cities": ["上海"], "min_monthly_salary": 20000})
        self.assertEqual(result["local_only"][0]["field"], "salary")
    def test_strict_mode_stops_before_any_page_operation(self):
        with self.assertRaises(ValueError):
            apply_search_conditions(self.page, self.config, self.request, {"cities": ["上海"], "min_monthly_salary": 20000}, strict=True)
        self.assertEqual(self.page.actions, [])
    def test_wrong_selected_condition_stops(self):
        self.page.readback = False
        with self.assertRaisesRegex(ValueError, "预期"):
            apply_search_conditions(self.page, self.config, self.request, {"cities": ["上海"]})

    def test_single_select_salary_does_not_drop_valid_higher_bands(self):
        control = {"multiple": False, "bands": [
            {"key": "20-50", "label": "20-50K", "min": 20000, "max": 50000},
            {"key": "50+", "label": "50K以上", "min": 50000, "max": None},
        ]}
        keys = salary_band_keys(control, normalize_policy({"min_monthly_salary": 25000, "salary_mode": "floor"}))
        self.assertEqual(keys, ["20-50", "50+"])
        self.config["search"]["filters"]["salary"] = {**control, "kind": "menu", "locator": {"css": "#salary"}, "selected": {"css": "#salary-selected"}}
        result = apply_search_conditions(self.page, self.config, self.request, {"cities": ["上海"], "min_monthly_salary": 25000})
        self.assertIn("salary", [item["field"] for item in result["local_only"]])


if __name__ == "__main__":
    unittest.main()
