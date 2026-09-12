"""Runner contract tests with fake locators. These do NOT assert real-site compatibility."""
import copy
import tempfile
import unittest
from pathlib import Path

from jobpilot.browser import run_one, guard_url, validate_adapter
from jobpilot.core import digest, match, read_json, tailor, validate_job
from jobpilot.store import Store

ROOT = Path(__file__).resolve().parents[1]


class Locator:
    def __init__(self, page, name):
        self.page, self.name = page, name
    @property
    def first(self):
        return self
    def count(self):
        return 0 if self.name in ("#captcha", "#rate-limit") else 1
    def wait_for(self, **kwargs):
        pass
    def is_visible(self):
        return bool(self.inner_text())
    def inner_text(self):
        return self.page.text.get(self.name, "")
    def fill(self, text):
        self.page.actions.append(("fill", text))
    def click(self):
        self.page.actions.append(("click", self.name))
        if self.page.fail:
            raise RuntimeError("click result unknown")
        self.page.text["#receipt"] = "申请已提交"
    def set_input_files(self, path):
        self.page.actions.append(("upload", path))


class Page:
    def __init__(self):
        self.text = {"#company": "示例招聘公司", "#job-title": "AI产品经理"}
        self.url = "https://example.invalid/jobs/001"
        self.actions = []
        self.fail = False
    def goto(self, url, **kwargs):
        self.url = url
    def locator(self, css):
        return Locator(self, css)
    def get_by_label(self, label, **kwargs):
        return Locator(self, label)
    def get_by_role(self, role, name, **kwargs):
        return Locator(self, name)
    def wait_for_timeout(self, ms):
        pass


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Store(Path(self.tmp.name) / "db.sqlite")
        p = read_json(ROOT / "examples/profile.json")
        j = validate_job(read_json(ROOT / "examples/jobs.json")[0])
        self.b = tailor(p, j, match(p, j, read_json(ROOT / "examples/policy.json")))
        self.s.save_bundle(j["id"], "bundle.json", digest(self.b), "matched")
        self.c = read_json(ROOT / "adapters/example-ats.json")
        self.c["verified"] = True  # fixture verified only in this fake page
        self.c["steps"] = [s for s in self.c["steps"] if s["op"] != "upload"]
        self.page = Page()
    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()
    def test_preview_never_fills_or_clicks(self):
        result = run_one(self.page, self.c, self.b, self.tmp.name, self.s)
        self.assertEqual(result["status"], "preview")
        self.assertEqual(self.page.actions, [])
        self.assertEqual(self.s.application(self.b["job"]["id"])["status"], "matched")
    def test_wrong_company_stops_before_side_effect(self):
        self.page.text["#company"] = "错误公司"
        with self.assertRaises(ValueError):
            run_one(self.page, self.c, self.b, self.tmp.name, self.s, True)
        self.assertEqual(self.page.actions, [])
    def test_unverified_adapter_cannot_send(self):
        self.c["verified"] = False
        with self.assertRaises(ValueError):
            run_one(self.page, self.c, self.b, self.tmp.name, self.s, True)
    def test_wrong_platform_adapter_stops_before_navigation(self):
        self.c["platform"] = "liepin"
        self.b["job"]["source_platform"] = "boss"
        with self.assertRaisesRegex(ValueError, "来源"):
            run_one(self.page, self.c, self.b, self.tmp.name, self.s)
        self.assertEqual(self.page.actions, [])
    def test_confirmed_receipt_changes_state(self):
        result = run_one(self.page, self.c, self.b, self.tmp.name, self.s, True)
        self.assertEqual(result["status"], "submitted")
        with self.assertRaises(ValueError):
            run_one(self.page, self.c, self.b, self.tmp.name, self.s, True)
        self.assertEqual(len(self.page.actions), 2)
    def test_unknown_click_result_is_not_retried(self):
        self.page.fail = True
        with self.assertRaises(RuntimeError):
            run_one(self.page, self.c, self.b, self.tmp.name, self.s, True)
        self.assertEqual(self.s.application(self.b["job"]["id"])["status"], "uncertain")
        with self.assertRaises(ValueError):
            run_one(self.page, self.c, self.b, self.tmp.name, self.s, True)
        self.assertEqual(len(self.page.actions), 2)
    def test_old_receipt_does_not_count_as_new_application(self):
        self.page.text["#receipt"] = "申请已提交"
        with self.assertRaises(ValueError):
            run_one(self.page, self.c, self.b, self.tmp.name, self.s, True)
        self.assertEqual(self.page.actions, [])
    def test_redirect_to_unlisted_host_stops(self):
        with self.assertRaises(ValueError):
            guard_url("https://example.invalid.evil.test/jobs/001", self.c)
    def test_missing_attachment_never_reports_success(self):
        self.c["steps"].insert(1, {"op": "upload", "source": "resume.docx", "locator": {"css": "input[type=file]"}})
        with self.assertRaises(ValueError):
            run_one(self.page, self.c, self.b, self.tmp.name, self.s, True)
        self.assertNotEqual(self.s.application(self.b["job"]["id"])["status"], "submitted")
        self.assertEqual(self.page.actions, [])


if __name__ == "__main__":
    unittest.main()
