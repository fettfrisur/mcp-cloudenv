# Ground truth across the affected chain

The default behavior is an investigation loop, not a request to run every test.
The agent maintains a small set of consequential claims and follows each through
its actual producers, consumers, enforcement points, and observations.

| Trigger | Chain to investigate | Useful falsification |
| --- | --- | --- |
| Runtime or dependency change | Policy → manifests/lock → installer/cache → executable → CI → build/deploy tools | Run below the supported boundary; check that it fails |
| API/tool format change | Producer → serialized output → schema → consumer → reference resolution | Round-trip an identifier; malformed/missing/ambiguous inputs |
| Auth/permissions change | Identity → credential delivery → request → middleware → resource → logs | Missing, forged, expired, wrong-audience and wrong-user credentials |
| Config/feature flag change | Default → environment override → parse → actual branch → observable behavior | Conflicting sources; unset/invalid values; stale process |
| Database/schema migration | Existing data → migration → constraints → readers/writers → rollback | Old/new clients, representative data, interrupted migration |
| Build or deployment change | Source commit → lock/toolchain → bundle → uploaded version → live instance | Compare actual artifact identity; smoke the intended route |
| Evaluation change | Dataset provenance → answer keys → renderer → model/tool transcript → metrics | Independent ground truth; leakage/collisions; real vs mocked trials |
| Documentation-only change | Stated behavior → current source or service → documented command | Execute example where practical; label unverified claims |

These are examples. Follow other relevant boundaries discovered in the project.
Do not invent observations to fill a table. Inspection, tests, external claims,
and live observations are distinct evidence strengths.

## A lightweight ledger

Keep the ledger outside the project so recording evidence doesn't invalidate it:

```sh
python3 "$ENV_REPO/scripts/chain.py" begin --project "$PROJECT" \
  --ledger "$ENV_REPO/.cloudenv/task-audit.json" --goal 'Describe the actual task'
python3 "$ENV_REPO/scripts/chain.py" file \
  --ledger "$ENV_REPO/.cloudenv/task-audit.json" --id package --path package.json
python3 "$ENV_REPO/scripts/chain.py" observe \
  --ledger "$ENV_REPO/.cloudenv/task-audit.json" --id checks \
  -- "$ENV_REPO/bin/mcp-env" verify --project "$PROJECT"
```

`ENV_REPO` and `PROJECT` above are task-specific variables set to the discovered
checkout paths. They aren't product-defined variables.

Edit the generated JSON's `claims` array; for example:

```json
{
  "id": "runtime-boundary",
  "statement": "The managed verification path uses the approved Node executable",
  "behavioral": true,
  "status": "verified",
  "files": ["package.json", "package-lock.json"],
  "reasoning": "Explain what the recorded observations establish and their limits",
  "chain": [
    {"layer": "metadata", "finding": "Describe the inspected range", "evidence": ["package"]},
    {"layer": "execution", "finding": "Describe actual version and test outcomes", "evidence": ["checks"]}
  ]
}
```

Only set `verified` after making the observations. This example is a schema, not
a claim about any repository. A deliberate rejection test can set
`"expected_failure": true` on a chain link, with the expected error explained in
`finding`; an arbitrary failing command is not a successful rejection test.

Add external evidence when connectors, CI logs or live services are authoritative:

```json
{
  "kind": "external",
  "source": "Canonical URL or exact connector operation",
  "checked_at": "ISO-8601 timestamp of the actual observation",
  "subject": "Exact commit, run, deployment or resource ID",
  "observation": "What the source actually returned; omit secrets"
}
```

Store it under a new ID in `evidence` and cite that ID in a chain link. External
freshness must be rechecked by the agent; the validator cannot contact every
provider. Static files are rehashed. Command evidence is invalidated if project
source changes. Commands stream their output; the ledger stores argv, exit status,
time and source identity, not raw logs or environment variables. Never put secrets
in command arguments. Preserve relevant sanitized output separately when useful.

Use `blocked` for a material acceptance criterion not established, with the exact
missing observation and next action in `reasoning`. Use `out-of-scope` for a
boundary the task does not require, with justification. Do not relabel a required
check out of scope merely because it failed or credentials are absent.

```sh
python3 "$ENV_REPO/scripts/chain.py" check \
  --ledger "$ENV_REPO/.cloudenv/task-audit.json" \
  --output "$ENV_REPO/.cloudenv/task-audit-status.json"
```

Exit codes: **0** complete coverage without declared blockers; **1** invalid,
stale or uncovered evidence; **2** valid accounting with blockers. Changed files
are detected against the starting snapshot, including tracked modifications and
unignored new files. Cover related files together; read-only tasks still need a
claim. Ignored build outputs require explicit evidence/provenance checks.

This validator prevents several easy bookkeeping failures. It cannot prove a
claim is true, decide what is relevant, stop an agent from bypassing instructions,
or authenticate handwritten external evidence. Agent reasoning supplies semantic
judgment. Required CI checks and provider permissions supply stronger enforcement.
