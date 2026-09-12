import copy
import json
import tempfile
import shutil
import subprocess
import unittest
from pathlib import Path

from jobpilot.assistant import create_cycle, expression_coverage, load_cycle, market_insights, revise_profile, search_plan, validated_ai_suggestions
from jobpilot.core import digest, match, read_json, validate_job
from jobpilot.store import Store

ROOT = Path(__file__).resolve().parents[1]


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.store = Store(self.directory / "db.sqlite")
        self.profile = read_json(ROOT / "examples/profile.json")
        self.policy = read_json(ROOT / "examples/policy.json")
        self.jobs = [validate_job(j) for j in read_json(ROOT / "examples/jobs.json")]
        for j in self.jobs:
            self.store.put_job(j)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def cycle(self, profile=None, parent=None, policy=None):
        return create_cycle(self.store, profile or self.profile, policy or self.policy, self.directory / "reports", parent_id=parent)

    def decision(self, result):
        report = load_cycle(self.store, result["cycle_id"])
        suggestion = next(s for s in report["suggestions"] if s["kind"] == "rewrite")
        return {"cycle_id": report["id"], "profile_hash": digest(self.profile), "decisions": [{"suggestion_id": suggestion["id"], "action": "accept", "confirmed": True}]}

    def test_complete_loop_improves_expression_not_capability(self):
        original = copy.deepcopy(self.profile)
        first = self.cycle()
        revised = revise_profile(self.store, first["cycle_id"], self.profile, self.decision(first), self.directory / "profile-v2.json")
        updated = read_json(revised["profile"])
        second = self.cycle(updated, first["cycle_id"])
        comparison = load_cycle(self.store, second["cycle_id"])["comparison"]["comparable_jobs"]
        target = next(c for c in comparison if c["job_id"] == self.jobs[0]["id"])
        self.assertEqual(target["capability_before"], target["capability_after"])
        self.assertEqual(target["expression_before"], 75)
        self.assertEqual(target["expression_after"], 100)
        self.assertEqual(self.profile, original)
        self.assertEqual(self.store.applications(), [])  # Analysis never queues applications.
        self.assertEqual(updated["facts"][0]["keywords"], self.profile["facts"][0]["keywords"])
        self.assertEqual(updated["facts"][0]["stage"], "prototype")

    def test_stale_profile_cannot_receive_old_suggestions(self):
        first = self.cycle()
        decision = self.decision(first)
        self.profile["headline"] += "（更新）"
        with self.assertRaisesRegex(ValueError, "已变更"):
            revise_profile(self.store, first["cycle_id"], self.profile, decision, self.directory / "v2.json")
        self.assertFalse((self.directory / "v2.json").exists())

    def test_confirmation_is_required_for_real_claim_changes(self):
        first = self.cycle()
        decision = self.decision(first)
        decision["decisions"][0]["confirmed"] = False
        with self.assertRaisesRegex(ValueError, "确认"):
            revise_profile(self.store, first["cycle_id"], self.profile, decision, self.directory / "v2.json")

    def test_gap_cannot_be_converted_into_experience(self):
        first = self.cycle()
        r = load_cycle(self.store, first["cycle_id"])
        gap = next(s for s in r["suggestions"] if s["kind"] == "gap")
        decision = {"cycle_id": r["id"], "profile_hash": digest(self.profile), "decisions": [{"suggestion_id": gap["id"], "action": "accept", "confirmed": True, "text": "精通 CUDA"}]}
        with self.assertRaisesRegex(ValueError, "能力缺口"):
            revise_profile(self.store, first["cycle_id"], self.profile, decision, self.directory / "v2.json")

    def test_duplicate_apply_and_overwriting_original_are_blocked(self):
        first = self.cycle()
        decision = self.decision(first)
        output = self.directory / "v2.json"
        output.write_text("original")
        with self.assertRaises(FileExistsError):
            revise_profile(self.store, first["cycle_id"], self.profile, decision, output)
        self.assertEqual(output.read_text(), "original")
        output.unlink()
        revise_profile(self.store, first["cycle_id"], self.profile, decision, output)
        with self.assertRaisesRegex(ValueError, "本轮已处理"):
            revise_profile(self.store, first["cycle_id"], self.profile, decision, self.directory / "v3.json")

    def test_changed_policy_is_not_counted_as_resume_improvement(self):
        first = self.cycle()
        policy = {**self.policy, "min_monthly_salary": 30000}
        second = self.cycle(parent=first["cycle_id"], policy=policy)
        comparison = load_cycle(self.store, second["cycle_id"])["comparison"]
        self.assertFalse(comparison["same_policy"])
        self.assertEqual(comparison["comparable_jobs"], [])

    def test_changed_jd_is_not_directly_comparable(self):
        first = self.cycle()
        self.store.put_job({**self.jobs[0], "description": "岗位描述已经修改"})
        second = self.cycle(parent=first["cycle_id"])
        comparison = load_cycle(self.store, second["cycle_id"])["comparison"]
        self.assertIn(self.jobs[0]["id"], comparison["changed_job_or_policy"])

    def test_no_requirements_inference_does_not_auto_pass(self):
        self.store.put_job({**self.jobs[0], "requirements": []})
        first = self.cycle()
        row = next(r for r in load_cycle(self.store, first["cycle_id"])["jobs"] if r["job"]["id"] == self.jobs[0]["id"])
        self.assertEqual(row["requirements_origin"], "inferred_partial")
        self.assertEqual(row["assessment"]["status"], "needs_review")

    def test_multi_city_search_has_evidence_and_no_contact(self):
        plan = search_plan(self.profile, {**self.policy, "cities": ["上海", "深圳"]})
        self.assertEqual({q["city"] for q in plan["queries"]}, {"上海", "深圳"})
        self.assertTrue(all(q["evidence_ids"] for q in plan["queries"]))
        self.assertNotIn(self.profile["contact"], json.dumps(plan))

    def test_search_plan_models_boss_and_liepin_different_actions(self):
        plan = search_plan(self.profile, {**self.policy, "platforms": ["boss", "liepin"], "cities": ["上海"], "districts": ["浦东新区"]})
        self.assertEqual({q["platform"] for q in plan["queries"]}, {"boss", "liepin"})
        boss = next(q for q in plan["queries"] if q["platform"] == "boss")
        liepin = next(q for q in plan["queries"] if q["platform"] == "liepin")
        self.assertEqual(boss["interaction_model"], "direct_chat")
        self.assertEqual(liepin["interaction_model"], "application_and_chat")
        self.assertIn("区", next(x for x in boss["filters"] if x["field"] == "districts")["label"])

    def test_market_frequency_deduplicates_cross_platform_copy(self):
        base = {**self.jobs[0], "title": "AI产品经理", "company": "同一公司", "city": "上海", "requirements": ["RAG"]}
        jobs = [
            validate_job({**base, "url": "https://www.zhipin.com/job_detail/a.html", "source_platform": "boss"}),
            validate_job({**base, "url": "https://www.liepin.com/job/a.shtml", "source_platform": "liepin"}),
        ]
        rows = []
        for job in jobs:
            assessment = match(self.profile, job, self.policy)
            rows.append({"job": job, "assessment": assessment, "expression": expression_coverage(self.profile, assessment)})
        market = market_insights(rows, min_jobs=2)
        self.assertEqual(market["candidate_jobs"], 2)
        self.assertEqual(market["distinct_job_clusters"], 1)
        self.assertEqual(market["requirements"][0]["cluster_count"], 1)
        self.assertFalse(market["requirements"][0]["recurring"])
        self.assertEqual(len(market["duplicate_groups"]), 1)

    def test_ai_cannot_invent_source_quote_or_metrics(self):
        raw = {"job_id": self.jobs[0]["id"], "fact_id": "F001", "after": "负责需求分析，效率提升80%", "reason": "强调成果", "requirement_quote": "负责企业知识库的需求分析"}
        with self.assertRaisesRegex(ValueError, "数字"):
            validated_ai_suggestions(self.profile, self.jobs, {"suggestions": [raw]})
        raw["after"] = "围绕 RAG 应用，负责需求分析与验收用例整理"
        raw["requirement_quote"] = "岗位里不存在的句子"
        with self.assertRaisesRegex(ValueError, "原句"):
            validated_ai_suggestions(self.profile, self.jobs, {"suggestions": [raw]})

    def test_ai_draft_with_evidence_remains_a_draft(self):
        raw = {"job_id": self.jobs[0]["id"], "fact_id": "F001", "after": "围绕 RAG 应用，负责原型需求分析与验收用例整理", "reason": "突出相关职责", "requirement_quote": "负责企业知识库的需求分析"}
        result = validated_ai_suggestions(self.profile, self.jobs, {"suggestions": [raw]})
        self.assertEqual(result[0]["source"], "ai_draft")
        self.assertNotEqual(self.profile["facts"][0]["text"], result[0]["after"])

    def test_html_escapes_profile_and_has_preferences_controls(self):
        self.profile["name"] = '</script><img src=x onerror="alert(1)">'
        first = self.cycle()
        html = Path(first["report"]).read_text()
        self.assertNotIn('<img src=x', html)
        self.assertIn('id="download-policy"', html)
        self.assertIn('id="download"', html)

    @unittest.skipUnless(shutil.which("node"), "Node is optional; needed for exported-page handler test")
    def test_review_page_decision_and_settings_handlers(self):
        result = self.cycle()
        process = subprocess.run(["node", str(ROOT / "tests/review_page.test.cjs"), result["report"]], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)


if __name__ == "__main__":
    unittest.main()
