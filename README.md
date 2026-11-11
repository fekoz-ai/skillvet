# skillvet

**Lint your Claude Code skills, subagents and hooks before they fail silently.**

A skill with a broken frontmatter loads without a description. A description with no trigger words is almost never picked. A hook event spelled `posttooluse` never fires. A subagent without a `description` is never delegated to. None of these show an error: Claude just quietly ignores your work.

`skillvet` catches them in one command, with no network access and no dependencies.

```console
$ skillvet .
.claude/agents/deployer.md:1  error    SV204  Missing 'description' (required): Claude uses it to decide when to delegate
.claude/agents/deployer.md:4  warning  SV208  permissionMode 'bypassPermissions' lets this subagent run every tool without asking; make sure that is intended
.claude/settings.json:3  warning  SV303  Unknown hook event 'posttooluse' (did you mean 'PostToolUse'?); it will never fire
.claude/settings.json:6  warning  SV309  Stop[0].hooks[0] sends hook data over plain http to a remote host; use https
.claude/skills/pdf-helper/SKILL.md:2  error    SV105  name 'PDF_Helper' must be kebab-case: lowercase letters, digits and single hyphens
.claude/skills/pdf-helper/SKILL.md:3  warning  SV111  description does not say WHEN to use the skill (e.g. 'Use when the user asks to...'); without triggers Claude rarely loads it
.claude/skills/pdf-helper/SKILL.md:3  warning  SV113  description should be written in third person ('Extracts tables from PDFs...'), not 'I can...' or 'You can...'
.claude/skills/pdf-helper/SKILL.md:9  error    SV118  References 'references/forms.md', which does not exist

3 errors, 12 warnings - checked 1 agent, 1 hooks file, 1 skill
```

(Shortened output from [`examples/bad`](examples/bad). Run `skillvet examples/good` to see a clean pass.)

## Install

```bash
pipx install skillvet        # or: pip install skillvet
uvx skillvet .               # run once without installing
```

Python 3.9+. No dependencies. Install `skillvet[yaml]` to validate frontmatter with PyYAML; without it, a built-in parser handles the YAML used in frontmatter.

## Use

```bash
skillvet                          # scan the current project
skillvet ~/.claude                # scan your personal skills, agents and settings
skillvet path/to/my-skill         # one skill folder
skillvet .claude/agents/x.md      # one subagent
skillvet --strict                 # fail on warnings too (good for CI)
skillvet --json                   # machine-readable output
skillvet --ignore SV107,SV112     # skip rules you disagree with
```

It finds skills (any folder with a `SKILL.md`), subagents (`agents/*.md`) and hook config (`.claude/settings.json`, `.claude/settings.local.json`, plugin `hooks/hooks.json`). It skips `node_modules`, `.git`, virtualenvs and build folders.

Exit codes: `0` clean, `1` errors found (or warnings with `--strict`), `2` path not found.

## Let Claude fix its own mistakes

Run skillvet as a Claude Code hook. Every time Claude writes or edits a skill, subagent or settings file, skillvet checks it and sends any errors straight back to Claude, which fixes them in the same turn.

Add this to `.claude/settings.json` (project) or `~/.claude/settings.json` (everywhere):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{ "type": "command", "command": "skillvet --claude-hook", "timeout": 30 }]
      }
    ]
  }
}
```

The hook stays silent for every other file and for warnings. It only speaks up on errors.

## Use in CI

GitHub Actions:

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
- run: pipx run skillvet --strict
```

[pre-commit](https://pre-commit.com):

```yaml
repos:
  - repo: https://github.com/fekoz-ai/skillvet
    rev: v0.1.0
    hooks:
      - id: skillvet
```

## What it checks

**Errors** break loading, uploading or security. **Warnings** make a skill trigger badly, waste context or go against the documented guidance. **Info** findings only appear with `--verbose`.

### Skills

| Code | Level | Check |
|---|---|---|
| SV101 | error | `SKILL.md` is missing |
| SV102 | error | No YAML frontmatter |
| SV103 | error | Frontmatter is not valid YAML |
| SV104 | error | `name` is missing |
| SV105 | error | `name` is not kebab-case or is longer than 64 characters |
| SV106 | error | `name` contains the reserved words `claude` or `anthropic` |
| SV107 | warning | `name` differs from the folder name |
| SV108 | error | `description` is missing |
| SV109 | error | `description` is longer than 1,024 characters |
| SV110 | error | `description` contains XML/HTML tags |
| SV111 | warning | `description` never says when to use the skill |
| SV112 | warning | `description` is too short to trigger reliably |
| SV113 | warning | `description` is not in third person |
| SV114 | warning | Unknown frontmatter key |
| SV115 | info | Claude Code-only keys that claude.ai uploads reject |
| SV116 | warning | `SKILL.md` is longer than 500 lines |
| SV117 | warning | Reference file over 100 lines without a table of contents |
| SV118 | error / warning | Links to a file that does not exist (error in `SKILL.md`, warning elsewhere) |
| SV119 | warning | Nested `SKILL.md` inside another skill |
| SV120 | warning | Too many all-caps MUST / NEVER / ALWAYS |
| SV121 | warning | `description` + `when_to_use` longer than 1,536 characters (Claude Code truncates them) |
| SV122 | warning | Frontmatter that Claude Code tolerates but strict YAML rejects (usually an unquoted `: `) |

### Subagents

| Code | Level | Check |
|---|---|---|
| SV201 | error | Missing or invalid frontmatter |
| SV202 | error | `name` is missing |
| SV203 | error | `name` is not lowercase with hyphens |
| SV204 | error | `description` is missing |
| SV205 | warning | `model` is not a known alias or a `claude-` model ID |
| SV206 | warning | Unknown frontmatter key |
| SV207 | warning | Invalid `permissionMode`, `effort`, `color`, `memory`, `isolation` or `maxTurns` |
| SV208 | warning | `permissionMode: bypassPermissions` |
| SV209 | error | `tools` is not a string or a list |
| SV210 | warning | Empty system prompt |
| SV211 | warning | `description` is too short to delegate well |
| SV212 | error | Two subagents with the same `name` |
| SV213 | warning | Frontmatter that Claude Code tolerates but strict YAML rejects |

### Hooks

| Code | Level | Check |
|---|---|---|
| SV301 | error | Invalid JSON (Claude Code ignores the whole file) |
| SV302 | error | `hooks` is not an object |
| SV303 | warning | Unknown event name, with a "did you mean" hint |
| SV304 | error | Event value is not a list |
| SV305 | error | Matcher group with no `hooks` list |
| SV306 | error / warning | Hook without a `type`, or with an unknown one |
| SV307 | error | `command` / `prompt` / `url` missing for its hook type |
| SV308 | warning | `timeout` is not a positive number |
| SV309 | warning | `http` hook sending data to a remote host over plain http |
| SV310 | error / warning | `matcher` is not a string or not a valid pattern |

### Secrets (all scanned files)

| Code | Level | Check |
|---|---|---|
| SV401 | error | API keys and tokens: Anthropic, OpenAI, AWS, GitHub, Slack, Google, Stripe live keys, Hugging Face |
| SV402 | error | Private key blocks |
| SV403 | warning | Hardcoded `api_key = "..."` / `password: "..."` style values |

Secrets are never printed in full, only the first 6 characters. Obvious placeholders (`your-api-key`, `${API_KEY}`, `xxxx`, `<token>`) are ignored.

## Silencing a finding

- One line: add `skillvet: ignore` anywhere on it, for example `<!-- skillvet: ignore -->` in Markdown.
- A whole file: put `skillvet: ignore-file` in its first 5 lines.
- A rule everywhere: `--ignore SV113`.
- Code blocks in Markdown are never checked for missing files, so templates and examples are safe.

## Privacy

skillvet only reads files. It never modifies them, never makes network requests and never sends anything anywhere.

## Contributing

Issues and pull requests are welcome, especially false positives: include the snippet that triggered it.

```bash
git clone https://github.com/fekoz-ai/skillvet && cd skillvet
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

## License

MIT. Made by [Fekoz Studio](https://fekozstudio.com).

skillvet is an independent project and is not affiliated with or endorsed by Anthropic. Claude and Claude Code are trademarks of Anthropic.
