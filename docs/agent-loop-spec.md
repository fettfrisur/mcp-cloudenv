# Recoverable agent loop — implementation contract

Status: accepted scope for the first implementation, 2026-10-25.
This is also the durable handoff: read it, the runbook and validation record before
continuing work. The user's goal is a feedback cycle that starts the right actor
at each milestone and recovers when actors or their handoffs fail.

## Smallest complete scope

Use Python 3.12 standard-library code, SQLite, a single controller per run, and
isolated local Git clones. No queue service, model supervisor, or recursive
review-of-review mechanism. The controller owns transitions; actors never launch
their successors. A separate bounded worker process finishes an invocation and
records its exit even if the controller dies. An OS service restarts the controller
after host/process failure. Persistent storage and a live supervisor are deployment
requirements, not properties of a shell process inside a Cloud task.

First backend: an explicit argv command returning a JSON report. Codex backend:
fresh `codex exec` invocations with role prompts, schema-constrained reports, and
saved authentication. No implicit paid trials, credential provisioning or Cloud
environment publication. Source remains in Git. Runtime state stays outside the
project. An existing published Cloud conversation is not a controllable backend.

## Product cycle

1. `plan` (builder): record a bounded plan and acceptance checks in PLAN.md.
2. `plan_review` (reviewer): challenge scope, assumptions and verification.
   Findings return to `plan`.
3. `build` (builder): implement the accepted plan or remediate attached findings.
4. `review` (reviewer): investigate concrete defects against the original baseline.
5. `verify` (verifier): independently exercise the promised behavior and boundaries.
   The controller additionally executes the configured acceptance command on this
   revision. A nonzero check returns the work to `build`.
6. `branch_review` (reviewer): examine the complete branch and accumulated evidence.
7. `complete`: immutable candidate commit and evidence; no automatic merge/deploy.

Review/verifier findings route to the builder, then repeat review and verification.
Every accepted builder revision invalidates subsequent approvals. Plans can change
during remediation; reviewers must recheck consistency with intent. Periodic audits
can submit a new run through the same CLI; scheduling and automatic audit intake
are follow-up scope, not an installed feature of this first release.

## Invocation contract and failure semantics

Every request binds run ID, unique attempt ID, stage, role, input commit, goal,
original baseline and prior accepted feedback. A report repeats those identities,
has a substantive summary, a stage-valid verdict, findings and file evidence.
Builder success is `ready`; reviewer/verifier success is `pass`. A valid
`changes_requested` report is successful actor execution leading to remediation.
`blocked` is a visible terminal condition with a reason, never a passing gate.
Schema/length/path checks establish a usable handoff, not semantic truth.

Empty, malformed, oversized, wrong-identity and obsolete reports are rejected.
Missing artifacts and modifications by a non-builder are rejected. Command failures,
timeouts and malformed reports retry the same stage from its accepted input, with
diagnostics attached. Preserve failed work and logs but never adopt partial edits.
Retries have bounded backoff and an attempt cap. Remediation has a separate cap;
a total-attempt cap bounds the entire run. Exhaustion persists `blocked` and a
diagnostic. CLI exit status and persisted status provide the first notification
surface; a service must alert on blocked/nonzero exits. No messaging credentials
are provisioned by this implementation.

State is recorded before launch. Accepted results and the next ready stage commit
in one SQLite transaction. A restarted controller reconciles persisted active work:
consume its exit record, or wait for its deadline and retry. No lost wakeup relies
on a callback. Accept an attempt at most once; ignore late and duplicate delivery.
Use a controller lock and transactional identity checks. Attempt clones have separate
Git metadata; abandoned actors cannot write the accepted repository through shared
worktree metadata. This is crash isolation, not a security boundary against hostile
same-user processes. Codex sandboxing/provider permissions remain applicable.

Git promotion imports and pins an immutable object before the SQLite transaction;
SQLite's accepted commit ID is authoritative. A persisted snapshot marker permits
idempotent recovery after import. Acceptance checks have their own durable dispatch
intent and exit record, so controller restart reuses their result. Setup/Git
commands have finite deadlines too. Linux workers use child subreaping and pidfds
to clean ordinary detached descendants before reporting completion. This does not
promise containment after the supervisor itself is killed; isolated attempt clones
still fence late output, and stronger process containment requires a host cgroup.
Partial run initialization is never a resumable workflow: only an atomically
published initial DB is opened; use a new directory after failed initialization.

## Evidence and acceptance

The acceptance command is fixed at run creation, runs independently with a timeout,
and cannot be replaced by an agent's report. Preserve stdout/stderr and actual exit
status. Candidate source and baseline identities accompany each gate. Final output
is an inspectable Git candidate; applying it to the source is a separate action.

Required automated tests use subprocesses and disposable Git repositories:

- A real file defect produces findings, remediation, re-review and completion.
- Plan rejection and final branch rejection take the appropriate return paths.
- Each role crashes, hangs, or returns empty/invalid/wrong-revision output.
- Acceptance checks fail despite a passing agent report and force remediation.
- Controller dies before launch and after completion before next dispatch.
- Restart uses persisted work/results; duplicate and late reports cannot advance it.
- A late abandoned builder cannot corrupt accepted source.
- Non-builder edits and missing/path-escaping evidence are rejected.
- Retry/remediation/total budgets stop visibly, with preserved diagnostics.
- Two controllers cannot run the same state directory concurrently.
- Bad executable/configuration/auth preflight cannot become a successful run.

Live model behavior, Codex CLI compatibility, hosted Cloud dispatch and service
restart must be distinguished from deterministic fault tests. Run a small live
trial only with an available authenticated runtime; missing runtime/access remains
blocked. Never label a fake worker as an LLM agent. Review this implementation with
an independent fresh agent and fix material findings before delivery.

## Runtime evidence so far

The initial checkout matches the current remote source tree
`8df59a781bece245b66cfa56e7666b595b95f706` (main commit
`71755f69bbc13a91f503be3e104e268713fe3513`). Python 3.12.14 and Git 2.51.1 are
available. No `codex` executable is on PATH. Current docs describe `codex exec`,
JSONL events, `--output-schema`, and `-o`:
https://learn.chatgpt.com/docs/non-interactive-mode . This supports the adapter
design, not a claim that live execution has been verified here.
