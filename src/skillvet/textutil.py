"""Small helpers shared by the checks: file reading, frontmatter parsing, ignore markers."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

try:  # PyYAML is optional; the built-in parser covers normal frontmatter
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - exercised via monkeypatch in tests
    yaml = None

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
             "dist", "build", ".next", ".nuxt", ".cache", "target", "vendor", "site-packages"}
TEXT_SUFFIXES = {".md", ".txt", ".py", ".sh", ".ps1", ".js", ".mjs", ".cjs", ".ts", ".json", ".yaml", ".yml",
                 ".toml", ".html", ".htm", ".csv", ".env", ".ini", ".cfg"}
MAX_TEXT_BYTES = 2_000_000

IGNORE_LINE = "skillvet: ignore"
IGNORE_FILE = "skillvet: ignore-file"


class FrontmatterError(ValueError):
    pass


def read_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.lstrip("﻿")


def is_ignored_file(lines: List[str]) -> bool:
    return any(IGNORE_FILE in ln for ln in lines[:5])


def iter_files(root: Path, prune: frozenset = frozenset()) -> Iterator[Path]:
    """Yield files under root in sorted order, never descending into SKIP_DIRS or `prune` names."""
    skip = SKIP_DIRS | set(prune)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        base = Path(dirpath)
        for name in sorted(filenames):
            yield base / name


def is_text_file(path: Path) -> bool:
    name = path.name.lower()
    return (path.suffix.lower() in TEXT_SUFFIXES or name.startswith(".env")) and path.stat().st_size <= MAX_TEXT_BYTES


def code_block_flags(lines: List[str]) -> List[bool]:
    """True for every line inside (or delimiting) a fenced code block."""
    flags, inside, fence = [], False, ""
    for ln in lines:
        marker = ln.lstrip()[:3]
        if marker in ("```", "~~~") and (not inside or marker == fence):
            flags.append(True)
            inside = not inside
            fence = marker if inside else ""
            continue
        flags.append(inside)
    return flags


def split_frontmatter(text: str) -> Tuple[Optional[str], str, int]:
    """Return (raw_yaml or None, body, body_start_line). Lines are 1-based."""
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    if not m:
        m2 = re.match(r"^---[ \t]*\r?\n---[ \t]*(?:\r?\n|$)", text)  # empty frontmatter
        if m2:
            return "", text[m2.end():], 3
        return None, text, 1
    body_start = text[:m.end()].count("\n") + 1
    return m.group(1), text[m.end():], body_start


def parse_yaml(raw: str) -> dict:
    """Parse frontmatter YAML into a dict. Raises FrontmatterError on invalid input."""
    if raw.strip() == "":
        return {}
    if yaml is not None:
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            first = str(exc).splitlines()[0] if str(exc) else "invalid YAML"
            raise FrontmatterError(first) from None
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise FrontmatterError("frontmatter must be a YAML mapping (key: value pairs)")
        return data
    return _mini_yaml(raw)


def parse_yaml_lenient(raw: str) -> dict:
    """Parse the way Claude Code tolerates: unquoted ': ' inside a plain value is kept as text."""
    return _mini_yaml(raw, lenient=True)


_KEY_RE = re.compile(r"^([A-Za-z0-9_][\w.-]*)\s*:(?:\s+(.*)|\s*)$")


def _scalar(value: str):
    v = value.strip()
    if not v:
        return ""
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        return inner.replace("''", "'") if v[0] == "'" else inner.replace('\\"', '"')
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_scalar(x) for x in inner.split(",")] if inner else []
    v = re.sub(r"\s+#.*$", "", v)  # trailing comment
    low = v.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def _mini_yaml(raw: str, lenient: bool = False) -> dict:
    """Minimal YAML subset parser used when PyYAML is not installed.

    Supports key: value, quoted strings, inline lists, block scalars (| and >),
    indented lists, one level of nested mappings, and comments.
    """
    lines = raw.splitlines()
    data: dict = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line[0] in " \t":
            raise FrontmatterError(f"unexpected indentation on frontmatter line {i + 1}")
        m = _KEY_RE.match(line)
        if not m:
            raise FrontmatterError(f"cannot parse frontmatter line {i + 1}: {line.strip()[:60]!r}")
        key, value = m.group(1), (m.group(2) or "").strip()
        if key in data:
            raise FrontmatterError(f"duplicate key '{key}'")
        j = i + 1
        block = []
        while j < len(lines) and (not lines[j].strip() or lines[j][0] in " \t"):
            block.append(lines[j])
            j += 1
        while block and not block[-1].strip():
            block.pop()
        if value[:1] in ("|", ">"):
            texts = [b.strip() for b in block]
            data[key] = "\n".join(texts) if value[0] == "|" else " ".join(t for t in texts if t)
        elif value == "":
            items = [b.strip() for b in block if b.strip() and not b.strip().startswith("#")]
            if items and all(x.startswith("- ") or x == "-" for x in items):
                data[key] = [_scalar(x[1:]) for x in items]
            elif items:
                nested = {}
                for x in items:
                    mm = _KEY_RE.match(x)
                    if not mm:
                        raise FrontmatterError(f"cannot parse nested value under '{key}': {x[:60]!r}")
                    nested[mm.group(1)] = _scalar(mm.group(2) or "")
                data[key] = nested
            else:
                data[key] = None
        else:
            if block:  # plain multi-line scalar
                value = " ".join([value] + [b.strip() for b in block if b.strip()])
            for opener, closer in (('"', '"'), ("'", "'"), ("[", "]"), ("{", "}")):
                if value.startswith(opener) and not (len(value) >= 2 and value.endswith(closer)):
                    raise FrontmatterError(f"unterminated {opener}...{closer} value for '{key}'")
            if not lenient and value[:1] not in ("\"", "'", "[", "{") and re.search(r":\s", value):
                raise FrontmatterError(f"unquoted ': ' inside the value of '{key}' (wrap the value in quotes)")
            data[key] = _scalar(value)
        i = j
    return data


def key_line(text: str, key: str) -> Optional[int]:
    """1-based line number where a top-level frontmatter key is defined."""
    for n, ln in enumerate(text.splitlines()[:300], start=1):
        if re.match(rf"^{re.escape(key)}\s*:", ln):
            return n
    return None
