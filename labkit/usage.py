"""Parse recorded usage. Missing values stay missing, never zero or estimated.

exec JSONL exposes turn totals. Optional rollout token_count records expose
successive usage totals in some CLI versions. The latter is a version-dependent
adapter, enabled only when its increments reconcile with the exec total.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def events(path: Path) -> tuple[list[dict], int]:
    records, bad = [], 0
    if not path.exists():
        return [], 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("not an event")
            records.append(item)
        except (ValueError, TypeError):
            bad += 1
    return records, bad


def valid_count(value: object) -> bool:
    return type(value) is int and value >= 0


def parse_usage(path: Path, rollout: Path | None = None) -> dict:
    records, bad = events(path)
    totals = []
    thread = None
    commands = []
    seen_items = set()
    failed = False
    for event in records:
        kind = event.get("type")
        if kind == "thread.started":
            value = event.get("thread_id")
            thread = value if isinstance(value, str) else None
        if kind in ("turn.failed", "error"):
            failed = True
        if kind == "turn.completed":
            usage = event.get("usage", {})
            if not isinstance(usage, dict):
                bad += 1
                continue
            if valid_count(usage.get("input_tokens")) and valid_count(
                usage.get("output_tokens")
            ):
                totals.append(usage)
        if kind == "item.completed":
            item = event.get("item", {})
            if not isinstance(item, dict):
                bad += 1
                continue
            key = item.get("id")
            if key is not None and not isinstance(key, str):
                bad += 1
                continue
            if key and key in seen_items:
                continue
            if key:
                seen_items.add(key)
            if item.get("type") == "command_execution":
                if not isinstance(item.get("command", ""), str):
                    bad += 1
                    continue
                commands.append(
                    {
                        "command": item.get("command", ""),
                        "exit_code": item.get("exit_code"),
                    }
                )
    result = {
        "thread_id": thread,
        "input_tokens": None,
        "output_tokens": None,
        "cached_input_tokens": None,
        "usage_source": "not_available",
        "calls": [],
        "call_detail": "not_available",
        "commands": commands,
        "document_candidates": [],
        "failed_event": failed,
        "malformed_lines": bad,
        "completed_turns": sum(e.get("type") == "turn.completed" for e in records),
    }
    # This exercise starts one new user turn. Several completed turns would need
    # explicit scope interpretation; do not silently add possibly cumulative totals.
    if len(totals) == 1 and not bad:
        result.update(
            input_tokens=totals[0]["input_tokens"],
            output_tokens=totals[0]["output_tokens"],
            cached_input_tokens=totals[0].get("cached_input_tokens"),
            usage_source="exec.turn.completed",
        )
    if rollout:
        detailed, detailed_bad = events(rollout)
        previous, calls, broken = 0, [], bool(detailed_bad)
        for event in detailed:
            payload = event.get("payload", {})
            if event.get("type") != "event_msg":
                continue
            if not isinstance(payload, dict):
                broken = True
                continue
            if payload.get("type") != "token_count":
                continue
            info = payload.get("info") or {}
            if not isinstance(info, dict):
                broken = True
                continue
            token_usage = info.get("total_token_usage") or {}
            if not isinstance(token_usage, dict):
                broken = True
                continue
            total = token_usage.get("input_tokens")
            if not valid_count(total):
                continue
            if total < previous:
                broken = True
                break
            if total > previous:
                calls.append(total - previous)
                previous = total
        if calls and not broken and previous == result["input_tokens"]:
            result.update(calls=calls, call_detail="rollout.token_count.reconciled")
    paths = set()
    for command in commands:
        text = command["command"]
        # A path in a command is evidence of a reference, not proof of a full read.
        paths.update(re.findall(r"(?:docs/[\w./-]+\.md|AGENTS(?:\.[\w-]+)?\.md)", text))
    result["document_candidates"] = sorted(paths)
    return result
