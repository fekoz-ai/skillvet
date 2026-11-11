"""Checks for Claude Code hook configuration (settings.json, settings.local.json, plugin hooks/hooks.json)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

from ..report import ERROR, WARNING, Finding, display_path
from ..textutil import read_text

HOOK_EVENTS = {
    "SessionStart", "Setup", "UserPromptSubmit", "UserPromptExpansion", "PreToolUse", "PermissionRequest",
    "PermissionDenied", "PostToolUse", "PostToolUseFailure", "PostToolBatch", "Notification", "MessageDisplay",
    "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted", "Stop", "StopFailure", "TeammateIdle",
    "InstructionsLoaded", "ConfigChange", "CwdChanged", "FileChanged", "WorktreeCreate", "WorktreeRemove",
    "PreCompact", "PostCompact", "Elicitation", "ElicitationResult", "SessionEnd",
}
# hook type -> field it cannot work without (None: no single required field we can verify)
HOOK_TYPES = {"command": "command", "prompt": "prompt", "agent": "prompt", "http": "url", "mcp_tool": None}


def _line_of(text: str, needle: str, start: int = 0) -> Optional[int]:
    idx = text.find(needle, start)
    return text.count("\n", 0, idx) + 1 if idx >= 0 else None


def check_hooks(path: Path) -> List[Finding]:
    path = path.resolve()
    shown = display_path(path)
    findings: List[Finding] = []

    def add(code, level, msg, line=None):
        findings.append(Finding(code, level, msg, shown, line))

    text = read_text(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        add("SV301", ERROR, f"Invalid JSON ({exc.msg}): Claude Code will ignore this whole file", exc.lineno)
        return findings
    if not isinstance(data, dict):
        add("SV301", ERROR, "Top level must be a JSON object", 1)
        return findings

    if "hooks" in data:
        hooks = data["hooks"]
        if not isinstance(hooks, dict):
            add("SV302", ERROR, "'hooks' must be an object mapping event names to lists", _line_of(text, '"hooks"'))
            return findings
    elif any(k in HOOK_EVENTS for k in data):
        hooks = data  # plugin hooks.json written without the "hooks" wrapper
    else:
        return findings  # a settings file with no hooks: nothing to check

    for event, groups in hooks.items():
        eline = _line_of(text, f'"{event}"')
        if event not in HOOK_EVENTS:
            close = [e for e in HOOK_EVENTS if e.lower() == event.lower()]
            hint = f" (did you mean '{close[0]}'?)" if close else ""
            add("SV303", WARNING, f"Unknown hook event '{event}'{hint}; it will never fire", eline)
            continue
        if not isinstance(groups, list):
            add("SV304", ERROR, f"'{event}' must be a list of matcher groups", eline)
            continue
        for gi, group in enumerate(groups):
            where = f"{event}[{gi}]"
            if not isinstance(group, dict):
                add("SV305", ERROR, f"{where} must be an object with a 'hooks' list", eline)
                continue
            matcher = group.get("matcher")
            if matcher is not None:
                if not isinstance(matcher, str):
                    add("SV310", ERROR, f"{where}.matcher must be a string", eline)
                elif matcher not in ("", "*"):
                    try:
                        re.compile(matcher)
                    except re.error as exc:
                        add("SV310", WARNING, f"{where}.matcher '{matcher}' is not a valid pattern ({exc})", eline)
            handlers = group.get("hooks")
            if not isinstance(handlers, list) or not handlers:
                add("SV305", ERROR, f"{where} has no 'hooks' list: nothing will run", eline)
                continue
            for hi, hook in enumerate(handlers):
                hw = f"{where}.hooks[{hi}]"
                if not isinstance(hook, dict):
                    add("SV306", ERROR, f"{hw} must be an object", eline)
                    continue
                htype = hook.get("type")
                if htype is None:
                    add("SV306", ERROR, f"{hw} is missing 'type' (command, prompt, agent, http or mcp_tool)", eline)
                    continue
                if not isinstance(htype, str) or htype not in HOOK_TYPES:
                    add("SV306", WARNING, f"{hw} has unknown type '{htype}'", eline)
                    continue
                field = HOOK_TYPES[htype]
                if field and (not isinstance(hook.get(field), str) or not hook.get(field).strip()):
                    add("SV307", ERROR, f"{hw} is a '{htype}' hook without a '{field}'", eline)
                timeout = hook.get("timeout")
                if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                                            or timeout <= 0):
                    add("SV308", WARNING, f"{hw}.timeout must be a positive number of seconds", eline)
                if htype == "http":
                    url = hook.get("url") or ""
                    if isinstance(url, str) and url.startswith("http://") and not re.match(
                            r"http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(/|$)", url):
                        add("SV309", WARNING, f"{hw} sends hook data over plain http to a remote host; use https",
                            eline)
    return findings
