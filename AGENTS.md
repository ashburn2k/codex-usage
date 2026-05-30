# AGENTS.md

Guidance for coding agents working on this Codex usage dashboard.

## Project Shape

This is a small Python 3.8+ project using only the standard library.

- [scanner.py](scanner.py) parses Codex JSONL transcripts into `~/.codex/usage.db`.
- [cli.py](cli.py) provides `scan`, `today`, `week`, `stats`, and `dashboard`.
- [dashboard.py](dashboard.py) serves an embedded HTML/JS dashboard on `localhost:8080`.
- [tests/](tests/) contains the unit test suite.

The VS Code extension directory is still the upstream Claude extension source and has not been renamed or packaged for Codex.

## Common Commands

```bash
python3 cli.py scan
python3 cli.py today
python3 cli.py week
python3 cli.py stats
python3 cli.py dashboard
python3 cli.py scan --projects-dir PATH
HOST=0.0.0.0 PORT=9000 python3 cli.py dashboard

python3 -m unittest discover -s tests
python3 -m unittest tests.test_scanner -v
```

## Data Flow

```text
~/.codex/sessions/**/*.jsonl
        -> scanner.parse_jsonl_file()
        -> aggregate_sessions()
        -> upsert_sessions() + insert_turns()
        -> ~/.codex/usage.db
        -> cli.py queries and dashboard.py /api/data
```

Codex usage is stored in `event_msg` records with `payload.type == "token_count"`.
Use `payload.info.last_token_usage` for per-call usage.

Important token mapping:

- `input_tokens` includes cached input.
- Store `input_tokens - cached_input_tokens` as normal input.
- Store `cached_input_tokens` as cached input.
- Store `output_tokens` as output.
- Store `reasoning_output_tokens` as reasoning.

Codex transcripts currently expose provider names, not stable public model-pricing IDs. Keep cost estimates as `n/a` unless a real Codex pricing source is added.

## SQLite Notes

- `turns` is the token source of truth.
- `sessions` stores denormalized per-session totals.
- `processed_files` tracks `(path, mtime, lines)` for incremental scans.
- `turns.message_id` is synthesized from `absolute_path:line_number`; keep it stable so forced rescans do not duplicate rows.
- After scan updates, session totals are recomputed from `turns`; preserve this reconciliation step.

## Testing Notes

- Tests must use temporary DBs and transcript directories.
- Do not touch the user's real `~/.codex/usage.db` in tests.
- The `/api/rescan` test patches `dashboard.DB_PATH` and `scanner.DEFAULT_PROJECTS_DIRS`; keep that contract intact.
