"""Detect credentials pasted into skills, agents and hook configs.

Matched values are never printed in full: only a short masked preview.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

from ..report import ERROR, WARNING, Finding, display_path
from ..textutil import IGNORE_LINE, is_ignored_file, read_text

# (code, label, pattern, level)
KNOWN_TOKENS = [
    ("SV401", "Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), ERROR),
    ("SV401", "OpenAI API key", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{32,}"), ERROR),
    ("SV401", "AWS access key ID", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), ERROR),
    ("SV401", "GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{50,}"),
     ERROR),
    ("SV401", "Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), ERROR),
    ("SV401", "Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), ERROR),
    ("SV401", "Stripe live key", re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{20,}"), ERROR),
    ("SV401", "Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"), ERROR),
    ("SV402", "private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----"),
     ERROR),
]

GENERIC_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(api[_-]?key|secret(?:[_-]?key)?|access[_-]?token|auth[_-]?token|token|password|passwd|bearer)\b
    ["']?\s*[:=]\s*
    (?:bearer\s+)?["']([^"'\s]{16,})["']
    """)

PLACEHOLDER = re.compile(
    r"(?i)your|example|sample|dummy|placeholder|changeme|replace|redacted|fake|test|xxxx|\*\*\*|\.\.\.|<|>|\$\{|\$\(|"
    r"\{\{|%[A-Z_]+%|^\$[A-Z_]+$|^env:|process\.env|os\.environ")


def _mask(value: str) -> str:
    return f"{value[:6]}... ({len(value)} chars)"


def _looks_placeholder(value: str) -> bool:
    if PLACEHOLDER.search(value):
        return True
    return len(set(value)) < 6  # low-variety strings such as "aaaaaaaaaaaaaaaa"


def scan_file(path: Path) -> List[Finding]:
    try:
        text = read_text(path)
    except OSError:
        return []
    lines = text.splitlines()
    if is_ignored_file(lines):
        return []
    shown = display_path(path)
    findings: List[Finding] = []
    for n, line in enumerate(lines, start=1):
        if IGNORE_LINE in line:
            continue
        taken = []  # spans already reported on this line
        for code, label, rx, level in KNOWN_TOKENS:
            for m in rx.finditer(line):
                if any(s <= m.start() < e for s, e in taken) or _looks_placeholder(m.group(0)):
                    continue
                taken.append((m.start(), m.end()))
                if code == "SV402":
                    msg = "Private key committed in plain text. Remove it and rotate the key"
                else:
                    msg = (f"{label} committed in plain text: {_mask(m.group(0))}. "
                           "Revoke it and load it from an environment variable instead")
                findings.append(Finding(code, level, msg, shown, n))
        for m in GENERIC_ASSIGNMENT.finditer(line):
            value = m.group(2)
            if any(s <= m.start(2) < e for s, e in taken) or _looks_placeholder(value):
                continue
            findings.append(Finding(
                "SV403", WARNING,
                f"Possible hardcoded {m.group(1).lower()}: {_mask(value)}. Use an environment variable",
                shown, n))
    return findings
