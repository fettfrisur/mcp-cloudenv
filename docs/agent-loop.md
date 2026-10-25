# Run the recoverable agent loop

Read [the contract](agent-loop-spec.md) and [validation](agent-loop-validation.md).
The first implementation runs on one Linux host with Python 3.12+, Git, `/proc`,
pidfds and child-subreaper support. A deterministic controller starts fresh builder,
reviewer and verifier invocations. All state is in SQLite and per-attempt files.
No Python packages are required. Each attempt has an independent Git clone.

## First try: no models or credentials

From this repository, use a new directory outside your project:

```sh
python3 -m loop.demo --directory /tmp/agent-loop-demo --scenario review:empty
python3 -m loop.controller status --state /tmp/agent-loop-demo/state
python3 -m loop.controller events --state /tmp/agent-loop-demo/state
```

The demo deliberately starts with subtraction masquerading as addition. Scripted
actors identify it and repair it; the controller runs actual assertions against
the resulting commit. `review:empty` also drops the first review report. Other
scenarios include `plan:crash`, `verify:hang`, `review:garbage`, `review:wrong`,
`plan-reject`, `branch-reject`, and `check-catches` (agents falsely pass until the
controller's acceptance command detects the defect). These are deterministic
subprocess tests, not an LLM evaluation.

## Use actual Codex agents

Install and authenticate a supported Codex CLI on the Linux host. This repository
does not copy tokens or silently install a CLI. Confirm `codex --version` and
`codex login status`. Set up the project's real tools/dependencies in each fresh
checkout through the acceptance command or a trusted command adapter; environment
dependencies are not copied from the source's ignored directories. For expensive
setup, a future sandbox backend can supply prepared workspaces.

Copy `examples/loop-codex.json`, then replace `check` with an argv array that
actually tests this project's acceptance criteria. It is fixed for the run and
executes without a shell. A script can do project-specific setup followed by tests.
Do not use an agent-writable test as your only independent acceptance criterion.
Optional `model` selects an available Codex model; omission uses the CLI default.
Every invocation is a fresh context, with a prompt from `loop/prompts/` and the
persisted task/feedback. No subagents are launched by these actors.

```sh
python3 -m loop.controller preflight --config /absolute/path/loop-config.json
python3 -m loop.controller init --project /absolute/path/project \
  --state /absolute/persistent/run --goal-file /absolute/path/goal.md \
  --config /absolute/path/loop-config.json
python3 -m loop.controller run --state /absolute/persistent/run
```

The source repository must be clean. It stays unchanged. Preflight checks platform,
executables and Codex login; it makes no model call and does not prove provider
reachability, model availability or schema compatibility. Missing runtime/access
does not become a successful loop. Live use consumes the selected provider's
quota/billing; the three persisted budgets cap invocations and remediation, not
currency or token cost. `timeout` includes attempt setup and actor runtime, with
bounded extra cleanup and Git validation time. `check_timeout` bounds the separate
acceptance command. Git operations have their own finite 30/60-second limits.

## Observe, recover and inspect the candidate

`status` includes the current stage, accepted revision, active attempt, consumed
budgets, feedback and diagnostics. `events` emits ordered JSONL transitions.
Attempt directories preserve request, raw report, hashed file evidence, stderr,
Codex event stream when applicable, supervisor exit record and accepted report.
The verifier's `check-invocation/` has the actual acceptance stdout (`report.json`),
stderr and exit record; `check.json` binds the result to the candidate revision.

Restart the same `run` command after controller failure. It consumes already
completed results or waits for the persisted deadline before retrying. Never run
`init` to resume: a new run starts new budgets. Reopening a blocked or completed
run cannot reset its budgets. Only one controller can own a run at once.

The `repository/` directory contains immutable candidate commits. The SQLite
`revision` is authoritative; the repository's checkout HEAD is not moved for each
attempt. Inspect `git -C /absolute/persistent/run/repository diff BASELINE REVISION`
using the two IDs from status. Import only an independently reviewed final
candidate into the application. No merge, push, deployment or environment
publication is performed by the loop.

## Keep the controller alive

Use persistent host storage and a service supervisor. `examples/agent-loop.service`
is a user-service template; substitute actual paths and an appropriate Python
executable. `Restart=on-failure` recovers controller failures and exits normally on
completion; exit 2 marks a durable blocked run and prevents an automatic restart
storm. Monitor that status/nonzero exit with your existing service alerting.
The template is not installed by this PR. A live controller/service is required;
this is not an always-on watcher merely because the code is present.

The controller's invocation helper is a separate bounded process. Linux subreaping
and pidfds allow it to kill and reap descendants, including ordinary detached
children, before publishing completion. Host reboot can interrupt workers; after
restart persisted deadlines recover them. This assumes a working kernel and
eventual service restart. Arbitrary hostile same-user code, kernel hangs, disk
failure and filesystem rollback require stronger containment/operations. State
files and logs may contain private source; protect and retain them accordingly.
Do not put credentials in command arguments or goals.

## Cloud boundary and next capability test

Current Cloud environment setup instructions can install tools and provide the
procedure, but do not establish a supported personal lifecycle-hook controller.
This implementation does not pretend to control the current hosted conversation.
It can run on a dedicated Linux host, or inside an environment whose long-lived
runtime and authentication have been explicitly tested. A background process
inside a Cloud task alone cannot guarantee future recovery.

The documented experimental `codex cloud exec`/`list --json` path needs a separate
capability trial against the user's published environment, including artifact
handoff and feedback delivery. It is not wired in speculatively. First run the
local Codex preflight and one live defect/repair loop on a configured host; retain
its reports separately from deterministic test evidence. Periodic audit intake,
multiple concurrent tasks, remote dispatch, cross-model panels and automatic
publication remain follow-up scope.
