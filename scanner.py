"""
scanner.py - Scans Codex JSONL transcript files and stores usage in SQLite.
"""

import glob
import json
import os
import re
import sqlite3
from pathlib import Path
from collections import Counter, defaultdict

SESSIONS_DIR = Path.home() / ".codex" / "sessions"
PROJECTS_DIR = SESSIONS_DIR
DB_PATH = Path.home() / ".codex" / "usage.db"
DEFAULT_PROJECTS_DIRS = [SESSIONS_DIR]

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def get_db(db_path=DB_PATH):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id      TEXT PRIMARY KEY,
            project_name    TEXT,
            first_timestamp TEXT,
            last_timestamp  TEXT,
            git_branch      TEXT,
            total_input_tokens      INTEGER DEFAULT 0,
            total_output_tokens     INTEGER DEFAULT 0,
            total_cache_read        INTEGER DEFAULT 0,
            total_cache_creation    INTEGER DEFAULT 0,
            total_reasoning_tokens  INTEGER DEFAULT 0,
            model           TEXT,
            turn_count      INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS turns (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id              TEXT,
            timestamp               TEXT,
            model                   TEXT,
            input_tokens            INTEGER DEFAULT 0,
            output_tokens           INTEGER DEFAULT 0,
            cache_read_tokens       INTEGER DEFAULT 0,
            cache_creation_tokens   INTEGER DEFAULT 0,
            reasoning_tokens        INTEGER DEFAULT 0,
            tool_name               TEXT,
            cwd                     TEXT,
            message_id              TEXT
        );

        CREATE TABLE IF NOT EXISTS processed_files (
            path    TEXT PRIMARY KEY,
            mtime   REAL,
            lines   INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
        CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON turns(timestamp);
        CREATE INDEX IF NOT EXISTS idx_sessions_first ON sessions(first_timestamp);
    """)
    _ensure_column(conn, "turns", "message_id", "TEXT")
    _ensure_column(conn, "turns", "reasoning_tokens", "INTEGER DEFAULT 0")
    _ensure_column(conn, "sessions", "total_reasoning_tokens", "INTEGER DEFAULT 0")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_turns_message_id
        ON turns(message_id) WHERE message_id IS NOT NULL AND message_id != ''
    """)
    conn.commit()


def _ensure_column(conn, table, column, definition):
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def project_name_from_cwd(cwd):
    """Derive a friendly project name from a cwd path."""
    if not cwd:
        return "unknown"
    parts = cwd.replace("\\", "/").rstrip("/").split("/")
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return parts[-1] if parts else "unknown"


def session_id_from_path(filepath):
    """Extract the Codex rollout UUID from a transcript filename."""
    match = UUID_RE.search(Path(filepath).stem)
    return match.group(0) if match else Path(filepath).stem


def model_from_meta(meta):
    """Codex transcripts currently expose provider, not exact model name."""
    provider = (meta or {}).get("model_provider")
    return f"codex/{provider}" if provider else "codex"


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _new_session_meta(session_id, timestamp="", cwd="", model="codex"):
    return {
        "session_id": session_id,
        "project_name": project_name_from_cwd(cwd),
        "first_timestamp": timestamp,
        "last_timestamp": timestamp,
        "git_branch": "",
        "model": model,
    }


def _touch_session_meta(session_meta, session_id, timestamp="", cwd="", model="codex"):
    meta = session_meta.setdefault(
        session_id,
        _new_session_meta(session_id, timestamp=timestamp, cwd=cwd, model=model),
    )
    if cwd and meta["project_name"] == "unknown":
        meta["project_name"] = project_name_from_cwd(cwd)
    if model and (not meta["model"] or meta["model"] == "codex"):
        meta["model"] = model
    if timestamp and (not meta["first_timestamp"] or timestamp < meta["first_timestamp"]):
        meta["first_timestamp"] = timestamp
    if timestamp and (not meta["last_timestamp"] or timestamp > meta["last_timestamp"]):
        meta["last_timestamp"] = timestamp
    return meta


def parse_jsonl_file(filepath, start_line=0):
    """Parse a Codex JSONL transcript.

    Codex writes usage as event_msg records whose payload type is
    "token_count". The per-call totals are in info.last_token_usage.
    input_tokens includes cached input, so cached_input_tokens is split out
    into cache_read_tokens to match the dashboard's existing token buckets.
    """
    session_id = session_id_from_path(filepath)
    current_cwd = ""
    current_model = "codex"
    session_meta = {}
    turns = []
    line_count = 0

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line_count, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                rtype = record.get("type")
                timestamp = record.get("timestamp", "")

                if rtype == "session_meta":
                    payload = record.get("payload") or {}
                    session_id = payload.get("id") or session_id
                    current_cwd = payload.get("cwd") or current_cwd
                    current_model = model_from_meta(payload)
                    _touch_session_meta(
                        session_meta,
                        session_id,
                        timestamp=payload.get("timestamp") or timestamp,
                        cwd=current_cwd,
                        model=current_model,
                    )
                    continue

                if line_count <= start_line:
                    continue

                if rtype != "event_msg":
                    continue

                payload = record.get("payload") or {}
                if payload.get("type") != "token_count":
                    continue

                info = payload.get("info") or {}
                usage = info.get("last_token_usage") or {}
                if not usage:
                    continue

                total_input = _int(usage.get("input_tokens"))
                cached_input = _int(usage.get("cached_input_tokens"))
                input_tokens = max(total_input - cached_input, 0)
                output_tokens = _int(usage.get("output_tokens"))
                reasoning_tokens = _int(usage.get("reasoning_output_tokens"))

                if input_tokens + output_tokens + cached_input + reasoning_tokens == 0:
                    continue

                _touch_session_meta(
                    session_meta,
                    session_id,
                    timestamp=timestamp,
                    cwd=current_cwd,
                    model=current_model,
                )

                turns.append({
                    "session_id": session_id,
                    "timestamp": timestamp,
                    "model": current_model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_tokens": cached_input,
                    "cache_creation_tokens": 0,
                    "reasoning_tokens": reasoning_tokens,
                    "tool_name": None,
                    "cwd": current_cwd,
                    "message_id": f"{Path(filepath).resolve()}:{line_count}",
                })
    except Exception as e:
        print(f"  Warning: error reading {filepath}: {e}")

    return list(session_meta.values()), turns, line_count


def aggregate_sessions(session_metas, turns):
    """Aggregate turn data back into session-level stats."""
    session_stats = defaultdict(lambda: {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_read": 0,
        "total_cache_creation": 0,
        "total_reasoning_tokens": 0,
        "turn_count": 0,
        "model": None,
    })
    session_model_counts = defaultdict(Counter)

    for t in turns:
        s = session_stats[t["session_id"]]
        s["total_input_tokens"] += t["input_tokens"]
        s["total_output_tokens"] += t["output_tokens"]
        s["total_cache_read"] += t["cache_read_tokens"]
        s["total_cache_creation"] += t.get("cache_creation_tokens", 0)
        s["total_reasoning_tokens"] += t.get("reasoning_tokens", 0)
        s["turn_count"] += 1
        if t.get("model"):
            session_model_counts[t["session_id"]][t["model"]] += 1

    for sid, counts in session_model_counts.items():
        if counts:
            session_stats[sid]["model"] = counts.most_common(1)[0][0]

    result = []
    for meta in session_metas:
        sid = meta["session_id"]
        stats = session_stats[sid]
        result.append({**meta, **stats, "model": stats["model"] or meta.get("model")})
    return result


def upsert_sessions(conn, sessions):
    for s in sessions:
        existing = conn.execute(
            "SELECT model FROM sessions WHERE session_id = ?",
            (s["session_id"],),
        ).fetchone()

        if existing is None:
            conn.execute("""
                INSERT INTO sessions
                    (session_id, project_name, first_timestamp, last_timestamp,
                     git_branch, total_input_tokens, total_output_tokens,
                     total_cache_read, total_cache_creation,
                     total_reasoning_tokens, model, turn_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                s["session_id"], s["project_name"], s["first_timestamp"],
                s["last_timestamp"], s["git_branch"],
                s["total_input_tokens"], s["total_output_tokens"],
                s["total_cache_read"], s["total_cache_creation"],
                s.get("total_reasoning_tokens", 0),
                s["model"], s["turn_count"],
            ))
        else:
            model_to_set = s["model"] or existing["model"]
            conn.execute("""
                UPDATE sessions SET
                    last_timestamp = MAX(last_timestamp, ?),
                    total_input_tokens = total_input_tokens + ?,
                    total_output_tokens = total_output_tokens + ?,
                    total_cache_read = total_cache_read + ?,
                    total_cache_creation = total_cache_creation + ?,
                    total_reasoning_tokens = total_reasoning_tokens + ?,
                    turn_count = turn_count + ?,
                    model = ?
                WHERE session_id = ?
            """, (
                s["last_timestamp"],
                s["total_input_tokens"], s["total_output_tokens"],
                s["total_cache_read"], s["total_cache_creation"],
                s.get("total_reasoning_tokens", 0),
                s["turn_count"], model_to_set,
                s["session_id"],
            ))


def insert_turns(conn, turns):
    conn.executemany("""
        INSERT OR IGNORE INTO turns
            (session_id, timestamp, model, input_tokens, output_tokens,
             cache_read_tokens, cache_creation_tokens, reasoning_tokens,
             tool_name, cwd, message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        (
            t["session_id"], t["timestamp"], t.get("model"),
            t.get("input_tokens", 0), t.get("output_tokens", 0),
            t.get("cache_read_tokens", 0), t.get("cache_creation_tokens", 0),
            t.get("reasoning_tokens", 0), t.get("tool_name"), t.get("cwd"),
            t.get("message_id", ""),
        )
        for t in turns
    ])


def scan(projects_dir=None, projects_dirs=None, db_path=DB_PATH, verbose=True):
    conn = get_db(db_path)
    init_db(conn)

    if projects_dirs:
        dirs_to_scan = [Path(d) for d in projects_dirs]
    elif projects_dir:
        dirs_to_scan = [Path(projects_dir)]
    else:
        dirs_to_scan = DEFAULT_PROJECTS_DIRS

    jsonl_files = []
    for d in dirs_to_scan:
        if not d.exists():
            continue
        if verbose:
            print(f"Scanning {d} ...")
        jsonl_files.extend(glob.glob(str(d / "**" / "*.jsonl"), recursive=True))
    jsonl_files.sort()

    new_files = 0
    updated_files = 0
    skipped_files = 0
    total_turns = 0
    total_sessions = set()

    for filepath in jsonl_files:
        try:
            mtime = os.path.getmtime(filepath)
        except OSError:
            continue

        row = conn.execute(
            "SELECT mtime, lines FROM processed_files WHERE path = ?",
            (filepath,),
        ).fetchone()

        if row and abs(row["mtime"] - mtime) < 0.01:
            skipped_files += 1
            continue

        is_new = row is None
        if verbose:
            status = "NEW" if is_new else "UPD"
            print(f"  [{status}] {filepath}")

        old_lines = 0 if is_new else row["lines"]
        session_metas, turns, line_count = parse_jsonl_file(filepath, start_line=old_lines)

        if not is_new and line_count <= old_lines:
            conn.execute("UPDATE processed_files SET mtime = ? WHERE path = ?", (mtime, filepath))
            conn.commit()
            skipped_files += 1
            continue

        if turns or session_metas:
            sessions = aggregate_sessions(session_metas, turns)
            upsert_sessions(conn, sessions)
            insert_turns(conn, turns)
            for s in sessions:
                total_sessions.add(s["session_id"])
            total_turns += len(turns)

        if is_new:
            new_files += 1
        else:
            updated_files += 1

        conn.execute("""
            INSERT OR REPLACE INTO processed_files (path, mtime, lines)
            VALUES (?, ?, ?)
        """, (filepath, mtime, line_count))
        conn.commit()

    if new_files or updated_files:
        conn.execute("""
            UPDATE sessions SET
                total_input_tokens = COALESCE((SELECT SUM(input_tokens) FROM turns WHERE turns.session_id = sessions.session_id), 0),
                total_output_tokens = COALESCE((SELECT SUM(output_tokens) FROM turns WHERE turns.session_id = sessions.session_id), 0),
                total_cache_read = COALESCE((SELECT SUM(cache_read_tokens) FROM turns WHERE turns.session_id = sessions.session_id), 0),
                total_cache_creation = COALESCE((SELECT SUM(cache_creation_tokens) FROM turns WHERE turns.session_id = sessions.session_id), 0),
                total_reasoning_tokens = COALESCE((SELECT SUM(reasoning_tokens) FROM turns WHERE turns.session_id = sessions.session_id), 0),
                turn_count = COALESCE((SELECT COUNT(*) FROM turns WHERE turns.session_id = sessions.session_id), 0)
        """)
        conn.commit()

    if verbose:
        print("\nScan complete:")
        print(f"  New files:     {new_files}")
        print(f"  Updated files: {updated_files}")
        print(f"  Skipped files: {skipped_files}")
        print(f"  Turns added:   {total_turns}")
        print(f"  Sessions seen: {len(total_sessions)}")

    conn.close()
    return {
        "new": new_files,
        "updated": updated_files,
        "skipped": skipped_files,
        "turns": total_turns,
        "sessions": len(total_sessions),
    }


if __name__ == "__main__":
    import sys

    projects_dir = None
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--projects-dir" and i + 1 < len(sys.argv[1:]):
            projects_dir = Path(sys.argv[i + 2])
            break
    scan(projects_dir=projects_dir)
