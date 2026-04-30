# Code Review

read_when: reviewing ML Junior changes, preparing a PR, or responding to review
feedback.

Review the change for correctness first. Style comments are useful only when
they reduce confusion or prevent future bugs.

## Review Focus

- Scope: change stays inside the requested write set or explains why it cannot.
- Behavior: current behavior is preserved unless the task explicitly changes it.
- Tests: regression coverage is added when a bug fix or risky behavior change
  fits the existing test harness.
- Docs: tracked docs are updated when APIs, runtime behavior, gates, or workflow
  expectations change.
- Guardrails: approvals, redaction, local filesystem boundaries, sandbox
  behavior, and network access remain explicit.
- Verification: handoff names commands run and any checks skipped.

## PR Feedback

- Cite the concrete fix and file path when replying.
- Resolve a thread only after the fix lands in the branch.
- Do not use ignored planning notes as the public source of truth; move durable
  guidance into tracked docs.

## Handoff Format

- Changed files:
- Summary:
- Tests:
- Blockers:
