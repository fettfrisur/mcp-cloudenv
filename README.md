# mcp-cloudenv

A reusable Codex Cloud development environment and a default habit of checking
claims against the actual system. Include this repository alongside your project
when creating a Cloud environment. The agent installs the tools, follows affected
contracts from configuration to observed behavior, and leaves reviewable evidence.

**The central feature is the development procedure, not the Node installer.**
It applies to any project. The first executable toolchain profile is for
`fettfrisur/atproto-mcp`: Linux, Node, npm, TypeScript and Cloudflare Workers tooling.

## Recoverable agent feedback loop

The [agent loop](docs/agent-loop.md) adds a small Python/SQLite controller that
starts independent builder, reviewer and verifier invocations at explicit stages.
Findings trigger remediation and re-review. Crashes, missing/invalid reports and
timeouts retry within persistent budgets; exhaustion ends visibly blocked.
Immutable candidate commits and per-attempt Git clones fence late work. A fixed
acceptance command runs independently of agent claims. The original source is
unchanged until you separately adopt the candidate.

Try the credential-free, scripted fault demonstration on Linux:

```sh
python3 -m loop.demo --directory /tmp/agent-loop-demo --scenario review:empty
```

For actual model work, configure the Codex CLI backend and run its preflight as
described in the runbook. This controller needs an explicitly configured host and
supervisor. It is not automatically installed in Codex Cloud, and the demonstration
does not claim to evaluate live models. See the [specification](docs/agent-loop-spec.md)
and [verification record](docs/agent-loop-validation.md) for scope and evidence.

## Set up in Codex Cloud

1. On web/desktop, create an environment and select **mcp-cloudenv** plus your
   application repository (initially **atproto-mcp**).
2. Give the setup agent the short prompt in [cloud-setup.md](docs/cloud-setup.md).
   It resolves checkout paths, runs the installation, records the Install script
   and Start skill, tests them, and reports remaining gaps.
3. Review the setup results, then **Publish**. Verify a new task loads the procedure.

The current documented Cloud product publishes a prepared filesystem from selected
repositories. This repo is the versioned recipe and working agreement; it is not a
Docker image that Codex automatically builds or adopts as its host. No undocumented
Cloud configuration file or image-selection mechanism is assumed. See the dated
[research notes](docs/platform-research.md) for current vs legacy behavior.

## What runs automatically, and where

| Mechanism | Trigger | Effect |
| --- | --- | --- |
| Cloud Start skill + explicit working agreement | New task/setup invocation | Orient the agent, check freshness, establish the development loop |
| Agent procedure in `AGENTS.md` / `maintain-mcp` | Task start, boundary change, contradiction, resume, completion | Trace relevant ground truth and maintain an evidence ledger |
| `mcp-env` wrapper | Every managed command | Require exact runtime and current dependency installation |
| `chain.py check` | Before completion | Reject stale evidence, uncovered changes and unsupported ledger structure; distinguish blockers |
| Repository CI | Push and PR | Test the environment scripts, negative cases and real installer |
| Runtime maintenance workflow | Daily at 07:17 UTC / manual | Detect newer Node 24 releases or overdue policy review; fail visibly and upload a report |
| Dependabot | Weekly | Propose GitHub Actions dependency updates |

A skill is agent guidance, not an unbypassable hook. Wrapper enforcement applies
when commands use the wrapper. Target-repository required CI/rulesets must be
adopted separately for a merge gate. Neither commits nor scheduled checks silently
republish Cloud environments or deploy applications. A failed maintenance check
creates an actionable signal; it does not launch a repair agent automatically.

## Commands

Run from this repository; replace `/path/to/atproto-mcp` with the actual checkout:

```sh
bin/mcp-env bootstrap
bin/mcp-env prepare --project /path/to/atproto-mcp
bin/mcp-env doctor --project /path/to/atproto-mcp
bin/mcp-env verify --project /path/to/atproto-mcp
bin/mcp-env run --project /path/to/atproto-mcp -- npm run dev
bin/mcp-env audit --project /path/to/atproto-mcp
bin/mcp-env updates --output .cloudenv/updates.json
bin/mcp-env release-ready --project /path/to/atproto-mcp
```

`bootstrap` installs Node **24.22.1** from official archives with repository-pinned
SHA-256 digests. Node's bundled npm is used; application tools come from the
application lockfile. Python 3.12+, Git and Bash are host prerequisites, checked
or exercised by setup; OS tooling is not a fully pinned base image.

`prepare` uses strict `npm ci` when lockfile, manifest, npm config, profile, runtime
or platform changes. `verify` requires fresh dependencies and runs types,
typecheck, tests and build, plus the independent eval verifier when present. It
records commit/source identity, exact tool versions, exit codes and build hashes.
A dry run is recorded as a build, never as a deployment. Paid model trials are
never silently launched.

`release-ready` rejects dirty/stale source, failed verification and changed build
artifacts. [Release procedure](docs/release.md) covers the subsequent authorized
upload, actual deployment identity, smoke checks and rollback evidence.

For other languages/projects use [the generic chain tool](docs/ground-truth.md)
and native project tooling. Add profiles only when implemented and tested; there
is no claim that Python/Rust/Go dependency installation is currently automated.

## Development

```sh
python3 -m unittest discover -s tests -v
bash -n bin/mcp-env
```

State is kept under ignored `.cloudenv/`. Important task evidence must be saved to
an authorized durable project record or PR. Environment publication and target
repository adoption are separate from committing this template.

See [validation](docs/validation.md) for what was actually exercised, and
[adoption](docs/adoption.md) for extending enforcement beyond the Cloud workspace.
