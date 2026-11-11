"""Checks for Agent Skills (a folder with a SKILL.md).

Rules follow Anthropic's Agent Skills specification and authoring best practices:
errors are things that break loading or uploading; warnings are things that make
the skill trigger badly, waste context, or drift from the documented guidance.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

from ..report import ERROR, INFO, WARNING, Finding, display_path
from ..textutil import (IGNORE_LINE, FrontmatterError, code_block_flags, is_ignored_file, iter_files,
                        key_line, parse_yaml, parse_yaml_lenient, read_text, split_frontmatter)

SPEC_KEYS = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
# Accepted by Claude Code but rejected by the claude.ai / API skill upload.
CLAUDE_CODE_KEYS = {
    "when_to_use", "argument-hint", "arguments", "disable-model-invocation", "user-invocable",
    "disallowed-tools", "model", "effort", "context", "agent", "background", "hooks", "paths", "shell",
}
SUPPORT_DIRS = "references|reference|scripts|assets|templates|examples|evals|resources|docs"

NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
RESERVED = re.compile(r"claude|anthropic", re.I)

WHEN_RE = re.compile(
    r"\buse (?:this|it|when|for|to|whenever|if|on)\b|\bwhen(?:ever)?\b|\btrigger|\binvoke|\bif the user\b|"
    r"\basks? (?:for|to|about)\b|\bfor (?:tasks|requests|questions)\b"
    # common trigger words in other languages (es, pt, it, fr, de, nl)
    r"|\b(?:cuando|úsal[ao]|usar para|quando|quand|lorsque|wenn|wanneer)\b", re.I)
FIRST_SECOND_PERSON = re.compile(
    r"^\s*(?:i\s|i'm\b|i am\b|you\b|you're\b|act as\b|as an?\b)|\b(?:i can|i will|i'll|i help|you can use me|let me)\b",
    re.I)
SHOUTING = re.compile(r"\b(MUST|NEVER|ALWAYS|CRITICAL|IMPORTANT|MANDATORY)\b")

DESC_MAX = 1024
NAME_MAX = 64
COMBINED_MAX = 1536
BODY_WARN_LINES = 500


def check_skill(root: Path) -> List[Finding]:
    root = root.resolve()
    findings: List[Finding] = []
    skill_md = root / "SKILL.md"
    shown = display_path(skill_md)

    def add(code, level, msg, line=None, path=None):
        findings.append(Finding(code, level, msg, path or shown, line))

    if not skill_md.is_file():
        add("SV101", ERROR, "SKILL.md not found in this folder")
        return findings

    nested = [p for p in iter_files(root, frozenset({"evals", "examples", "templates", "tests"}))
              if p.name == "SKILL.md" and p != skill_md]
    for p in nested:
        add("SV119", WARNING, "Nested SKILL.md inside another skill: it will not load as its own skill, "
                              "and claude.ai rejects uploads with more than one", path=display_path(p))

    text = read_text(skill_md)
    raw, body, body_start = split_frontmatter(text)
    if raw is None:
        add("SV102", ERROR, "Missing YAML frontmatter: SKILL.md must start with '---', name and description, '---'", 1)
        return findings
    try:
        fm = parse_yaml(raw)
    except FrontmatterError as exc:
        try:
            fm = parse_yaml_lenient(raw)
        except FrontmatterError:
            add("SV103", ERROR, f"Invalid YAML frontmatter ({exc}); the skill will load without a name or "
                                "description", 1)
            return findings
        add("SV122", WARNING, f"Frontmatter is not strict YAML ({exc}). Claude Code tolerates it, but claude.ai "
                              "uploads and strict validators reject it: wrap values containing ': ' in quotes", 1)

    # ---- keys
    for key in sorted(set(fm) - SPEC_KEYS - CLAUDE_CODE_KEYS):
        add("SV114", WARNING, f"Unknown frontmatter key '{key}' (not in the Agent Skills spec). "
                              "Move custom data under 'metadata:'", key_line(text, key))
    code_only = sorted(set(fm) & CLAUDE_CODE_KEYS)
    if code_only:
        add("SV115", INFO, f"Claude Code-only keys ({', '.join(code_only)}): fine in Claude Code, "
                           "but claude.ai and the API reject the upload", key_line(text, code_only[0]))

    # ---- name
    name = fm.get("name")
    nline = key_line(text, "name")
    if name is None or (isinstance(name, str) and not name.strip()):
        add("SV104", ERROR, "Missing 'name' in frontmatter", nline or 1)
    elif not isinstance(name, str):
        add("SV105", ERROR, f"'name' must be a string, got {type(name).__name__}", nline)
    else:
        name = name.strip()
        if not NAME_RE.fullmatch(name):
            add("SV105", ERROR, f"name '{name}' must be kebab-case: lowercase letters, digits and single hyphens", nline)
        if len(name) > NAME_MAX:
            add("SV105", ERROR, f"name is {len(name)} characters (max {NAME_MAX})", nline)
        if RESERVED.search(name):
            add("SV106", ERROR, "name cannot contain the reserved words 'claude' or 'anthropic'", nline)
        if name != root.name:
            add("SV107", WARNING, f"name '{name}' does not match the folder name '{root.name}'", nline)

    # ---- description
    desc = fm.get("description")
    dline = key_line(text, "description")
    if desc is None or (isinstance(desc, str) and not desc.strip()):
        add("SV108", ERROR, "Missing 'description': Claude uses it to decide when to load the skill", dline or 1)
    elif not isinstance(desc, str):
        add("SV108", ERROR, f"'description' must be a string, got {type(desc).__name__}", dline)
    else:
        d = " ".join(desc.split())
        if len(d) > DESC_MAX:
            add("SV109", ERROR, f"description is {len(d)} characters (max {DESC_MAX})", dline)
        wtu = fm.get("when_to_use")
        if isinstance(wtu, str) and len(d) + len(" ".join(wtu.split())) > COMBINED_MAX:
            add("SV121", WARNING, f"description + when_to_use exceed {COMBINED_MAX} characters; "
                                  "Claude Code truncates them in the skill list", dline)
        if re.search(r"<[A-Za-z/!]", d):
            add("SV110", ERROR, "description contains XML/HTML tags, which the skill spec does not allow", dline)
        if not WHEN_RE.search(d):
            add("SV111", WARNING, "description does not say WHEN to use the skill (e.g. 'Use when the user asks "
                                  "to...'); without triggers Claude rarely loads it", dline)
        if len(d) < 80:
            add("SV112", WARNING, f"description is only {len(d)} characters: probably too vague to trigger reliably",
                dline)
        if FIRST_SECOND_PERSON.search(d):
            add("SV113", WARNING, "description should be written in third person ('Extracts tables from PDFs...'), "
                                  "not 'I can...' or 'You can...'", dline)

    # ---- size and style
    total = len(text.splitlines())
    if total > BODY_WARN_LINES:
        add("SV116", WARNING, f"SKILL.md is {total} lines (keep it under {BODY_WARN_LINES}; "
                              "move detail into reference files loaded on demand)")
    body_lines = body.splitlines()
    flags = code_block_flags(body_lines)
    shouts = [m.group(0) for ln, inside in zip(body_lines, flags) if not inside and IGNORE_LINE not in ln
              for m in SHOUTING.finditer(ln)]
    if len(shouts) > 5:
        add("SV120", WARNING, f"{len(shouts)} all-caps emphasis words ({', '.join(sorted(set(shouts)))}). Recent "
                              "Claude models follow instructions closely and over-apply shouted rules; "
                              "explain the reason instead", body_start)

    findings.extend(_check_long_references(root))
    findings.extend(_check_references(root))
    return findings


def _check_long_references(root: Path) -> List[Finding]:
    out = []
    for p in iter_files(root):
        if p.suffix.lower() != ".md" or p.name == "SKILL.md":
            continue
        lines = read_text(p).splitlines()
        if len(lines) > 100 and not is_ignored_file(lines):
            head = "\n".join(lines[:30]).lower()
            if not re.search(r"contents|index|índice|indice|contenido|sommaire|inhalt|sumário|\n\s*(?:[-*]|\d+\.) \[",
                             head):
                out.append(Finding("SV117", WARNING, f"{len(lines)}-line reference file without a table of contents "
                                   "near the top; Claude may only preview part of it", display_path(p)))
    return out


_LINK_RE = re.compile(r"\[[^\]]*\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_BARE_RE = re.compile(rf"(?<![\w/.\-])((?:[\w\-]+/)?(?:{SUPPORT_DIRS})/[\w./\-]*\w\.[A-Za-z0-9]+)")


def _check_references(root: Path) -> List[Finding]:
    out: List[Finding] = []
    seen = set()
    for p in iter_files(root):
        if p.suffix.lower() not in (".md", ".txt"):
            continue
        if p.name.upper().startswith(HISTORY_FILES):
            continue  # history files describe files that used to exist
        lines = read_text(p).splitlines()
        if is_ignored_file(lines):
            continue
        flags = code_block_flags(lines)
        for i, ln in enumerate(lines):
            if flags[i] or IGNORE_LINE in ln:
                continue
            candidates = [m.group(1) for m in _LINK_RE.finditer(ln)]
            candidates += [m.group(1).rstrip(".") for m in _BARE_RE.finditer(ln)]
            for ref in candidates:
                if not _is_local_ref(ref):
                    continue
                clean = ref.split("#", 1)[0].split("?", 1)[0]
                if not clean or (clean, p) in seen:
                    continue
                seen.add((clean, p))
                if (p.parent / clean).exists() or (root / clean).exists():
                    continue
                pos = ln.find(ref)
                if CREATES_FILE.search(re.split(r"[.!?;]\s", ln[:max(pos, 0)])[-1]):
                    continue  # "create evals/evals.json", "for example scripts/x.py": not an existing-file reference
                first = clean.split("/")[0]
                cross_skill = first not in SUPPORT_DIRS.split("|") and "/" in clean
                if cross_skill and (root.parent / clean).exists():
                    continue  # reference into a sibling skill that exists
                level = ERROR if p.name == "SKILL.md" and not cross_skill else WARNING
                where = " (another skill?)" if cross_skill else ""
                out.append(Finding("SV118", level, f"References '{clean}', which does not exist{where}",
                                   display_path(p), i + 1))
    return out


CREATES_FILE = re.compile(
    r"\b(?:if|unless|whether|creates?|save[sd]?|writes?|generates?|outputs?|produces?|exports? to|adds?|e\.g\.|for example|such as|"
    r"crea|guarda|genera|escribe|ej\.|por ejemplo)\b", re.I)
HISTORY_FILES = ("CHANGELOG", "TEST_RESULTS", "HISTORY", "RELEASE_NOTES")


def _is_local_ref(ref: str) -> bool:
    if re.match(r"^[a-z][a-z0-9+.\-]*:", ref, re.I):  # http:, mailto:, file:, C: ...
        return False
    if ref.startswith(("#", "/", "~", "$", "{", "<", "%")) or "{{" in ref or "*" in ref:
        return False
    if re.match(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]*/", ref):  # SKILL_DIR/scripts/x.py: a path template
        return False
    return "." in ref.rsplit("/", 1)[-1] or ref.endswith("/")
