"""Checks for Claude Code subagent files (.claude/agents/*.md, plugin agents/*.md)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

from ..report import ERROR, WARNING, Finding, display_path
from ..textutil import FrontmatterError, key_line, parse_yaml, parse_yaml_lenient, read_text, split_frontmatter

AGENT_KEYS = {
    "name", "description", "tools", "disallowedTools", "model", "permissionMode", "maxTurns", "skills",
    "mcpServers", "hooks", "memory", "background", "effort", "isolation", "color", "initialPrompt",
}
MODEL_ALIASES = {"sonnet", "opus", "haiku", "fable", "inherit"}
ENUMS = {
    "permissionMode": {"default", "acceptEdits", "auto", "dontAsk", "bypassPermissions", "plan"},
    "effort": {"low", "medium", "high", "xhigh", "max"},
    "color": {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"},
    "memory": {"user", "project", "local"},
    "isolation": {"worktree"},
}
NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def check_agent(path: Path) -> List[Finding]:
    path = path.resolve()
    shown = display_path(path)
    findings: List[Finding] = []

    def add(code, level, msg, line=None):
        findings.append(Finding(code, level, msg, shown, line))

    text = read_text(path)
    raw, body, body_start = split_frontmatter(text)
    if raw is None:
        add("SV201", ERROR, "Missing YAML frontmatter: a subagent file needs '---', name and description, '---'", 1)
        return findings
    try:
        fm = parse_yaml(raw)
    except FrontmatterError as exc:
        try:
            fm = parse_yaml_lenient(raw)
        except FrontmatterError:
            add("SV201", ERROR, f"Invalid YAML frontmatter ({exc}); Claude Code will skip this subagent", 1)
            return findings
        add("SV213", WARNING, f"Frontmatter is not strict YAML ({exc}). Claude Code tolerates it, but other "
                              "tools may not: wrap values containing ': ' in quotes", 1)

    name = fm.get("name")
    nline = key_line(text, "name")
    if not isinstance(name, str) or not name.strip():
        add("SV202", ERROR, "Missing 'name' (required): the subagent will not be registered", nline or 1)
    elif not NAME_RE.fullmatch(name.strip()):
        add("SV203", ERROR, f"name '{name}' must use lowercase letters, digits and hyphens", nline)

    desc = fm.get("description")
    dline = key_line(text, "description")
    if not isinstance(desc, str) or not desc.strip():
        add("SV204", ERROR, "Missing 'description' (required): Claude uses it to decide when to delegate",
            dline or 1)
    elif len(" ".join(desc.split())) < 40:
        add("SV211", WARNING, "description is very short; say what the subagent does and when Claude should "
                              "delegate to it", dline)

    for key in sorted(set(fm) - AGENT_KEYS):
        add("SV206", WARNING, f"Unknown frontmatter key '{key}' for a subagent; Claude Code ignores it",
            key_line(text, key))

    model = fm.get("model")
    if model is not None:
        mline = key_line(text, "model")
        if not isinstance(model, str) or not (model in MODEL_ALIASES or model.startswith("claude-")):
            add("SV205", WARNING, f"model '{model}' is not an alias (sonnet, opus, haiku, fable, inherit) "
                                  "or a full model ID starting with 'claude-'", mline)

    for key, allowed in ENUMS.items():
        value = fm.get(key)
        if value is not None and (not isinstance(value, str) or value not in allowed):
            add("SV207", WARNING, f"{key} '{value}' is not one of: {', '.join(sorted(allowed))}", key_line(text, key))

    if fm.get("permissionMode") == "bypassPermissions":
        add("SV208", WARNING, "permissionMode 'bypassPermissions' lets this subagent run every tool without asking; "
                              "make sure that is intended", key_line(text, "permissionMode"))

    tools = fm.get("tools")
    if tools is not None and not isinstance(tools, (str, list)):
        add("SV209", ERROR, "'tools' must be a comma-separated string or a list", key_line(text, "tools"))

    max_turns = fm.get("maxTurns")
    if max_turns is not None and (isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns < 1):
        add("SV207", WARNING, "maxTurns must be a positive integer", key_line(text, "maxTurns"))

    if not body.strip():
        add("SV210", WARNING, "Empty body: the markdown after the frontmatter is the subagent's system prompt",
            body_start)
    return findings


def duplicate_names(paths: List[Path]) -> List[Finding]:
    """Flag two subagent files in the same folder that declare the same name."""
    seen = {}
    out = []
    for p in paths:
        try:
            text = read_text(p)
            raw, _, _ = split_frontmatter(text)
            fm = parse_yaml_lenient(raw) if raw is not None else {}
        except (FrontmatterError, OSError):
            continue
        name = fm.get("name")
        if not isinstance(name, str):
            continue
        key = (p.resolve().parent, name.strip())
        if key in seen:
            out.append(Finding("SV212", ERROR, f"Duplicate subagent name '{name}' (also in {display_path(seen[key])})",
                               display_path(p), key_line(text, "name")))
        else:
            seen[key] = p
    return out
