# Agent-loop verification — 2026-10-25

## Implemented and exercised

The standard-library implementation is in `loop/controller.py` and `loop/worker.py`.
The three role instructions are versioned under `loop/prompts/`. Requests and
reports bind run, attempt, stage, role and revision; SQLite stores accepted state
and transitions. Attempts have private Git clones. Accepted source is an immutable
commit, imported idempotently before database acceptance. A fixed acceptance
command executes separately from the model's report.

Commands run on Linux with Python 3.12.14 and Git 2.51.1:

```sh
python3 -m unittest discover -s tests -v
bash -n bin/mcp-env
python3 -m compileall -q loop tests/test_loop.py
git diff --check
python3 -m loop.demo --directory /absolute/new/demo --scenario review:empty
python3 -m loop.controller preflight --config examples/loop-codex.json
```

The full suite passed **39 tests in 78.145 seconds**, including the original
environment tests and the new loop tests. The fault matrix runs empty, malformed,
crashed, hung and wrong-revision actor cases for builder, reviewer and verifier.
The subprocess workers are deterministic fixtures, explicitly not LLMs.

| Property | Observed evidence |
| --- | --- |
| Defect → findings → remediation → re-review | Actual subtraction defect repaired to addition in a candidate commit; original source remained unchanged |
| Plan/final branch feedback | Both rejection stages returned work to the appropriate builder stage |
| False verifier pass | Independently executed assertions failed, forcing repair despite the actor's pass report |
| Actor failure recovery | Each role's empty/malformed/crashed/hung/stale output retried within bounds |
| Invalid handoff | Escaping/missing evidence, non-builder source edits and oversized reports rejected |
| Evidence resource bound | Oversized sparse evidence rejected; hashes stream within a byte budget |
| Controller crash before dispatch | Persisted claim expired and resumed without losing the workflow |
| Crash after acceptance before next dispatch | Persisted ready stage resumed; successor was not lost |
| Git promotion crash | Reconciliation reused the frozen snapshot/import without corrupting accepted state |
| Crash after verification | Completed acceptance result reused with max_attempts=1, without rerunning the check |
| Controller killed during verification | Real controller process killed; bounded helper finished; restart completed |
| Duplicate/late delivery | Cannot advance state twice; late workspace edits cannot change candidate commit |
| Detached descendants | Real detached editor terminated before exit publication; abandoned workspace checked for late damage |
| Budgets | Stage retries, remediation and total attempt limits blocked persistently; restart did not reset them |
| Visibility/exclusivity | Blocked CLI exit 2, retained diagnostics, exclusive controller lock |
| Codex adapter contract | A test-only executable checked login/exec arguments, role sandbox, model, stdin, schema and report output |

The final scripted demo with `review:empty` completed with **10 invocations and
one remediation**, including retrying the intentionally empty report. It exercised
the actual controller, SQLite, helper processes, Git snapshots, acceptance command
and final gate. No model or hosted Cloud call occurred.

## Independent review

A separate fresh reviewer examined the specification and implementation. It found
and helped reproduce the acceptance-directory restart bug and detached-child
cleanup bug. Both were corrected and retained as regressions. The runtime mounts
`/proc` from an ancestor PID namespace; cleanup now compares host parent IDs and
maps `NSpid` IDs before using namespace-local pidfds. Only unreaped direct children
are signaled, avoiding an unrelated-PID reuse window.

The reviewer independently reran detached-child cleanup, crash after verification,
and actual controller death during verification: all three passed in 6.8 seconds.
Its final review reported no remaining material correctness findings. This is
engineering review evidence, not a proof that arbitrary model outputs are correct.

## Blocked / not installed

Actual command result:

```json
{"ready": false, "problems": ["executable unavailable: codex"]}
```

The Codex preflight exited **2**. This session has no Codex CLI on PATH. Therefore
live CLI compatibility, authentication, provider/model execution, model quality,
and an actual autonomous LLM defect/repair trial remain **blocked**. The CLI shim
does not establish these claims. Hosted `codex cloud exec` dispatch and artifact
handoff were not tested. No Cloud environment was modified or republished, and no
service, schedule, alerting integration or production deployment was installed.

The service template and runbook make host supervision explicit. A process inside
a temporary task is not an always-on service. Host reboot recovery, actual service
restart, disk durability under power loss and hostile-process containment were not
tested. The helper cleans ordinary descendants while alive; if the helper itself
is killed, attempt isolation still rejects late work, but stronger process cleanup
requires host-level containment such as a cgroup.

## Next integration action

On the intended Linux host, install/authenticate Codex, configure the fixed
acceptance command, run preflight, and execute one small live task with retained
reports. Then test service restart against the same persisted state. Establish the
published Cloud dispatch/handoff capability separately before choosing it as a
backend. The versioned specification and runbook are the handoff for that work.

## Tested executable identities

Git blob IDs for the controller and helper in the passing suite:

- `loop/controller.py`: `ee3831e084240c41f4204c100687c136382a6b39`
- `loop/worker.py`: `920d61222be4a1c75457af9763373be347ae2dd0`
- `tests/test_loop.py`: `c9b0dab8939a114bb72e9dfd8b72f58f981eafb4`
