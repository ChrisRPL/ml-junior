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

- `/new`, `/open`, `/status`, `/handoff`, `/export`, `/doctor`

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

## Contributor Rules

- Keep CLI command metadata in sync with implemented behavior and required
  backend capability.
- New commands should share backend session, event, workflow, approval, and
  policy contracts rather than creating a separate agent runtime.
- Mark planned commands as unimplemented until their backend capability exists.
