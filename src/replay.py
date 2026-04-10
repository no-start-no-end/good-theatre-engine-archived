"""Interactive replay console for performance logs.

Allows stepping through events forward/backward, filtering, and annotating.
Run with:
    python3 -m src.replay --log-dir ./logs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


class ReplayConsole:
    """Step through events one at a time with filtering and annotation."""

    def __init__(self, events: list[dict]):
        self.events = events
        self.index = 0
        self.filter_type: Optional[str] = None
        self.filter_source: Optional[str] = None
        self.annotations: dict[int, str] = {}
        self.filtered = list(range(len(events)))

    def _matches(self, i: int) -> bool:
        if self.filter_type:
            msg_type = self.events[i].get("message", {}).get("type", "")
            if msg_type != self.filter_type:
                return False
        if self.filter_source:
            src = self.events[i].get("message", {}).get("source", "")
            if self.filter_source not in src:
                return False
        return True

    def _build_filtered(self):
        self.filtered = [i for i in range(len(self.events)) if self._matches(i)]
        if self.filtered:
            self.index = max(0, min(self.index, len(self.filtered) - 1))

    def cmd_filter(self, args: list[str]):
        """filter [type] [source-substring] — filter the visible event stream."""
        self.filter_type = args[0] if len(args) > 0 and args[0] != "_" else self.filter_type
        self.filter_source = args[1] if len(args) > 1 and args[1] != "_" else self.filter_source
        self._build_filtered()
        print(f"Filter: type={self.filter_type or '*'}, source={self.filter_source or '*'}")
        print(f"{len(self.filtered)} events match")

    def cmd_step(self, args: list[str]):
        """step [n] — move forward n events (default 1)."""
        n = int(args[0]) if args and args[0].isdigit() else 1
        self.index = min(self.index + n, len(self.filtered) - 1)
        self._show(self.filtered[self.index])

    def cmd_back(self, args: list[str]):
        """back [n] — move backward n events (default 1)."""
        n = int(args[0]) if args and args[0].isdigit() else 1
        self.index = max(self.index - n, 0)
        self._show(self.filtered[self.index])

    def cmd_goto(self, args: list[str]):
        """goto <idx> — jump to event at filtered index idx."""
        if args:
            self.index = max(0, min(int(args[0]), len(self.filtered) - 1))
            self._show(self.filtered[self.index])

    def cmd_show(self, args: list[str]):
        """show <n> — show n events around current position."""
        n = min(int(args[0]) if args and args[0].isdigit() else 5, len(self.filtered))
        start = max(0, self.index - n)
        end = min(len(self.filtered), self.index + n + 1)
        for i in range(start, end):
            marker = ">>>" if i == self.index else "   "
            self._show(self.filtered[i], marker=marker)

    def cmd_tag(self, args: list[str]):
        """tag <text> — annotate the current event."""
        if args:
            self.annotations[self.filtered[self.index]] = " ".join(args)
            print(f"Tagged: {' '.join(args)}")

    def cmd_info(self, args: list[str]):
        """info — show summary statistics."""
        total = len(self.events)
        print(f"Total events: {total}")
        print(f"Filtered: {len(self.filtered)} / {total}")
        if self.annotations:
            print(f"Annotations: {len(self.annotations)}")
        types: dict[str, int] = {}
        for e in self.events:
            t = e.get("message", {}).get("type", "?")
            types[t] = types.get(t, 0) + 1
        print("By type:", dict(sorted(types.items(), key=lambda x: -x[1])))

    def cmd_save(self, args: list[str]):
        """save <path> — write annotated events to a JSON file."""
        path = args[0] if args else "annotated_events.json"
        annotated = [
            {**self.events[i], "annotation": self.annotations.get(i, "")}
            for i in sorted(self.annotations.keys())
        ]
        Path(path).write_text(json.dumps(annotated, indent=2))
        print(f"Saved {len(annotated)} annotated events to {path}")

    def _show(self, i: int, marker: str = "   "):
        entry = self.events[i]
        msg = entry.get("message", {})
        ts = entry.get("logged_at", "?")
        t = msg.get("type", "?")
        src = msg.get("source", "?")
        payload = msg.get("payload", {})
        trace = entry.get("trace_id", "?")[:8]
        ann = self.annotations.get(i, "")
        ann_str = f" # {ann}" if ann else ""
        print(f"{marker} [{i:05d}] {ts} ({trace}) {t:22s} {src:30s} {json.dumps(payload)}{ann_str}")

    def cmd_help(self, args: list[str]):
        print("Commands:")
        for name in sorted(self._commands.keys()):
            print(f"  {name} — {self._commands[name].__doc__ or name}")

    _commands: dict[str, object] = {}

    def run(self):
        self._commands = {
            "filter": self.cmd_filter,
            "step": self.cmd_step,
            "back": self.cmd_back,
            "goto": self.cmd_goto,
            "show": self.cmd_show,
            "tag": self.cmd_tag,
            "info": self.cmd_info,
            "save": self.cmd_save,
            "?": self.cmd_help,
            "help": self.cmd_help,
        }
        print(f"Good Theatre — Replay Console")
        print(f"{len(self.events)} events loaded. Position {self.index}/{len(self.events)-1}")
        print("Commands: filter, step, back, goto, show, tag, info, save, help")
        print()
        if self.events:
            self._show(self.filtered[self.index])
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                self.index = min(self.index + 1, len(self.filtered) - 1)
                self._show(self.filtered[self.index])
                continue
            parts = line.split()
            cmd = parts[0]
            args = parts[1:]
            if cmd == "q" or cmd == "quit":
                break
            handler = self._commands.get(cmd)
            if handler:
                handler(args)
            else:
                print(f"Unknown command: {cmd}. Try 'help'.")


def load_events(log_dir: str) -> list[dict]:
    path = Path(log_dir) / "events.jsonl"
    if not path.exists():
        print(f"No events file at {path}")
        return []
    events = []
    with path.open("r", encoding="utf-8") as h:
        for line in h:
            if line.strip():
                events.append(json.loads(line))
    return events


def main():
    parser = argparse.ArgumentParser(description="Good Theatre interactive replay")
    parser.add_argument("--log-dir", "-d", default="./logs")
    args = parser.parse_args()

    events = load_events(args.log_dir)
    if not events:
        print("No events found.")
        return
    ReplayConsole(events).run()


if __name__ == "__main__":
    main()
