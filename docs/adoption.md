# Adoption beyond this environment

The template can enforce its own commands and teach the agent a default procedure.
It cannot silently govern a separate repo's direct commands, merge settings or
production credentials. Integrate each application through a normal reviewable
change when authorized.

For atproto-mcp, a focused adoption PR should:

1. Add an AGENTS.md pointer/working agreement scoped to that repo and instruct the
   agent to load the environment procedure when the environment repo is available.
2. Enforce the agreed engine boundary at local command entry points and installation
   (`devEngines` on a supported npm, or a shared guard), and reconcile lockfile,
   version pins, README and test matrix. Decide explicitly which Node lines to test.
3. Invoke the environment verification in CI using an immutable template commit,
   and test intended acceptance and rejection boundaries. A private cross-repo
   checkout requires a credential authorized for both repos; the application's
   default GITHUB_TOKEN alone does not grant access to another private repo.
4. Make the relevant checks required through repository rulesets when account/plan
   permissions allow it. Merely committing a workflow does not create a merge gate.
5. Carry the chain ledger and sanitized evidence into the PR/CI artifacts, and use
   the release procedure for production changes.

Do not copy a floating `main` from this repo into CI and assume reproducibility.
Update the pinned template commit through reviewed maintenance changes. Do not
change target metadata or CI just to make setup green. Existing atproto-mcp's
broader `>=26.12.1` engine branch is not narrowed by this environment template.

For other projects, the generic chain tool works with any Git checkout. The agent
should map the same procedure to native manifests, package manager, tests, build
outputs and deployment provider. Add an executable profile only after testing it.

## Maintaining the environment itself

The daily workflow checks the official Node index and policy-review age. It emits
a report and fails if maintenance is due or the check cannot run. Dependabot opens
weekly GitHub Actions updates. Neither mechanism silently changes the toolchain.

When the report calls for an update, the agent should inspect official release
notes/lifecycle, update `policy.json` version and both archive hashes, run installer
and regression tests, review the diff, and commit/open a PR within task authority.
Then republish and validate a new Cloud task. A checksum downloaded over TLS from
the official host is the recorded provenance; this installer does not claim GPG
signature verification or protection against compromise of that host.
