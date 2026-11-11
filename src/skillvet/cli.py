"""Command-line entry point: skillvet [PATH ...]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from . import __version__
from .checks.agent import check_agent, duplicate_names
from .checks.hooks import check_hooks
from .checks.secrets import scan_file
from .checks.skill import check_skill
from .report import ERROR, WARNING, Finding, count, to_json, to_text
from .textutil import is_text_file, iter_files

Target = Tuple[str, Path]
HOOK_FILE_NAMES = {"settings.json", "settings.local.json", "hooks.json"}


def is_agent_file(p: Path) -> bool:
    """A markdown file directly in an agents/ folder, excluding READMEs, templates and drafts."""
    name = p.name.lower()
    return (p.suffix.lower() == ".md" and p.parent.name == "agents"
            and name not in ("readme.md", "changelog.md", "license.md")
            and ".template." not in name and not name.startswith(("_", ".")))


def _inside_skill(path: Path, skill_roots: List[Path]) -> bool:
    return any(root == path or root in path.parents for root in skill_roots)


def discover(path: Path) -> List[Target]:
    """Find skills, subagents and hook files under PATH."""
    path = path.resolve()
    if path.is_file():
        if path.name == "SKILL.md":
            return [("skill", path.parent)]
        if path.suffix.lower() == ".json":
            return [("hooks", path)]
        if path.suffix.lower() == ".md":
            return [("agent", path)]
        return []
    if not path.is_dir():
        return []
    if (path / "SKILL.md").is_file():
        return [("skill", path)]

    files = list(iter_files(path))
    skill_roots: List[Path] = []
    for p in sorted((f for f in files if f.name == "SKILL.md"), key=lambda f: len(f.parts)):
        if not _inside_skill(p.parent, skill_roots):  # shallowest SKILL.md wins
            skill_roots.append(p.parent)
    skill_roots.sort()
    targets: List[Target] = [("skill", r) for r in skill_roots]

    for p in files:
        if _inside_skill(p, skill_roots):
            continue
        if is_agent_file(p):
            targets.append(("agent", p))
        elif p.name in HOOK_FILE_NAMES and (p.parent.name in (".claude", "hooks") or p.parent == path):
            targets.append(("hooks", p))
    return targets


def run(targets: List[Target]) -> List[Finding]:
    findings: List[Finding] = []
    scanned = set()
    agent_files = []
    for kind, p in targets:
        if kind == "skill":
            findings.extend(check_skill(p))
            files = [f for f in iter_files(p) if is_text_file(f)]
        elif kind == "agent":
            findings.extend(check_agent(p))
            agent_files.append(p)
            files = [p]
        else:
            findings.extend(check_hooks(p))
            files = [p]
        for f in files:
            if f.resolve() not in scanned:
                scanned.add(f.resolve())
                findings.extend(scan_file(f))
    findings.extend(duplicate_names(agent_files))
    return findings


def _filter(findings: List[Finding], ignore: List[str]) -> List[Finding]:
    codes = {c.strip().upper() for c in ignore if c.strip()}
    return [f for f in findings if f.code not in codes]


def _hook_mode(ignore: List[str]) -> int:
    """Run as a Claude Code PostToolUse hook: check whatever file Claude just wrote.

    Exit code 2 sends the errors back to Claude so it can fix them; anything else is silent.
    """
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_input = payload.get("tool_input")
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(file_path, str) or not file_path:
        return 0
    p = Path(file_path)
    target: Optional[Target] = None
    for cand in [p.parent, *p.parents]:
        if (cand / "SKILL.md").is_file():
            target = ("skill", cand)
            break
        if cand == cand.parent:
            break
    if target is None:
        if is_agent_file(p):
            target = ("agent", p)
        elif p.name in HOOK_FILE_NAMES:
            target = ("hooks", p)
    if target is None or not target[1].exists():
        return 0
    findings = _filter(run([target]), ignore)
    errors = [f for f in findings if f.level == ERROR]
    if errors:
        sys.stderr.write(to_text(errors, [target], color=False) + "\n")
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="skillvet",
        description="Lint Claude Code skills, subagents and hooks: broken frontmatter, descriptions that never "
                    "trigger, missing files, invalid hook config and leaked API keys.",
    )
    ap.add_argument("paths", nargs="*", default=["."], help="skill folders, agent files, settings.json or a "
                                                            "project root to scan (default: current folder)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--strict", action="store_true", help="exit 1 on warnings too, not only errors")
    ap.add_argument("--verbose", "-v", action="store_true", help="also show info-level findings")
    ap.add_argument("--ignore", default="", help="comma-separated rule codes to skip, e.g. SV107,SV112")
    ap.add_argument("--no-color", action="store_true", help="disable colored output")
    ap.add_argument("--claude-hook", action="store_true",
                    help="run as a Claude Code PostToolUse hook (reads the event JSON from stdin)")
    ap.add_argument("--version", action="version", version=f"skillvet {__version__}")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    ignore = args.ignore.split(",") if args.ignore else []
    if args.claude_hook:
        return _hook_mode(ignore)

    targets: List[Target] = []
    missing = []
    for raw in args.paths:
        p = Path(raw)
        if not p.exists():
            missing.append(raw)
            continue
        for t in discover(p):
            if t not in targets:
                targets.append(t)
    for raw in missing:
        sys.stderr.write(f"skillvet: path not found: {raw}\n")
    if missing and not targets:
        return 2

    findings = _filter(run(targets), ignore)
    if args.json:
        print(to_json(findings, targets, __version__))
    else:
        if not targets:
            print("No skills, subagents or hook files found. Point skillvet at a skill folder, "
                  "an agents/*.md file, a settings.json or a project root.")
            return 0
        print(to_text(findings, targets, verbose=args.verbose, color=False if args.no_color else None))
    failed = count(findings, ERROR) or (args.strict and count(findings, WARNING))
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
