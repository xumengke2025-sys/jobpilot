import unittest
from pathlib import Path

from jobpilot.core import match, read_json
from jobpilot.preferences import normalize_policy, parse_monthly_salary
from jobpilot.search_filters import apply_search_conditions

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


if __name__ == "__main__":
    unittest.main()
