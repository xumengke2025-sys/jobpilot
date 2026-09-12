"""Run a two-cycle demonstration using fictional data; never opens BOSS or sends messages."""
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jobpilot.assistant import create_cycle, load_cycle, revise_profile
from jobpilot.core import digest, read_json, validate_job
from jobpilot.store import Store


def main():
    output = ROOT / "output" / ("demo-loop-" + uuid.uuid4().hex[:8])
    store = Store(output / "demo.sqlite")
    try:
        profile, policy = read_json(ROOT / "examples/profile.json"), read_json(ROOT / "examples/policy.json")
        for job in read_json(ROOT / "examples/jobs.json"):
            store.put_job(validate_job(job))
        first = create_cycle(store, profile, policy, output / "cycles")
        report = load_cycle(store, first["cycle_id"])
        suggestion = next(s for s in report["suggestions"] if s["kind"] == "rewrite" and s["source"] == "approved_variant")
        # This scripted confirmation is for the bundled fictional example only.
        decisions = {"cycle_id": first["cycle_id"], "profile_hash": digest(profile), "decisions": [{"suggestion_id": suggestion["id"], "action": "accept", "confirmed": True}]}
        revision = revise_profile(store, first["cycle_id"], profile, decisions, output / "profile-v2.json")
        second = create_cycle(store, read_json(revision["profile"]), policy, output / "cycles", parent_id=first["cycle_id"])
        print(json.dumps({"demo_only": True, "first": first, "second": second, "comparison": load_cycle(store, second["cycle_id"])["comparison"]}, ensure_ascii=False, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
