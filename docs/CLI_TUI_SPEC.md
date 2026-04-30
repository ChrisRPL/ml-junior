# CLI And TUI Spec

read_when: changing CLI commands, slash-command metadata, command completion,
headless mode, local-mode execution, flow preview commands, or future TUI
layout.

Status: current-vs-target CLI contract. "Current behavior" means shipped in
this repository now. "Target behavior" is direction only.

## Current Behavior

- Installed CLI entrypoints are `ml-junior` and the compatibility alias
  `ml-intern`.
- Interactive CLI commands currently include `/help`, `/undo`, `/compact`,
  `/model [id]`, `/effort [level]`, `/yolo`, `/status`, `/quit`, `/exit`,
  `/flows`, and `/flow preview <id>`.
- `/flows` and `/flow preview <id>` are implemented read-only renderers backed
  by `backend.flow_templates`.
- Slash-command parsing and completions include implemented and planned command
  metadata: group, risk level, mutating/read-only status, aliases, and required
  backend capability.
- Planned commands registered for help/completion print a capability-required
  message instead of executing.
- `/doctor`, including `/doctor local-inference`, is planned only. It may appear
  in help/completion metadata, but it must not perform checks until the backend
  capability exists.
- Headless mode is `ml-junior "prompt text"` or `ml-intern "prompt text"`.
  Approval-gated tools stop the run and print pending approvals unless
  `--yolo` or `--auto-approve` is passed.
- CLI interactive and headless paths use local mode, so `bash`, `read`, `write`,
  and `edit` operate on the local filesystem under local guardrails.

Current limitations:

- There is no shipped multi-pane TUI.
- `ml-junior run <flow>` and `ml-junior project <command>` are target command
  families, not current entrypoints.
- `/flow start`, `/flow pause`, `/flow resume`, `/flow fork`, `/phase`,
  `/plan`, experiment commands, approval-center commands, evidence commands,
  code commands, and publish commands are planned only unless
  `docs/CURRENT_ARCHITECTURE.md` says otherwise.

## Target Behavior

The CLI should act as a terminal command center for ML projects with three
families:

- `ml-junior`: interactive TUI for live work.
- `ml-junior run <flow>`: scripted/headless flow execution.
- `ml-junior project <command>`: project and session management.

The future interactive TUI should show:

- Left or tabbed pane: project, selected flow, phase, blockers, and status.
- Center pane: conversation, summaries, decisions, and handoff notes.
- Right or tabbed pane: active tools, jobs, approvals, budgets, and artifacts.
- Bottom composer: slash-command input with fuzzy completion.

Slash-command completion should show command name, description, arguments, risk
level, mutating/read-only state, required backend capability, and shortcut when
available.

## Target Command Groups

Project commands:

- `/new`, `/open`, `/status`, `/handoff`, `/export`, `/doctor`,
  `/doctor local-inference`

Flow and planning commands:

- `/flows`, `/flow preview <id>`, `/flow start <id>`, `/flow pause`,
  `/flow resume`, `/flow fork`, `/phase`, `/plan`

Experiment and artifact commands:

- `/experiments`, `/runs`, `/run show <id>`, `/run compare <id> <id>`,
  `/run fork <id>`, `/metrics`, `/artifacts`

Tooling, approval, and policy commands:

- `/tools`, `/jobs`, `/approve`, `/deny`, `/permissions`, `/budget`

Context and evidence commands:

- `/evidence`, `/decisions`, `/assumptions`, `/compact`, `/memory`,
  `/ledger`, `/ledger verify`, `/proof bundle`

Code and publishing commands:

- `/diff`, `/test`, `/rollback`, `/commit`, `/pr`, `/package`

## Autonomy Model

Target autonomy levels should be explicit:

- `observe`: read-only state inspection.
- `assist`: propose plans and code; user executes.
- `edit`: edit files; ask before commands.
- `run`: run safe commands and experiments within budget.
- `publish`: publish only after explicit final approval.

## Local Inference Setup

Target local model ids use explicit local prefixes:

- `local/ollama/<model>` resolves to an OpenAI-compatible Ollama `/v1`
  endpoint. Default base URL is the local Ollama daemon
  (`http://localhost:11434/v1`) unless overridden by local inference config or
  environment.
- `local/llamacpp/<alias>` resolves to an OpenAI-compatible llama.cpp server
  `/v1` endpoint. Default base URL is a local llama.cpp server
  (`http://localhost:8080/v1`) unless overridden by local inference config or
  environment.

Setup contract:

- Users start and manage Ollama or llama.cpp themselves. The CLI must not start,
  install, update, or stop local inference daemons.
- Configuration should accept localhost, container-host aliases, and private IP
  addresses only. Public remote inference endpoints are provider endpoints, not
  local inference.
- The resolved endpoint uses a dummy local API key for OpenAI-compatible client
  wiring. It must not require or reuse remote provider credentials.
- Local setup docs and diagnostics must avoid printing full URLs with embedded
  credentials, local user paths, request bodies, or model prompts.

## `/doctor local-inference` Target Contract

`/doctor local-inference` is a planned read-only diagnostic command. Target
behavior:

- Resolve configured Ollama and llama.cpp base URLs for requested local model
  ids.
- Validate URL scheme, host class, and `/v1` compatibility shape without
  mutating config.
- Report provider kind, model alias, base URL host class, intended `/v1/models`
  probe URL, and remediation hints.
- Redact secrets, auth headers, token query parameters, local user paths,
  prompts, and response bodies in all terminal output, events, and logs.
- Classify daemon responses supplied by the caller/test harness, including
  success, connection refused, timeout, malformed JSON, incompatible schema, and
  model-not-found.

Non-goals for the command:

- No daemon startup, package installation, model pull/download, or config write.
- No remote/provider fallback when a local daemon is missing.
- No sandbox, HF, MCP, telemetry, or internet calls.

## Contributor Rules

- Keep CLI command metadata in sync with implemented behavior and required
  backend capability.
- New commands should share backend session, event, workflow, approval, and
  policy contracts rather than creating a separate agent runtime.
- Mark planned commands as unimplemented until their backend capability exists.
