# Subagent Protocol

read_when: splitting work across overseer, worker, or verifier agents; assigning
write sets; coordinating parallel doc or code slices; or checking another
agent's handoff.

Use this protocol when multiple agents work in the same repository at once.
Keep each slice small, observable, and reversible by scope rather than by git
history.

## Roles

### Overseer Loop

The overseer owns the branch-level plan and coordination loop:

- Split work into independent slices with a goal, strict write set, definition
  of done, and expected checks.
- Assign disjoint files or directories. Avoid overlapping write sets unless the
  conflict is intentional and explicitly sequenced.
- Track slice status, blockers, and verification evidence in the active backlog
  or handoff notes.
- Review worker handoffs before merging results into the branch story.
- Reassign or shrink work when a slice needs files outside its write set.

### Worker Loop

The worker owns one slice:

- Start with `git status` and read the relevant docs or code before editing.
- Edit only the assigned write set. If the root cause needs more files, stop and
  ask the overseer for a new scope.
- Preserve unrelated changes from other agents. Do not revert, rename, delete,
  or reformat files outside the slice.
- Add focused tests or docs when the slice changes behavior or public workflow.
- Run the requested checks, plus the smallest useful local check for the change.
- Final handoff names changed files, checks run, gaps, and any backlog update
  needed from the overseer.

### Verifier Loop

The verifier checks the result without expanding scope:

- Read the task, write set, diff, and worker handoff.
- Confirm the definition of done, forbidden scopes, and docs or test evidence.
- Rerun targeted checks when practical; otherwise state why not.
- Report findings with file and line references. If clean, say so and note any
  residual risk.
- Do not fix issues unless the verifier is explicitly reassigned as a worker
  with a new write set.

## Write Sets

- Treat the write set as a hard boundary.
- Read broadly when needed, but write narrowly.
- Generated files count as writes. Include them in the assigned write set or do
  not generate them.
- If two agents need the same file, sequence the work or nominate one owner.
- Before handoff, inspect `git diff --stat` or equivalent to prove only allowed
  files changed.

## Commits

- The overseer decides whether workers commit or leave changes unstaged.
- Workers do not commit unless the slice explicitly asks for it.
- When commits are allowed, commit only the worker's write set and use the
  repository's commit helper and Conventional Commit style.
- Do not amend, squash, push, or rewrite branch history unless the overseer
  explicitly asks.

## Checks

- Prefer end-to-end verification when practical; otherwise run the narrowest
  meaningful lint, typecheck, test, doc, or grep/readback check.
- Quote exact failing commands or error text in the handoff.
- For doc-only slices, use `git diff --check` and a readback or grep for the new
  link, heading, or `read_when` hint.
- If a required check is blocked by missing deps, credentials, network, or time,
  report the blocker and the best partial evidence.

## Backlog Updates

- The overseer keeps the active backlog authoritative.
- Workers update backlog files only when those files are in the write set.
- If backlog files are outside scope, include the requested status change in the
  handoff instead of editing them.
- Backlog notes should include owner, status, blocker, next action, and evidence
  path or command when available.

## Forbidden Scopes

- No edits outside the write set.
- No destructive git commands, branch rewrites, broad restores, or manual stashes
  without explicit instruction.
- No repo-wide search-and-replace or broad formatting passes.
- No dependency, runtime, signing, credential, CI, deployment, or infrastructure
  changes unless the slice explicitly includes them.
- No deleting, renaming, or overwriting unexpected files from another agent.
- No final handoff that overclaims checks, scope, or behavior.
