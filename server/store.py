"""One SQLite transaction saves the domain snapshot and its audit/quantity ledger."""
import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS checkpoint (
            id INTEGER PRIMARY KEY CHECK(id=1), state_json TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS audit (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
            at REAL NOT NULL, kind TEXT NOT NULL, session_id TEXT,
            task_id TEXT, command_id TEXT, mode TEXT NOT NULL, detail_json TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS movements (
            run_id TEXT NOT NULL, command_id TEXT NOT NULL, slot INTEGER NOT NULL,
            session_id TEXT NOT NULL, sku TEXT NOT NULL, direction TEXT NOT NULL,
            at REAL NOT NULL, mode TEXT NOT NULL,
            PRIMARY KEY(run_id, command_id, slot));
          CREATE TABLE IF NOT EXISTS archived_runs (
            run_id TEXT PRIMARY KEY, state_json TEXT NOT NULL);
        """)

    def load(self):
        row = self.db.execute("SELECT state_json FROM checkpoint WHERE id=1").fetchone()
        return json.loads(row[0]) if row else None

    def save(self, state, records):
        with self.db:
            for record in records:
                self.db.execute(
                    "INSERT INTO audit(run_id,at,kind,session_id,task_id,command_id,mode,detail_json) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (state["run_id"], record["at"], record["kind"], record.get("session_id"),
                     record.get("task_id"), record.get("command_id"), "mock",
                     json.dumps(record["detail"], ensure_ascii=False)),
                )
                if record["kind"] == "item_confirmed":
                    item = record["detail"]
                    self.db.execute(
                        "INSERT INTO movements VALUES(?,?,?,?,?,?,?,?)",
                        (state["run_id"], record["command_id"], item["slot"], record["session_id"],
                         item["sku"], item["direction"], record["at"], "mock"),
                    )
            self.db.execute("INSERT OR REPLACE INTO checkpoint VALUES(1,?)",
                            (json.dumps(state, ensure_ascii=False),))

    def archive(self, state):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO archived_runs VALUES(?,?)",
                            (state["run_id"], json.dumps(state, ensure_ascii=False)))

    def logs(self, run_id, limit=200):
        rows = self.db.execute("SELECT * FROM audit WHERE run_id=? ORDER BY seq DESC LIMIT ?",
                               (run_id, limit)).fetchall()
        return [{**dict(r), "detail": json.loads(r["detail_json"])} for r in rows]

    def close(self):
        self.db.close()
