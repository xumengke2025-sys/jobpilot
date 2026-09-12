"""SQLite ledger with atomic claims. An uncertain send is never auto-retried."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS applications(job_id TEXT PRIMARY KEY, status TEXT NOT NULL,
            bundle_path TEXT NOT NULL, bundle_hash TEXT NOT NULL, updated_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT,
            status TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
        """)

    def put_job(self, job):
        with self.db:
            self.db.execute("INSERT INTO jobs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (job["id"], json.dumps(job, ensure_ascii=False)))

    def jobs(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM jobs ORDER BY rowid")]

    def application(self, jid):
        row = self.db.execute("SELECT * FROM applications WHERE job_id=?", (jid,)).fetchone()
        return dict(row) if row else None

    def save_bundle(self, jid, path, sha, status):
        with self.db:
            old = self.application(jid)
            if old and old["status"] not in ("matched", "needs_review", "rejected"):
                raise ValueError("该岗位已有投递过程，不能覆盖已绑定的简历")
            self.db.execute("INSERT INTO applications VALUES (?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET status=excluded.status,bundle_path=excluded.bundle_path,bundle_hash=excluded.bundle_hash,updated_at=excluded.updated_at", (jid, status, str(path), sha, now()))

    def claim(self, jid):
        with self.db:
            cur = self.db.execute("UPDATE applications SET status='running',updated_at=? WHERE job_id=? AND status='matched'", (now(), jid))
            if cur.rowcount != 1:
                raise ValueError("岗位不在可执行状态（或已被其他进程领取）")
            self.db.execute("INSERT INTO events(job_id,status,detail,created_at) VALUES (?,?,?,?)", (jid, "running", "领取投递任务", now()))

    def event(self, jid, status, detail):
        with self.db:
            self.db.execute("UPDATE applications SET status=?,updated_at=? WHERE job_id=?", (status, now(), jid))
            self.db.execute("INSERT INTO events(job_id,status,detail,created_at) VALUES (?,?,?,?)", (jid, status, detail, now()))

    def applications(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM applications ORDER BY updated_at DESC")]

    def close(self):
        self.db.close()
