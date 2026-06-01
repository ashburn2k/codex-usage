"""
ha_export.py - Export a compact Codex usage summary for Home Assistant.
"""

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import dashboard
import scanner


def _int(value):
    return int(value or 0)


def _range_bounds(days):
    if days is None:
        return None, None
    end = date.today()
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _day_in_range(day, start, end):
    if not day:
        return False
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


def _empty_totals(label):
    return {
        "label": label,
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_creation": 0,
        "reasoning": 0,
        "turns": 0,
        "sessions": 0,
        "projects": 0,
        "total_tokens": 0,
    }


def _finalize_totals(totals):
    totals["total_tokens"] = (
        totals["input"]
        + totals["output"]
        + totals["cache_read"]
        + totals["cache_creation"]
        + totals["reasoning"]
    )
    return totals


def _token_total(row):
    return (
        _int(row.get("input"))
        + _int(row.get("output"))
        + _int(row.get("cache_read"))
        + _int(row.get("cache_creation"))
        + _int(row.get("reasoning"))
    )


def daily_rows_for_range(data, days=30):
    start, end = _range_bounds(days)
    rows = []
    for row in data.get("daily_by_model", []):
        if not _day_in_range(row.get("day"), start, end):
            continue
        item = {
            "day": row.get("day"),
            "model": row.get("model") or "unknown",
            "input": _int(row.get("input")),
            "output": _int(row.get("output")),
            "cache_read": _int(row.get("cache_read")),
            "cache_creation": _int(row.get("cache_creation")),
            "reasoning": _int(row.get("reasoning")),
            "turns": _int(row.get("turns")),
        }
        item["total_tokens"] = _token_total(item)
        rows.append(item)
    return rows


def daily_totals(data, days=30):
    days_by_key = {}
    for row in daily_rows_for_range(data, days):
        item = days_by_key.setdefault(
            row["day"],
            {
                "day": row["day"],
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_creation": 0,
                "reasoning": 0,
                "turns": 0,
                "total_tokens": 0,
            },
        )
        item["input"] += row["input"]
        item["output"] += row["output"]
        item["cache_read"] += row["cache_read"]
        item["cache_creation"] += row["cache_creation"]
        item["reasoning"] += row["reasoning"]
        item["turns"] += row["turns"]
        item["total_tokens"] += row["total_tokens"]
    return [days_by_key[day] for day in sorted(days_by_key)]


def hourly_totals(data, days=30):
    start, end = _range_bounds(days)
    buckets = {
        hour: {"hour": hour, "turns": 0, "output": 0, "days": set()}
        for hour in range(24)
    }

    for row in data.get("hourly_by_model", []):
        day = row.get("day")
        if not _day_in_range(day, start, end):
            continue
        hour = _int(row.get("hour"))
        if hour < 0 or hour > 23:
            continue
        buckets[hour]["turns"] += _int(row.get("turns"))
        buckets[hour]["output"] += _int(row.get("output"))
        if day:
            buckets[hour]["days"].add(day)

    all_days = {
        row.get("day")
        for row in data.get("hourly_by_model", [])
        if _day_in_range(row.get("day"), start, end)
    }
    day_count = max(len(all_days), 1)
    rows = []
    for hour in range(24):
        bucket = buckets[hour]
        rows.append(
            {
                "hour": hour,
                "turns": bucket["turns"],
                "output": bucket["output"],
                "avg_turns": bucket["turns"] / day_count,
                "avg_output": bucket["output"] / day_count,
            }
        )
    return {"day_count": len(all_days), "hours": rows}


def totals_for_range(data, label, days=None):
    start, end = _range_bounds(days)
    totals = _empty_totals(label)

    for row in data.get("daily_by_model", []):
        if not _day_in_range(row.get("day"), start, end):
            continue
        totals["input"] += _int(row.get("input"))
        totals["output"] += _int(row.get("output"))
        totals["cache_read"] += _int(row.get("cache_read"))
        totals["cache_creation"] += _int(row.get("cache_creation"))
        totals["reasoning"] += _int(row.get("reasoning"))
        totals["turns"] += _int(row.get("turns"))

    sessions = [
        row
        for row in data.get("sessions_all", [])
        if _day_in_range(row.get("last_date"), start, end)
    ]
    totals["sessions"] = len(sessions)
    totals["projects"] = len({row.get("project") or "unknown" for row in sessions})
    return _finalize_totals(totals)


def top_projects(data, days=30, limit=8):
    start, end = _range_bounds(days)
    projects = {}

    for session in data.get("sessions_all", []):
        if not _day_in_range(session.get("last_date"), start, end):
            continue
        name = session.get("project") or "unknown"
        item = projects.setdefault(
            name,
            {
                "project": name,
                "sessions": 0,
                "turns": 0,
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_creation": 0,
                "reasoning": 0,
                "total_tokens": 0,
            },
        )
        item["sessions"] += 1
        item["turns"] += _int(session.get("turns"))
        item["input"] += _int(session.get("input"))
        item["output"] += _int(session.get("output"))
        item["cache_read"] += _int(session.get("cache_read"))
        item["cache_creation"] += _int(session.get("cache_creation"))
        item["reasoning"] += _int(session.get("reasoning"))

    rows = [_finalize_totals(item) for item in projects.values()]
    rows.sort(key=lambda row: row["total_tokens"], reverse=True)
    return rows[:limit]


def model_totals(data, days=30):
    start, end = _range_bounds(days)
    models = {}

    for row in data.get("daily_by_model", []):
        if not _day_in_range(row.get("day"), start, end):
            continue
        name = row.get("model") or "unknown"
        item = models.setdefault(
            name,
            {
                "model": name,
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_creation": 0,
                "reasoning": 0,
                "turns": 0,
                "total_tokens": 0,
            },
        )
        item["input"] += _int(row.get("input"))
        item["output"] += _int(row.get("output"))
        item["cache_read"] += _int(row.get("cache_read"))
        item["cache_creation"] += _int(row.get("cache_creation"))
        item["reasoning"] += _int(row.get("reasoning"))
        item["turns"] += _int(row.get("turns"))

    rows = [_finalize_totals(item) for item in models.values()]
    rows.sort(key=lambda row: row["total_tokens"], reverse=True)
    return rows


def project_branch_totals(data, days=30, limit=20):
    start, end = _range_bounds(days)
    branches = {}

    for session in data.get("sessions_all", []):
        if not _day_in_range(session.get("last_date"), start, end):
            continue
        project = session.get("project") or "unknown"
        branch = session.get("branch") or ""
        key = (project, branch)
        item = branches.setdefault(
            key,
            {
                "project": project,
                "branch": branch,
                "sessions": 0,
                "turns": 0,
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_creation": 0,
                "reasoning": 0,
                "total_tokens": 0,
            },
        )
        item["sessions"] += 1
        item["turns"] += _int(session.get("turns"))
        item["input"] += _int(session.get("input"))
        item["output"] += _int(session.get("output"))
        item["cache_read"] += _int(session.get("cache_read"))
        item["cache_creation"] += _int(session.get("cache_creation"))
        item["reasoning"] += _int(session.get("reasoning"))

    rows = [_finalize_totals(item) for item in branches.values()]
    rows.sort(key=lambda row: row["total_tokens"], reverse=True)
    return rows[:limit]


def build_payload(data):
    return {
        "source": "codex-usage",
        "generated_at": data.get("generated_at"),
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "all_models": data.get("all_models", []),
        "ranges": {
            "today": totals_for_range(data, "Today", 1),
            "seven_days": totals_for_range(data, "7 days", 7),
            "thirty_days": totals_for_range(data, "30 days", 30),
            "all_time": totals_for_range(data, "All time", None),
        },
        "models_30d": model_totals(data, 30),
        "top_projects_30d": top_projects(data, 30),
        "charts": {
            "range_label": "30 days",
            "daily_30d": daily_totals(data, 30),
            "daily_by_model_30d": daily_rows_for_range(data, 30),
            "hourly_30d": hourly_totals(data, 30),
            "models_30d": model_totals(data, 30),
            "projects_30d": top_projects(data, 30, 10),
            "project_branches_30d": project_branch_totals(data, 30, 20),
        },
        "recent_sessions": data.get("sessions_all", [])[:8],
    }


def export_summary(output_path, db_path=None, scan_first=True, projects_dir=None):
    db = Path(db_path).expanduser() if db_path else scanner.DB_PATH
    if scan_first:
        scanner.scan(
            projects_dir=Path(projects_dir).expanduser() if projects_dir else None,
            db_path=db,
            verbose=False,
        )
    data = dashboard.get_dashboard_data(db)
    payload = build_payload(data)

    if output_path == "-":
        print(json.dumps(payload, indent=2))
    else:
        output = Path(output_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export Codex usage summary JSON for Home Assistant.")
    parser.add_argument("--output", "-o", default=str(Path.home() / ".codex" / "ha-codex-usage-summary.json"))
    parser.add_argument("--db", default=None, help="Path to usage.db")
    parser.add_argument("--projects-dir", default=None, help="Codex transcript directory to scan")
    parser.add_argument("--no-scan", action="store_true", help="Export existing DB data without scanning first")
    args = parser.parse_args(argv)

    export_summary(
        args.output,
        db_path=args.db,
        scan_first=not args.no_scan,
        projects_dir=args.projects_dir,
    )


if __name__ == "__main__":
    main()
