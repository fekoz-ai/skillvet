import json
import textwrap
from pathlib import Path

import pytest

from skillvet import cli, textutil
from skillvet.checks.agent import check_agent
from skillvet.checks.hooks import check_hooks
from skillvet.checks.secrets import scan_file
from skillvet.checks.skill import check_skill

GOOD_DESC = ("Extracts tables and form fields from PDF files and converts them to CSV. "
             "Use when the user asks to read, parse or export data from a PDF.")


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return path


def make_skill(tmp_path, name="pdf-tables", desc=GOOD_DESC, body="# PDF tables\n\nSteps here.\n", extra=""):
    root = tmp_path / name
    write(root / "SKILL.md", f"---\nname: {name}\ndescription: {desc}\n{extra}---\n\n{body}")
    return root


def codes(findings):
    return sorted(f.code for f in findings)


# Fake credentials are assembled at runtime so the repository never contains a token-shaped string.
def fake_anthropic():
    return "sk-" + "ant-" + "api03-" + "Q7v" * 12


def fake_github():
    return "gh" + "p_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"


def fake_aws():
    return "AK" + "IA" + "Q4Z7W2N8R5T1Y6U3"


# --------------------------------------------------------------------------- skills
def test_good_skill_is_clean(tmp_path):
    root = make_skill(tmp_path)
    write(root / "references" / "api.md", "# API\n")
    root_md = root / "SKILL.md"
    root_md.write_text(root_md.read_text(encoding="utf-8") + "See [the API notes](references/api.md).\n",
                       encoding="utf-8")
    assert [f for f in check_skill(root) if f.level != "info"] == []


def test_missing_skill_md(tmp_path):
    (tmp_path / "empty").mkdir()
    assert codes(check_skill(tmp_path / "empty")) == ["SV101"]


def test_missing_frontmatter(tmp_path):
    root = tmp_path / "x"
    write(root / "SKILL.md", "# Just a title\n")
    assert codes(check_skill(root)) == ["SV102"]


def _yaml_mode(monkeypatch, with_pyyaml):
    if with_pyyaml:
        pytest.importorskip("yaml")
    else:
        monkeypatch.setattr(textutil, "yaml", None)


@pytest.mark.parametrize("with_pyyaml", [True, False])
@pytest.mark.parametrize("bad_line", [
    "description: [unclosed",
    'description: "unclosed quote',
    "- a stray list item",
])
def test_invalid_yaml(tmp_path, monkeypatch, with_pyyaml, bad_line):
    _yaml_mode(monkeypatch, with_pyyaml)
    root = tmp_path / "bad-yaml"
    write(root / "SKILL.md", f"---\nname: bad-yaml\n{bad_line}\n---\nbody\n")
    assert "SV103" in codes(check_skill(root))


@pytest.mark.parametrize("with_pyyaml", [True, False])
def test_unquoted_colon_is_a_warning_not_an_error(tmp_path, monkeypatch, with_pyyaml):
    """Claude Code tolerates 'description: a: b'; strict YAML (claude.ai upload) does not."""
    _yaml_mode(monkeypatch, with_pyyaml)
    root = make_skill(tmp_path, desc="Load tests an API before launch. Use when the user says: run a load test.")
    found = check_skill(root)
    assert "SV122" in codes(found) and "SV103" not in codes(found)
    assert "SV108" not in codes(found)  # description was still read


@pytest.mark.parametrize("name,code", [
    ("PDF_Tools", "SV105"),
    ("double--hyphen", "SV105"),
    ("claude-helper", "SV106"),
    ("my-anthropic-skill", "SV106"),
])
def test_bad_names(tmp_path, name, code):
    root = make_skill(tmp_path, name=name)
    assert code in codes(check_skill(root))


def test_name_too_long(tmp_path):
    name = "a" * 65
    root = make_skill(tmp_path, name=name)
    assert "SV105" in codes(check_skill(root))


def test_name_folder_mismatch(tmp_path):
    root = tmp_path / "folder-name"
    write(root / "SKILL.md", f"---\nname: other-name\ndescription: {GOOD_DESC}\n---\nbody\n")
    assert "SV107" in codes(check_skill(root))


def test_missing_name_and_description(tmp_path):
    root = tmp_path / "s"
    write(root / "SKILL.md", "---\nlicense: MIT\n---\nbody\n")
    c = codes(check_skill(root))
    assert "SV104" in c and "SV108" in c


def test_description_too_long(tmp_path):
    root = make_skill(tmp_path, desc="Use when parsing. " + "word " * 220)
    assert "SV109" in codes(check_skill(root))


def test_description_with_xml_tags(tmp_path):
    root = make_skill(tmp_path, desc='"Use when the user sends <file> tags to parse PDFs and export the tables as CSV."')
    assert "SV110" in codes(check_skill(root))


def test_description_without_trigger(tmp_path):
    root = make_skill(tmp_path, desc="Extracts tables and form fields from PDF documents and converts them to tidy "
                                     "CSV files with typed columns.")
    assert "SV111" in codes(check_skill(root))


def test_description_too_short(tmp_path):
    root = make_skill(tmp_path, desc="Use when parsing PDFs.")
    assert "SV112" in codes(check_skill(root))


def test_description_first_person(tmp_path):
    root = make_skill(tmp_path, desc="I can extract tables from PDF files for you. Use when the user asks to parse "
                                     "a PDF or export its tables.")
    assert "SV113" in codes(check_skill(root))


def test_io_prefix_is_not_first_person(tmp_path):
    root = make_skill(tmp_path, desc="I/O helpers that read and write Parquet and CSV files. Use when the user asks "
                                     "to convert between tabular formats.")
    assert "SV113" not in codes(check_skill(root))


def test_unknown_and_claude_code_keys(tmp_path):
    root = make_skill(tmp_path, extra="version: 1.0\nmodel: sonnet\n")
    found = check_skill(root)
    assert "SV114" in codes(found)
    sv115 = [f for f in found if f.code == "SV115"]
    assert sv115 and sv115[0].level == "info"


def test_long_skill_md(tmp_path):
    root = make_skill(tmp_path, body="line\n" * 520)
    assert "SV116" in codes(check_skill(root))


def test_long_reference_without_toc(tmp_path):
    root = make_skill(tmp_path)
    write(root / "references" / "big.md", "# Big\n" + "text\n" * 150)
    assert "SV117" in codes(check_skill(root))


def test_long_reference_with_toc_is_fine(tmp_path):
    root = make_skill(tmp_path)
    write(root / "references" / "big.md", "# Big\n\n## Contents\n- [Intro](#intro)\n" + "text\n" * 150)
    assert "SV117" not in codes(check_skill(root))


def test_missing_reference(tmp_path):
    root = make_skill(tmp_path, body="Read references/forms.md first, then run scripts/fill.py.\n")
    found = [f for f in check_skill(root) if f.code == "SV118"]
    assert {f.message.split("'")[1] for f in found} == {"references/forms.md", "scripts/fill.py"}
    assert all(f.line for f in found)


def test_missing_markdown_link(tmp_path):
    root = make_skill(tmp_path, body="See [guide](GUIDE.md) and [site](https://example.com) and [top](#top).\n")
    found = [f for f in check_skill(root) if f.code == "SV118"]
    assert len(found) == 1 and "GUIDE.md" in found[0].message


def test_missing_reference_outside_skill_md_is_a_warning(tmp_path):
    root = make_skill(tmp_path)
    write(root / "references" / "guide.md", "Then run scripts/missing.py.\n")
    found = [f for f in check_skill(root) if f.code == "SV118"]
    assert len(found) == 1 and found[0].level == "warning"


@pytest.mark.parametrize("body", [
    "Create evals/evals.json with three test prompts.\n",
    "Outputs are saved to assets/out.png when done.\n",
    "Use a path template such as references/topic.md for new notes.\n",
    "Run SKILL_DIR/scripts/init.py to start.\n",
    "If the skill already has an `evals/evals.json`, keep it.\n",
])
def test_reference_false_positives(tmp_path, body):
    root = make_skill(tmp_path, body=body)
    assert "SV118" not in codes(check_skill(root))


def test_history_files_are_not_checked(tmp_path):
    root = make_skill(tmp_path)
    write(root / "CHANGELOG.md", "Removed scripts/old.py\n")
    write(root / "TEST_RESULTS.md", "Ran scripts/gone.py\n")
    assert "SV118" not in codes(check_skill(root))


def test_spanish_description_has_triggers(tmp_path):
    root = make_skill(tmp_path, desc="Prepara presupuestos con tres opciones y desglose de impuestos. Úsala cuando "
                                     "el usuario pida un precio o un presupuesto.")
    assert "SV111" not in codes(check_skill(root))


def test_agent_templates_and_readmes_are_skipped(tmp_path):
    write(tmp_path / ".claude" / "agents" / "README.md", "# Agents\n")
    write(tmp_path / ".claude" / "agents" / "DESIGN.template.md", "fill me\n")
    write(tmp_path / ".claude" / "agents" / "_draft.md", "draft\n")
    assert cli.discover(tmp_path) == []


def test_references_inside_code_blocks_are_ignored(tmp_path):
    root = make_skill(tmp_path, body="```\npython scripts/template.py\n```\n")
    assert "SV118" not in codes(check_skill(root))


def test_ignore_marker(tmp_path):
    root = make_skill(tmp_path, body="Optional: references/later.md  <!-- skillvet: ignore -->\n")
    assert "SV118" not in codes(check_skill(root))


def test_nested_skill_md(tmp_path):
    root = make_skill(tmp_path)
    write(root / "sub" / "SKILL.md", "---\nname: sub\n---\n")
    assert "SV119" in codes(check_skill(root))


def test_shouting(tmp_path):
    root = make_skill(tmp_path, body="You MUST do this. NEVER that. ALWAYS this. CRITICAL. IMPORTANT. MUST again.\n")
    assert "SV120" in codes(check_skill(root))


def test_folded_description_parses(tmp_path):
    root = tmp_path / "folded"
    write(root / "SKILL.md", f"---\nname: folded\ndescription: >\n  {GOOD_DESC[:80]}\n  {GOOD_DESC[80:]}\n---\nb\n")
    assert [f for f in check_skill(root) if f.level == "error"] == []


# --------------------------------------------------------------------------- mini YAML parser (no PyYAML)
def test_mini_yaml_parser(monkeypatch):
    monkeypatch.setattr(textutil, "yaml", None)
    data = textutil.parse_yaml(textwrap.dedent("""
        name: my-skill
        description: "Quoted: with colon"
        allowed-tools: [Read, Grep]
        metadata:
          author: someone
          version: 2
        notes: |
          line one
          line two
        tags:
          - a
          - b
        flag: true
    """))
    assert data["name"] == "my-skill"
    assert data["description"] == "Quoted: with colon"
    assert data["allowed-tools"] == ["Read", "Grep"]
    assert data["metadata"] == {"author": "someone", "version": 2}
    assert data["notes"] == "line one\nline two"
    assert data["tags"] == ["a", "b"]
    assert data["flag"] is True


def test_mini_yaml_rejects_garbage(monkeypatch):
    monkeypatch.setattr(textutil, "yaml", None)
    with pytest.raises(textutil.FrontmatterError):
        textutil.parse_yaml("this is not yaml at all")
    with pytest.raises(textutil.FrontmatterError):
        textutil.parse_yaml("name: a\nname: b")


def test_skill_check_without_pyyaml(tmp_path, monkeypatch):
    monkeypatch.setattr(textutil, "yaml", None)
    root = make_skill(tmp_path)
    assert [f for f in check_skill(root) if f.level != "info"] == []


# --------------------------------------------------------------------------- agents
GOOD_AGENT = """
---
name: code-reviewer
description: Reviews diffs for bugs and security issues. Use after code changes, before committing.
tools: Read, Grep, Glob
model: sonnet
---

You are a careful code reviewer.
"""


def test_good_agent(tmp_path):
    p = write(tmp_path / "agents" / "code-reviewer.md", GOOD_AGENT)
    assert check_agent(p) == []


def test_agent_full_model_id_ok(tmp_path):
    p = write(tmp_path / "agents" / "a.md", GOOD_AGENT.replace("model: sonnet", "model: claude-opus-5-5"))
    assert check_agent(p) == []


def test_agent_problems(tmp_path):
    p = write(tmp_path / "agents" / "bad.md", """
        ---
        name: Bad Agent
        description: Helps.
        model: gpt-4
        permissionMode: bypassPermissions
        color: magenta
        temperature: 0.2
        maxTurns: 0
        ---
    """)
    c = codes(check_agent(p))
    for expected in ("SV203", "SV205", "SV206", "SV207", "SV208", "SV210", "SV211"):
        assert expected in c, expected


def test_agent_missing_required(tmp_path):
    p = write(tmp_path / "agents" / "x.md", "---\ntools: Read\n---\nprompt\n")
    c = codes(check_agent(p))
    assert "SV202" in c and "SV204" in c


def test_agent_without_frontmatter(tmp_path):
    p = write(tmp_path / "agents" / "x.md", "just text\n")
    assert codes(check_agent(p)) == ["SV201"]


def test_agent_list_valued_enum_does_not_crash(tmp_path):
    p = write(tmp_path / "agents" / "x.md", GOOD_AGENT.replace("model: sonnet", "color: [red, blue]"))
    assert "SV207" in codes(check_agent(p))


def test_duplicate_agent_names(tmp_path):
    write(tmp_path / ".claude" / "agents" / "a.md", GOOD_AGENT)
    write(tmp_path / ".claude" / "agents" / "b.md", GOOD_AGENT)
    findings = cli.run(cli.discover(tmp_path))
    assert "SV212" in codes(findings)


# --------------------------------------------------------------------------- hooks
def hooks_file(tmp_path, hooks, name="settings.json"):
    return write(tmp_path / ".claude" / name, json.dumps({"hooks": hooks}, indent=2))


def test_good_hooks(tmp_path):
    p = hooks_file(tmp_path, {
        "PreToolUse": [{"matcher": "Bash|Write", "hooks": [{"type": "command", "command": "./check.sh", "timeout": 30}]}],
        "Stop": [{"hooks": [{"type": "prompt", "prompt": "Did the task finish?"}]}],
        "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "http", "url": "http://localhost:8080/h"}]}],
    })
    assert check_hooks(p) == []


def test_settings_without_hooks(tmp_path):
    p = write(tmp_path / ".claude" / "settings.json", json.dumps({"permissions": {"allow": []}}))
    assert check_hooks(p) == []


def test_invalid_json(tmp_path):
    p = write(tmp_path / ".claude" / "settings.json", '{"hooks": {,}}')
    f = check_hooks(p)
    assert codes(f) == ["SV301"] and f[0].line == 1


def test_hook_problems(tmp_path):
    p = hooks_file(tmp_path, {
        "preToolUse": [],
        "Stop": {"hooks": []},
        "PostToolUse": [
            {"matcher": "Edit"},
            {"matcher": "([", "hooks": [{"type": "command"}]},
            {"hooks": [{"command": "x"}, {"type": "webhook"}, {"type": ["command"]},
                       {"type": "command", "command": "x", "timeout": -1},
                       {"type": "http", "url": "http://example.org/hook"}]},
        ],
    })
    found = check_hooks(p)
    c = codes(found)
    for expected in ("SV303", "SV304", "SV305", "SV306", "SV307", "SV308", "SV309", "SV310"):
        assert expected in c, expected
    assert any("did you mean 'PreToolUse'" in f.message for f in found)


def test_plugin_hooks_json_without_wrapper(tmp_path):
    p = write(tmp_path / "hooks" / "hooks.json", json.dumps(
        {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "x"}]}]}))
    assert check_hooks(p) == []


# --------------------------------------------------------------------------- secrets
def test_detects_known_tokens(tmp_path):
    p = write(tmp_path / "notes.md", f"key: {fake_anthropic()}\ntoken {fake_github()}\naws {fake_aws()}\n")
    found = scan_file(p)
    assert codes(found) == ["SV401", "SV401", "SV401"]
    for f in found:  # never print the full secret
        assert fake_anthropic() not in f.message and fake_github() not in f.message


def test_private_key(tmp_path):
    p = write(tmp_path / "k.md", "-----BEGIN " + "PRIVATE KEY-----\nabc\n")
    assert codes(scan_file(p)) == ["SV402"]


def test_generic_assignment(tmp_path):
    p = write(tmp_path / "c.py", 'API_KEY = "q8Lr2Vx9Tz4Kp7Wm3Ns6"\n')
    assert codes(scan_file(p)) == ["SV403"]


@pytest.mark.parametrize("line", [
    'API_KEY = "your-api-key-goes-here"',
    'api_key = "${ANTHROPIC_API_KEY}"',
    'token: "xxxxxxxxxxxxxxxxxxxxxxxx"',
    'password = "<your password here>"',
    "export ANTHROPIC_API_KEY=sk-ant-...",
    'password = "aaaaaaaaaaaaaaaaaaaa"',
])
def test_placeholders_are_not_secrets(tmp_path, line):
    p = write(tmp_path / "c.md", line + "\n")
    assert scan_file(p) == []


def test_secret_ignore_marker(tmp_path):
    p = write(tmp_path / "c.md", f"{fake_anthropic()}  skillvet: ignore\n")
    assert scan_file(p) == []


def test_secret_in_skill_is_reported_via_cli(tmp_path, capsys):
    root = make_skill(tmp_path)
    write(root / "scripts" / "run.py", f'KEY = "{fake_anthropic()}"\n')
    assert cli.main([str(root), "--no-color"]) == 1
    out = capsys.readouterr().out
    assert "SV401" in out and fake_anthropic() not in out


# --------------------------------------------------------------------------- discovery and CLI
def test_discover_project(tmp_path):
    make_skill(tmp_path / ".claude" / "skills")
    write(tmp_path / ".claude" / "skills" / "pdf-tables" / "agents" / "helper.md", "not an agent\n")
    write(tmp_path / ".claude" / "agents" / "rev.md", GOOD_AGENT)
    write(tmp_path / ".claude" / "settings.json", "{}")
    write(tmp_path / "node_modules" / "x" / "SKILL.md", "---\n---\n")
    kinds = sorted(k for k, _ in cli.discover(tmp_path))
    assert kinds == ["agent", "hooks", "skill"]


def test_cli_exit_codes(tmp_path, capsys):
    good = make_skill(tmp_path)
    assert cli.main([str(good)]) == 0
    bad = make_skill(tmp_path, name="Bad_Name")
    assert cli.main([str(bad)]) == 1
    warn = make_skill(tmp_path, name="warn-only", desc="Use when parsing PDFs.")
    assert cli.main([str(warn)]) == 0
    assert cli.main([str(warn), "--strict"]) == 1
    assert cli.main([str(warn), "--strict", "--ignore", "SV112"]) == 0
    assert cli.main([str(tmp_path / "nope")]) == 2
    capsys.readouterr()


def test_cli_json_output(tmp_path, capsys):
    root = make_skill(tmp_path, name="Bad_Name")
    cli.main([str(root), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["errors"] >= 1
    assert {"code", "level", "message", "path", "line"} <= set(data["findings"][0])


def test_cli_nothing_found(tmp_path, capsys):
    assert cli.main([str(tmp_path)]) == 0
    assert "No skills" in capsys.readouterr().out


def test_claude_hook_mode(tmp_path, monkeypatch, capsys):
    import io
    bad = make_skill(tmp_path, name="Bad_Name")
    event = {"tool_name": "Write", "tool_input": {"file_path": str(bad / "SKILL.md")}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    assert cli.main(["--claude-hook"]) == 2
    assert "SV105" in capsys.readouterr().err

    good = make_skill(tmp_path)
    event["tool_input"]["file_path"] = str(good / "SKILL.md")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    assert cli.main(["--claude-hook"]) == 0

    for payload in ("not json", "[]", '{"tool_input": "x"}', '{"tool_input": {"file_path": "/nowhere/file.py"}}'):
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        assert cli.main(["--claude-hook"]) == 0


def test_examples_folder_matches_readme():
    """The bundled examples must keep producing what the README shows."""
    examples = Path(__file__).resolve().parent.parent / "examples"
    good = cli.run(cli.discover(examples / "good"))
    assert [f for f in good if f.level != "info"] == []
    bad = cli.run(cli.discover(examples / "bad"))
    assert any(f.level == "error" for f in bad)
