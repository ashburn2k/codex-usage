# Codex Usage Dashboard

Local token-usage dashboard for Codex Desktop / Codex CLI transcripts.

This is a Codex-oriented port of [phuryn/claude-usage](https://github.com/phuryn/claude-usage). It keeps the same small Python shape: no package install, no database server, no third-party Python dependencies. It scans local JSONL transcripts, stores usage in SQLite, and serves a Chart.js dashboard.

## What This Tracks

Codex writes local session transcripts under:

```text
~/.codex/sessions/YYYY/MM/DD/*.jsonl
```

This tool reads `event_msg` records whose payload type is `token_count` and captures:

- input tokens, split into non-cached input and cached input
- output tokens
- reasoning output tokens
- sessions, projects, timestamps, and provider labels

Codex logs currently expose provider names such as `codex/custom`, not stable public model names or pricing. For that reason, cost columns render as `n/a` instead of applying unrelated Claude API prices.

## Requirements

- Python 3.8+
- No third-party Python packages

## Usage

```bash
# Scan Codex JSONL files and populate ~/.codex/usage.db
python3 cli.py scan

# Show today's usage summary
python3 cli.py today

# Show the last 7 days
python3 cli.py week

# Show all-time statistics
python3 cli.py stats

# Scan, start the dashboard, and open it in a browser
python3 cli.py dashboard

# Custom host and port
HOST=0.0.0.0 PORT=9000 python3 cli.py dashboard

# Scan a custom transcript directory
python3 cli.py scan --projects-dir /path/to/sessions

# Export compact JSON for Home Assistant
python3 ha_export.py --output ~/.codex/ha-codex-usage-summary.json
```

The scanner is incremental. It tracks each file path, modification time, and processed line count, so repeated scans only process new transcript lines.

## How It Works

`scanner.py` walks `~/.codex/sessions/**/*.jsonl`. Each session normally starts with a `session_meta` record, then usage appears in `event_msg` records:

```json
{
  "type": "event_msg",
  "payload": {
    "type": "token_count",
    "info": {
      "last_token_usage": {
        "input_tokens": 25660,
        "cached_input_tokens": 25472,
        "output_tokens": 382,
        "reasoning_output_tokens": 280
      }
    }
  }
}
```

Because `input_tokens` includes cached input, the scanner stores:

- `input_tokens - cached_input_tokens` as input
- `cached_input_tokens` as cached input
- `output_tokens` as output
- `reasoning_output_tokens` as reasoning

Data is stored in `~/.codex/usage.db`.

## Files

| File | Purpose |
|------|---------|
| `scanner.py` | Parses Codex JSONL transcripts into SQLite |
| `dashboard.py` | HTTP server plus single-page dashboard |
| `cli.py` | `scan`, `today`, `week`, `stats`, and `dashboard` commands |
| `ha_export.py` | Compact JSON exporter for Home Assistant cards |
| `tests/` | Unit tests for parser, CLI helpers, and dashboard API |
| `vscode-extension/` | Original extension source from upstream; not yet ported to Codex naming |

## Attribution

Based on [phuryn/claude-usage](https://github.com/phuryn/claude-usage), licensed under MIT. This port keeps the original license file.
