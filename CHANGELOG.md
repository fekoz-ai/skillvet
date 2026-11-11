# Changelog

## 0.1.0

First release.

- Skills: frontmatter, name and description rules from the Agent Skills spec, trigger and third-person checks, size limits, missing referenced files, nested skills.
- Subagents: required fields, model, enums, `bypassPermissions`, empty prompts, duplicate names.
- Hooks: valid JSON, event names with "did you mean" hints, handler types and required fields, timeouts, matchers, plain-http remote hooks.
- Secrets: common API key and token formats, private keys, hardcoded credentials (never printed in full).
- `--claude-hook` mode to run as a Claude Code `PostToolUse` hook.
- Text and JSON output, `--strict`, `--ignore`, inline `skillvet: ignore` markers.
