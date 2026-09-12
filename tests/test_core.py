import copy
import tempfile
import unittest
from pathlib import Path

from jobpilot.core import canonical_url, contains, digest, match, read_json, tailor, validate_job, validate_profile
from jobpilot.export import render_resume
from jobpilot.store import Store

ROOT = Path(__file__).resolve().parents[1]


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.p = read_json(ROOT / "examples/profile.json")
        self.policy = read_json(ROOT / "examples/policy.json")
        self.jobs = read_json(ROOT / "examples/jobs.json")

    def test_relevant_job_has_fact_evidence(self):
        result = match(self.p, self.jobs[0], self.policy)
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["evidence"]["RAG"], ["F001"])

    def test_unknown_salary_never_auto_passes(self):
        self.jobs[0]["salary_min"] = None
        self.assertEqual(match(self.p, self.jobs[0], self.policy)["status"], "needs_review")

    def test_excluded_company_overrides_high_score(self):
        result = match(self.p, self.jobs[2], self.policy)
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["status"], "rejected")

    def test_unsupported_skills_are_missing(self):
        result = match(self.p, self.jobs[1], self.policy)
        self.assertEqual(result["missing"], ["CUDA", "分布式训练"])
        self.assertEqual(result["status"], "needs_review")

    def test_unconfirmed_facts_are_rejected(self):
        self.p["facts"][0]["confirmed"] = False
        with self.assertRaises(ValueError):
            validate_profile(self.p)

    def test_duplicate_fact_ids_are_rejected(self):
        self.p["facts"][1]["id"] = "F001"
        with self.assertRaises(ValueError):
            validate_profile(self.p)

    def test_model_cannot_invent_experience(self):
        assessment = match(self.p, self.jobs[0], self.policy)
        with self.assertRaises(ValueError):
            tailor(self.p, self.jobs[0], assessment, {"items": [{"id": "invented", "variant": 0}]})

    def test_model_cannot_invent_keywords(self):
        assessment = match(self.p, self.jobs[0], self.policy)
        with self.assertRaises(ValueError):
            tailor(self.p, self.jobs[0], assessment, {"items": [{"id": "F001", "variant": 0}], "keywords": ["CUDA"]})

    def test_keyword_requires_selected_evidence(self):
        assessment = match(self.p, self.jobs[0], self.policy)
        with self.assertRaises(ValueError):
            tailor(self.p, self.jobs[0], assessment, {"items": [{"id": "F002", "variant": 0}], "keywords": ["RAG"]})

    def test_only_approved_rewording_is_used(self):
        assessment = match(self.p, self.jobs[0], self.policy)
        bundle = tailor(self.p, self.jobs[0], assessment, {"items": [{"id": "F001", "variant": 1}], "keywords": ["RAG"]})
        self.assertEqual(bundle["facts"][0]["text"], self.p["facts"][0]["approved_variants"][0])
        self.assertEqual(bundle["facts"][0]["stage"], "prototype")
        with self.assertRaises(ValueError):
            tailor(self.p, self.jobs[0], assessment, {"items": [{"id": "F001", "variant": -1}]})

    def test_html_does_not_execute_profile_text(self):
        self.p["name"] = "<script>alert(1)</script>"
        bundle = tailor(self.p, self.jobs[0], match(self.p, self.jobs[0], self.policy))
        html = render_resume(bundle)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_url_rejects_credentials_and_preserves_job_query(self):
        with self.assertRaises(ValueError):
            canonical_url("https://user:password@example.com/job")
        self.assertNotEqual(validate_job({**self.jobs[0], "url": "https://example.com/?job=1"})["id"], validate_job({**self.jobs[0], "url": "https://example.com/?job=2"})["id"])

    def test_english_tokens_do_not_match_substrings(self):
        self.assertFalse(contains("paid", "AI"))
        self.assertTrue(contains("AI 产品经理", "AI"))

    def test_claim_is_atomic_and_prevents_retries(self):
        with tempfile.TemporaryDirectory() as td:
            s1, s2 = Store(Path(td) / "db.sqlite"), Store(Path(td) / "db.sqlite")
            try:
                j = validate_job(self.jobs[0])
                s1.put_job(j)
                s1.put_job(j)
                self.assertEqual(len(s1.jobs()), 1)
                s1.save_bundle(j["id"], "bundle.json", "hash", "matched")
                s1.claim(j["id"])
                with self.assertRaises(ValueError):
                    s2.claim(j["id"])
                s1.event(j["id"], "uncertain", "网络断开")
                with self.assertRaises(ValueError):
                    s2.claim(j["id"])
                with self.assertRaises(ValueError):
                    s2.save_bundle(j["id"], "new.json", "new", "matched")
            finally:
                s1.close()
                s2.close()


if __name__ == "__main__":
    unittest.main()
