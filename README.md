<p align="center">
  <img src="frontend/public/terminal-cap/logo-terminal-cap-wordmark.svg" alt="ML Junior Terminal Cap wordmark" width="420" />
</p>

# ML Junior

ML Junior is an agentic ML engineering workspace for researching, planning,
implementing, and verifying machine-learning work with the Hugging Face
ecosystem. It combines a Python async agent runtime, a CLI, a FastAPI backend,
and a Vite/React browser shell with access to docs, papers, datasets,
repositories, Jobs, and local or sandboxed execution.

This repository is being rebranded from the upstream `ml-intern` lineage.
Use `ml-junior` for new local workflows. The legacy `ml-intern` command remains
available and points at the same safe CLI entrypoint for compatibility with
existing scripts, docs, and upstream habits.

Terminal Cap is the current visual direction for ML Junior. The tracked assets
live in `frontend/public/terminal-cap/`, including the mark, wordmark, banner,
and empty-state illustrations. Treat those assets as branding direction in
progress, not a claim that every product surface is complete.

## Quick Start

### Installation

```bash
git clone <repo-url> ml-junior
cd ml-junior
uv sync
uv tool install -e .
```

If you are cloning from an upstream Hugging Face remote, the repository URL or
checkout directory may still contain `ml-intern`. That is expected during the
transition; the installed CLI scripts remain compatible.

After installation, both commands launch the same CLI:

```bash
ml-junior
ml-intern
```

Create a `.env` file in the project root, or export these in your shell:

```bash
ANTHROPIC_API_KEY=<your-anthropic-api-key> # if using Anthropic models
HF_TOKEN=<your-hugging-face-token>
GITHUB_TOKEN=<github-personal-access-token>
```

If no `HF_TOKEN` is set, the CLI prompts you to paste one on first launch.
To create a `GITHUB_TOKEN`, follow GitHub's
[personal access token docs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token).

## Usage

Interactive mode starts a chat session:

```bash
ml-junior
```

Headless mode runs one prompt:

```bash
ml-junior "fine-tune llama on my dataset"
```

Common options:

```bash
ml-junior --model anthropic/claude-opus-4-6 "your prompt"
ml-junior --max-iterations 100 "your prompt"
ml-junior --no-stream "your prompt"
```

Compatibility: replace `ml-junior` with `ml-intern` in any command above when
an existing workflow depends on the upstream name. Both scripts resolve to
`agent.main:cli`.

## Current Shape

- Python async agent runtime with queue-driven turns and tool calls.
- FastAPI backend with session APIs and server-sent event streaming.
- Vite/React frontend for the browser experience.
- Tool surface for Hugging Face docs, papers, datasets, repositories, Jobs,
  GitHub examples, planning, local execution, and sandbox execution.
- Guardrails around approvals, redaction, local writes, sandbox actions, and
  network-dependent work.

Some internal package names, comments, and compatibility paths may still use
upstream `ml-intern` or older Hugging Face agent naming. Keep those names when
they preserve compatibility; prefer ML Junior naming for new user-facing copy.

## Architecture

### Component Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                         User/CLI                            │
└────────────┬─────────────────────────────────────┬──────────┘
             │ Operations                          │ Events
             ↓ (user_input, exec_approval,         ↑
      submission_queue  interrupt, compact, ...)  event_queue
             │                                          │
             ↓                                          │
┌────────────────────────────────────────────────────┐  │
│            submission_loop (agent_loop.py)         │  │
│  ┌──────────────────────────────────────────────┐  │  │
│  │  1. Receive Operation from queue             │  │  │
│  │  2. Route to handler (run_agent/compact/...) │  │  │
│  └──────────────────────────────────────────────┘  │  │
│                      ↓                             │  │
│  ┌──────────────────────────────────────────────┐  │  │
│  │         Handlers.run_agent()                 │  ├──┤
│  │                                              │  │  │
│  │  ┌────────────────────────────────────────┐  │  │  │
│  │  │  Agentic Loop                         │  │  │  │
│  │  │                                        │  │  │  │
│  │  │  ┌──────────────────────────────────┐  │  │  │  │
│  │  │  │ Session                          │  │  │  │  │
│  │  │  │  ├─ ContextManager               │  │  │  │  │
│  │  │  │  ├─ ToolRouter                   │  │  │  │  │
│  │  │  │  └─ Doom loop detector           │  │  │  │  │
│  │  │  └──────────────────────────────────┘  │  │  │  │
│  │  └────────────────────────────────────────┘  │  │  │
│  └──────────────────────────────────────────────┘  │  │
└────────────────────────────────────────────────────┴──┘
```

### Agentic Loop Flow

```text
User message
     ↓
Add to ContextManager
     ↓
Iteration loop
     ↓
LLM call
     ↓
Parse tool calls
     ↓
Approval check
     ↓
Execute via ToolRouter
     ↓
Add results to ContextManager
     ↓
Repeat until done
```

## Events

The agent emits events via `event_queue`:

- `processing` - Starting to process user input
- `ready` - Agent is ready for input
- `assistant_chunk` - Streaming token chunk
- `assistant_message` - Complete LLM response text
- `assistant_stream_end` - Token stream finished
- `tool_call` - Tool being called with arguments
- `tool_output` - Tool execution result
- `tool_log` - Informational tool log message
- `tool_state_change` - Tool execution state transition
- `approval_required` - Requesting user approval for sensitive operations
- `turn_complete` - Agent finished processing
- `error` - Error occurred during processing
- `interrupted` - Agent was interrupted
- `compacted` - Context was compacted
- `undo_complete` - Undo operation completed
- `shutdown` - Agent shutting down

## Development

### Adding Built-In Tools

Edit `agent/core/tools.py`:

```python
def create_builtin_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="your_tool",
            description="What your tool does",
            parameters={
                "type": "object",
                "properties": {
                    "param": {"type": "string", "description": "Parameter description"}
                },
                "required": ["param"],
            },
            handler=your_async_handler,
        ),
    ]
```

### Adding MCP Servers

Edit `configs/main_agent_config.json`:

```json
{
  "model_name": "anthropic/claude-sonnet-4-5-20250929",
  "mcpServers": {
    "your-server-name": {
      "transport": "http",
      "url": "https://example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${YOUR_TOKEN}"
      }
    }
  }
}
```

Environment variables like `${YOUR_TOKEN}` are substituted from `.env`.
