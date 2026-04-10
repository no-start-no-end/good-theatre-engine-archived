"""Replay and analysis tool for performance logs."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from .core.error_log import ErrorLog
from .core.knowledge import KnowledgeBase


def replay_log(log_path: str, filter_type: str | None = None, limit: int = 0):
    """Print a human-readable replay of events.jsonl."""
    path = Path(log_path)
    if not path.exists():
        print(f"Log not found: {path}")
        return

    events = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                events.append(json.loads(line))

    if limit:
        events = events[-limit:]

    count = 0
    for entry in events:
        msg = entry.get("message", {})
        if filter_type and msg.get("type") != filter_type:
            continue
        ts = entry.get("logged_at", "")
        msg_type = msg.get("type", "?")
        source = msg.get("source", "?")
        payload = msg.get("payload", {})
        trace = entry.get("trace_id", "?")[:8]

        print(f"[{ts}] ({trace}) {msg_type:20s} {source:30s} {json.dumps(payload)}")
        count += 1

    print(f"\n{count} events shown")


def analyse_performance(log_dir: str):
    """Print a summary of a performance run."""
    log_path = Path(log_dir)
    events_path = log_path / "events.jsonl"
    state_path = log_path / "performance_state.json"
    patterns_path = log_path / "patterns.jsonl"

    print("=== Good Theatre — Performance Analysis ===\n")

    # State
    if state_path.exists():
        state = json.loads(state_path.read_text())
        print(f"Show:        {state.get('name', '?')}")
        print(f"Final phase:  {state.get('phase', '?')}")
        print(f"Final energy: {state.get('energy_level', '?')}")

    # Events summary
    if events_path.exists():
        event_counts: dict[str, int] = defaultdict(int)
        source_counts: dict[str, int] = defaultdict(int)
        with events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    entry = json.loads(line)
                    msg = entry.get("message", {})
                    event_counts[msg.get("type", "?")] += 1
                    source_counts[msg.get("source", "?")] += 1

        total = sum(event_counts.values())
        print(f"\n--- Events ({total} total) ---")
        for evt, count in sorted(event_counts.items()):
            print(f"  {evt:30s}: {count:4d}")

        print(f"\n--- Top Sources ---")
        for src, count in sorted(source_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"  {src:30s}: {count:4d}")

    # Patterns
    if patterns_path.exists():
        patterns = []
        with patterns_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    patterns.append(json.loads(line))

        if patterns:
            print(f"\n--- Patterns ({len(patterns)} learned) ---")
            by_trigger: dict[str, list] = defaultdict(list)
            for p in patterns:
                by_trigger[p.get("trigger", "?")].append(p)
            for trigger, ps in sorted(by_trigger.items(), key=lambda x: -len(x[1]))[:5]:
                avg = sum(p.get("success", 0) for p in ps) / len(ps)
                print(f"  {trigger:30s}: {len(ps):3d} occurrences, avg success {avg:.2f}")

    # Errors
    errlog = ErrorLog(str(log_path))
    summary = errlog.summary()
    if summary["total"] > 0:
        print(f"\n--- Errors ({summary['total']} total) ---")
        for sev, count in summary["by_severity"].items():
            if count > 0:
                print(f"  {sev:15s}: {count}")
        if summary["non_recoverable"]:
            print("  Non-recoverable:")
            for e in summary["non_recoverable"]:
                print(f"    [{e['phase']}] {e['source']}: {e['message']}")


def main():
    parser = argparse.ArgumentParser(description="Good Theatre log analysis")
    parser.add_argument("command", choices=["replay", "analyse"])
    parser.add_argument("path", nargs="?", default="./logs")
    parser.add_argument("--type", "-t", default=None, help="Filter by message type")
    parser.add_argument("--limit", "-l", type=int, default=0, help="Limit to last N events")
    args = parser.parse_args()

    if args.command == "replay":
        replay_log(args.path, filter_type=args.type, limit=args.limit)
    elif args.command == "analyse":
        analyse_performance(args.path)


if __name__ == "__main__":
    main()
