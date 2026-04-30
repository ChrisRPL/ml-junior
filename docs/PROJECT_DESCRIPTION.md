# Project Description

read_when: onboarding to ML Junior, explaining the project to a contributor, or
checking whether a change fits the project direction.

ML Junior is an agentic ML engineering workspace. It helps a user research,
plan, implement, and verify machine-learning work with strong access to
Hugging Face docs, papers, datasets, repositories, Jobs, and sandboxed or local
execution.

Current repository shape:

- Python async agent runtime with queue-driven turns and tool calls.
- FastAPI backend with session APIs and server-sent event streaming.
- Vite/React frontend for the browser experience.
- Tool surface for Hugging Face, GitHub examples, docs, planning, local mode,
  and sandbox mode.
- Guardrails around approvals, redaction, local writes, sandbox actions, and
  network-dependent work.

Project direction:

- Make the product, UX, persistence, and contributor docs ML Junior-specific.
- Keep ML workflows observable: plans, tool calls, artifacts, metrics, and
  verification should be easy to inspect.
- Prefer deterministic offline gates for default verification; isolate provider,
  Hugging Face, Docker, and network checks.
- Treat target behavior as aspirational until tracked docs or code say it is
  implemented.

Out of scope for this description:

- Marketing copy.
- Demo data.
- Claims that ignored planning docs are the source of truth.
