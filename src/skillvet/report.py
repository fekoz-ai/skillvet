"""Findings and output formatting."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional

ERROR = "error"
WARNING = "warning"
INFO = "info"
LEVEL_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}


@dataclass(frozen=True)
class Finding:
    code: str
    level: str
    message: str
    path: str
    line: Optional[int] = None

    def location(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


def display_path(path: Path) -> str:
    """Path relative to the working directory when possible, always with forward slashes."""
    try:
        rel = os.path.relpath(path)
        if not rel.startswith(".."):
            return rel.replace(os.sep, "/")
    except ValueError:  # different drive on Windows
        pass
    return str(path).replace(os.sep, "/")


def sort_findings(findings: Iterable[Finding]) -> List[Finding]:
    return sorted(findings, key=lambda f: (f.path, f.line or 0, LEVEL_ORDER[f.level], f.code))


def count(findings: Iterable[Finding], level: str) -> int:
    return sum(1 for f in findings if f.level == level)


def _use_color(stream) -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


_COLORS = {ERROR: "\033[31m", WARNING: "\033[33m", INFO: "\033[36m"}
_RESET = "\033[0m"
_DIM = "\033[2m"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def to_text(findings: List[Finding], targets: List[tuple], verbose: bool = False, color: Optional[bool] = None) -> str:
    if color is None:
        color = _use_color(sys.stdout)
    shown = [f for f in sort_findings(findings) if verbose or f.level != INFO]
    lines = []
    for f in shown:
        level = f"{f.level:<7}"
        if color:
            level = f"{_COLORS[f.level]}{level}{_RESET}"
            loc = f"{_DIM}{f.location()}{_RESET}"
        else:
            loc = f.location()
        lines.append(f"{loc}  {level}  {f.code}  {f.message}")

    kinds = {}
    for kind, _ in targets:
        kinds[kind] = kinds.get(kind, 0) + 1
    labels = {"skill": "skill", "agent": "agent", "hooks": "hooks file"}
    checked = ", ".join(_plural(n, labels[k]) for k, n in sorted(kinds.items())) or "nothing"
    summary = (f"{_plural(count(findings, ERROR), 'error')}, {_plural(count(findings, WARNING), 'warning')}"
               f" - checked {checked}")
    if lines:
        lines.append("")
    lines.append(summary)
    return "\n".join(lines)


def to_json(findings: List[Finding], targets: List[tuple], version: str) -> str:
    return json.dumps({
        "version": version,
        "summary": {
            "errors": count(findings, ERROR),
            "warnings": count(findings, WARNING),
            "info": count(findings, INFO),
            "targets": [{"kind": k, "path": display_path(p)} for k, p in targets],
        },
        "findings": [asdict(f) for f in sort_findings(findings)],
    }, indent=2, ensure_ascii=False)
