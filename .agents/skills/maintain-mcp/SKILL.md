---
name: maintain-mcp
description: Follow ground truth through configuration, implementation, tests, build artifacts, deployment and observed behavior. Use proactively at task start, on cross-boundary changes or conflicting evidence, after checkout refresh, and before completion for any project in the mcp-cloudenv environment, including non-MCP and non-Node projects.
---

# Development and evidence loop

Locate the mcp-cloudenv checkout and the target project; use their actual absolute
paths. Read the target's AGENTS.md and the environment's AGENTS.md. Never assume a
sibling repository's instructions are automatically inherited. Read
`docs/ground-truth.md` in mcp-cloudenv for the ledger schema and examples.

1. **Establish the baseline.** Inspect Git status, current commit, applicable
   instructions, existing notes, open PRs and deployment records as relevant.
   Preserve unfinished work. State the intended result and checkable acceptance
   criteria. Identify the source of truth for each important claim. Start or
   continue a ledger with `scripts/chain.py`; keep it outside the target checkout.
2. **Trace the affected chain.** Ask who produces each changed value/contract, who
   consumes it, where it is enforced, and what observation demonstrates its effect.
   Follow relevant edges beyond the edited file. Include negative paths and stale
   caches where they matter. Use the trigger/claim examples in ground-truth.md.
   Classify boundaries that cannot be observed as blocked or explicitly out of
   scope. Do not infer deployment state from Git or behavior from documentation.
3. **Prepare tools.** For atproto-mcp, run `bin/mcp-env bootstrap`, then `prepare`
   and `doctor` with `--project <absolute-path>`. For another stack, derive the
   tools from its manifests/locks, record versions, and add a tested profile if
   reuse warrants it. Never install an unrelated language stack just for symmetry.
4. **Work and investigate.** Form a concrete hypothesis, make a bounded change,
   test the claim, inspect the result, and adjust. Update the chain when discoveries
   change scope. Reuse completed work. Do not settle for a successful command
   when the intended effect has not been observed.
5. **Verify the final state.** Run relevant checks on the final checkout. Use
   `chain.py observe` to record command outcomes and `chain.py file` to capture
   static configuration. Record external observations with their URL/tool source,
   timestamp, exact subject (commit/deployment/resource) and observed result.
   For atproto-mcp use `mcp-env verify`; run `audit`/`updates` for security or
   maintenance tasks. Keep paid LLM evaluation separate and record whether it ran.
6. **Close honestly.** Fill the ledger's claims and their boundary evidence, run
   `chain.py check`, and resolve stale/uncovered evidence. Exit 2 means a valid
   ledger with material blockers, not completion. State changes, evidence,
   limitations and smallest remaining action. Persist the ledger in a suitable
   authorized project record/PR or artifact; do not rely on ephemeral VM state.

For release tasks read `docs/release.md`; verify build provenance, live deployment
identity, smoke behavior and rollback readiness within the user's authorization.
Do not equate a dry run with deployment or a running process with service readiness.

Scale effort to consequences. A spelling correction usually needs source/diff
inspection; a runtime policy change needs package metadata, installer, local
commands, CI, build/deploy tooling and actual-version evidence. No universal
checklist can substitute for tracing the particular system.
