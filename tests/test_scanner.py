"""Tests for scanner.py - Codex JSONL parsing, DB operations, and scanning."""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scanner import (
    aggregate_sessions,
    get_db,
    init_db,
    insert_turns,
    parse_jsonl_file,
    project_name_from_cwd,
    scan,
    session_id_from_path,
    upsert_sessions,
)


def _make_session_meta(session_id="019e780e-93e4-7323-ad38-8ad1e0b672a2",
                       timestamp="2026-05-30T08:44:41.828Z",
                       cwd="/Users/hui/Documents/codex/codex-usage",
                       model_provider="custom"):
    return json.dumps({
        "timestamp": timestamp,
        "type": "session_meta",
        "payload": {
            "id": session_id,
            "timestamp": timestamp,
            "cwd": cwd,
            "originator": "Codex Desktop",
            "cli_version": "0.135.0-alpha.1",
            "source": "vscode",
            "thread_source": "user",
            "model_provider": model_provider,
        },
    })


def _make_token_count(timestamp="2026-05-30T08:45:00.000Z",
                      input_tokens=1200,
                      cached_input_tokens=1000,
                      output_tokens=300,
                      reasoning_output_tokens=200):
    return json.dumps({
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "output_tokens": output_tokens,
                    "reasoning_output_tokens": reasoning_output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
                "total_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "output_tokens": output_tokens,
                    "reasoning_output_tokens": reasoning_output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
                "model_context_window": 258400,
            },
            "rate_limits": {"limit_id": "codex"},
        },
    })


class TestProjectNameFromCwd(unittest.TestCase):
    def test_two_components(self):
        self.assertEqual(project_name_from_cwd("/home/user/myproject"), "user/myproject")

    def test_deep_path(self):
        self.assertEqual(project_name_from_cwd("/a/b/c/d"), "c/d")

    def test_windows_path(self):
        self.assertEqual(project_name_from_cwd("C:\\Users\\me\\project"), "me/project")

    def test_empty_string(self):
        self.assertEqual(project_name_from_cwd(""), "unknown")

    def test_none(self):
        self.assertEqual(project_name_from_cwd(None), "unknown")


class TestSessionIdFromPath(unittest.TestCase):
    def test_extracts_rollout_uuid(self):
        path = "/tmp/rollout-2026-05-30T01-44-41-019e780e-93e4-7323-ad38-8ad1e0b672a2.jsonl"
        self.assertEqual(session_id_from_path(path), "019e780e-93e4-7323-ad38-8ad1e0b672a2")

    def test_falls_back_to_stem(self):
        self.assertEqual(session_id_from_path("/tmp/session.jsonl"), "session")


class TestParseJsonlFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write_jsonl(self, filename, lines):
        path = os.path.join(self.tmpdir, filename)
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        return path

    def test_basic_codex_parsing(self):
        path = self._write_jsonl("rollout-2026-05-30T01-44-41-019e780e-93e4-7323-ad38-8ad1e0b672a2.jsonl", [
            _make_session_meta(),
            _make_token_count(),
        ])
        metas, turns, line_count = parse_jsonl_file(path)

        self.assertEqual(len(metas), 1)
        self.assertEqual(len(turns), 1)
        self.assertEqual(line_count, 2)
        self.assertEqual(metas[0]["project_name"], "codex/codex-usage")
        self.assertEqual(metas[0]["model"], "codex/custom")
        self.assertEqual(turns[0]["input_tokens"], 200)
        self.assertEqual(turns[0]["cache_read_tokens"], 1000)
        self.assertEqual(turns[0]["output_tokens"], 300)
        self.assertEqual(turns[0]["reasoning_tokens"], 200)

    def test_skips_empty_usage_and_malformed_json(self):
        path = self._write_jsonl("test.jsonl", [
            "not valid json",
            _make_session_meta(session_id="sess-1"),
            _make_token_count(input_tokens=0, cached_input_tokens=0,
                              output_tokens=0, reasoning_output_tokens=0),
        ])
        metas, turns, _ = parse_jsonl_file(path)
        self.assertEqual(len(metas), 1)
        self.assertEqual(len(turns), 0)

    def test_uses_path_session_without_meta(self):
        path = self._write_jsonl("rollout-2026-05-30T01-44-41-019e780e-93e4-7323-ad38-8ad1e0b672a2.jsonl", [
            _make_token_count(),
        ])
        metas, turns, _ = parse_jsonl_file(path)
        self.assertEqual(metas[0]["session_id"], "019e780e-93e4-7323-ad38-8ad1e0b672a2")
        self.assertEqual(turns[0]["model"], "codex")


class TestAggregateSessions(unittest.TestCase):
    def test_aggregation(self):
        metas = [{
            "session_id": "s1",
            "project_name": "test",
            "first_timestamp": "2026-05-30T08:00:00Z",
            "last_timestamp": "2026-05-30T08:01:00Z",
            "git_branch": "",
            "model": "codex/custom",
        }]
        turns = [
            {"session_id": "s1", "input_tokens": 100, "output_tokens": 50,
             "cache_read_tokens": 10, "cache_creation_tokens": 0,
             "reasoning_tokens": 5, "model": "codex/custom"},
            {"session_id": "s1", "input_tokens": 200, "output_tokens": 100,
             "cache_read_tokens": 20, "cache_creation_tokens": 0,
             "reasoning_tokens": 10, "model": "codex/custom"},
        ]
        sessions = aggregate_sessions(metas, turns)
        self.assertEqual(sessions[0]["total_input_tokens"], 300)
        self.assertEqual(sessions[0]["total_output_tokens"], 150)
        self.assertEqual(sessions[0]["total_cache_read"], 30)
        self.assertEqual(sessions[0]["total_reasoning_tokens"], 15)
        self.assertEqual(sessions[0]["turn_count"], 2)


class TestDatabaseOperations(unittest.TestCase):
    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmpfile.close()
        self.db_path = Path(self.tmpfile.name)
        self.conn = get_db(self.db_path)
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        os.unlink(self.db_path)

    def test_init_db_creates_codex_columns(self):
        turn_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(turns)")}
        session_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(sessions)")}
        self.assertIn("reasoning_tokens", turn_cols)
        self.assertIn("total_reasoning_tokens", session_cols)

    def test_insert_turns(self):
        turns = [{
            "session_id": "s1", "timestamp": "2026-05-30T08:45:00Z",
            "model": "codex/custom", "input_tokens": 100,
            "output_tokens": 50, "cache_read_tokens": 10,
            "cache_creation_tokens": 0, "reasoning_tokens": 5,
            "tool_name": None, "cwd": "/tmp", "message_id": "m1",
        }]
        insert_turns(self.conn, turns)
        rows = self.conn.execute("SELECT * FROM turns").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reasoning_tokens"], 5)

    def test_upsert_session(self):
        session = {
            "session_id": "s1", "project_name": "test",
            "first_timestamp": "2026-05-30T08:00:00Z",
            "last_timestamp": "2026-05-30T08:10:00Z",
            "git_branch": "", "model": "codex/custom",
            "total_input_tokens": 1000, "total_output_tokens": 500,
            "total_cache_read": 100, "total_cache_creation": 0,
            "total_reasoning_tokens": 250, "turn_count": 5,
        }
        upsert_sessions(self.conn, [session])
        row = self.conn.execute("SELECT * FROM sessions WHERE session_id = 's1'").fetchone()
        self.assertEqual(row["total_reasoning_tokens"], 250)


class TestScanIntegration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sessions_dir = Path(self.tmpdir) / "sessions"
        self.sessions_dir.mkdir()
        self.db_path = Path(self.tmpdir) / "usage.db"
        self.filepath = self.sessions_dir / "rollout-2026-05-30T01-44-41-019e780e-93e4-7323-ad38-8ad1e0b672a2.jsonl"

    def _write_initial(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write(_make_session_meta() + "\n")
            f.write(_make_token_count(timestamp="2026-05-30T08:45:00Z") + "\n")

    def test_scan_new_files(self):
        self._write_initial()
        result = scan(projects_dir=self.sessions_dir, db_path=self.db_path, verbose=False)
        self.assertEqual(result["new"], 1)
        self.assertEqual(result["turns"], 1)
        self.assertEqual(result["sessions"], 1)

    def test_scan_is_incremental(self):
        self._write_initial()
        scan(projects_dir=self.sessions_dir, db_path=self.db_path, verbose=False)
        result = scan(projects_dir=self.sessions_dir, db_path=self.db_path, verbose=False)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["new"], 0)

    def test_appends_only_new_lines(self):
        self._write_initial()
        scan(projects_dir=self.sessions_dir, db_path=self.db_path, verbose=False)

        import time
        time.sleep(0.05)
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(_make_token_count(timestamp="2026-05-30T08:46:00Z",
                                      input_tokens=1300,
                                      cached_input_tokens=1000,
                                      output_tokens=100,
                                      reasoning_output_tokens=50) + "\n")

        result = scan(projects_dir=self.sessions_dir, db_path=self.db_path, verbose=False)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["turns"], 1)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        session = conn.execute("SELECT * FROM sessions").fetchone()
        models = {r["model"] for r in conn.execute("SELECT model FROM turns").fetchall()}
        turn_count = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        conn.close()
        self.assertEqual(turn_count, 2)
        self.assertEqual(session["total_input_tokens"], 500)
        self.assertEqual(session["total_reasoning_tokens"], 250)
        self.assertEqual(models, {"codex/custom"})

    def test_message_id_prevents_duplicate_forced_rescan(self):
        self._write_initial()
        scan(projects_dir=self.sessions_dir, db_path=self.db_path, verbose=False)

        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM processed_files")
        conn.commit()
        conn.close()

        scan(projects_dir=self.sessions_dir, db_path=self.db_path, verbose=False)
        conn = sqlite3.connect(self.db_path)
        count = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
