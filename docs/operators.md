# Operators

## CLI
Run `python -m src.main --mode cli`.

Commands:
- `start`
- `stop`
- `status`
- `inject <type> <source> <payload_json>`
- `patterns`
- `override <target> <value>`
- `gate bypass|advisory|mandatory|override`
- `knowledge`
- `bus`
- `quit`

## Dashboard
Run `python -m src.main --mode dashboard` and open `http://127.0.0.1:8080`.

Features:
- live SSE event stream
- state and pattern panels
- event injection form
- gate control through POST endpoints
