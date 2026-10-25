# Publish the environment

Select `fettfrisur/mcp-cloudenv` and the project repository in Codex Cloud's
**Create environment** flow. Include both explicitly; do not depend on a setup
script cloning private repositories with an ad hoc token.

## Prompt for the environment setup agent

> Use mcp-cloudenv as this environment's versioned setup and working agreement.
> Read its AGENTS.md and .agents/skills/maintain-mcp/SKILL.md, plus each selected
> project's instructions. Resolve the actual checkout paths. Install the host
> prerequisites if missing, run mcp-cloudenv's tests, and for atproto-mcp run
> bootstrap, prepare, doctor and verify. Configure the Install script to run these
> commands with the discovered paths. Configure the Start skill from the procedure
> below, explicitly loading the ground-truth development loop for every project.
> Do not publish until the setup report distinguishes tested, blocked, and
> unconfigured items. Do not change the application just to hide a setup failure.

This is a setup instruction, not an assumed machine-readable Cloud manifest.
The product owns the actual Install script and Start skill settings.

## Install script content

Record commands equivalent to these after resolving the paths. No assumption is
made about `/workspace` or sibling directory names:

```sh
set -eu
ENV_REPO='/actual/checkout/mcp-cloudenv'
PROJECT='/actual/checkout/atproto-mcp'
cd "$ENV_REPO"
python3 -m unittest discover -s tests -v
bash -n bin/mcp-env
bin/mcp-env bootstrap
bin/mcp-env prepare --project "$PROJECT"
bin/mcp-env doctor --project "$PROJECT"
bin/mcp-env verify --project "$PROJECT"
```

Host prerequisites: Linux x64/arm64, Python >=3.12 (including venv only if a future
profile needs it), Bash, Git, trusted CA certificates. The script uses Python's
standard library. Install missing host packages through the Cloud setup agent's
supported system package manager. No global npm/pip installation or deployment
credential is needed. Node, npm and app CLI tools are pinned by archive/lockfile.

## Start skill content

In the environment's Start skill, record the discovered path to `mcp-cloudenv`
and instruct the agent to:

1. Read its AGENTS.md and maintain-mcp skill, even if the task's cwd is a different
   repository. Read target instructions and existing unfinished work.
2. Establish the actual checkout and scope. Start/continue a `chain.py` ledger.
3. For atproto-mcp run `bootstrap`, `prepare`, `doctor`. This is idempotent for
   unchanged inputs. Use the managed wrapper for later commands. For other
   projects inspect their manifests and prepare native tools, recording versions.
4. Start only services the task needs; verify readiness with a meaningful local
   health/MCP check. Do not leave a production connection running for a code task.
5. Follow the evidence-chain triggers during work and run `chain.py check` before
   concluding. Recheck after a repository refresh or resume; do not assume the
   Start skill or Install script was automatically rerun.

Repository skills are supported in Cloud, but the discovery scope from a sibling
checkout is not a guarantee. Explicit Start skill loading closes that gap. Test it
in a **new task** after publication by asking the agent to report instruction
sources, tool versions and evidence-ledger location. Do not claim it is installed
merely because the skill file exists in Git.

## Network and credentials

Start with the **Package managers** preset plus `nodejs.org` (official runtime
archives and release index). Add `api.github.com` and `raw.githubusercontent.com`
for repository/API and release-policy inspection when needed. These domains are
not credentials. Preserve the configured HTTPS proxy; do not bypass it.

Additional permissions should follow the actual project task:

| Task | Additional access |
| --- | --- |
| Local tests/build | No production credentials; package registry access |
| Dependency audit | npm registry advisory endpoint |
| Live Bluesky tests | Exact AppView/relay domains used by the selected test |
| Real LLM evaluation | `api.openai.com`, a scoped secret and explicit run/budget authorization |
| Deployment | `api.cloudflare.com`, intended worker endpoint, scoped credential and task authorization |

Prefer a domain-bound Network secret for HTTPS API credentials that support
proxy substitution. Use a direct environment value only when the program needs
the raw value locally; never bake it into the prepared filesystem. No secret
values belong in this repository. Account availability of VPN/OIDC is not assumed.

## Publication acceptance

- Tests and real setup commands pass in the setup VM.
- A new task after Publish uses the pinned Node and loads the working agreement.
- Change a fixture lockfile and demonstrate that the wrapper refuses stale state.
- Demonstrate blocked versus verified claim reporting in a disposable project.
- Check that a sibling project also receives the Start skill instruction.
- Record environment name, template commit, app commit(s), check results and
  missing access. Do not record credentials.

After changing policy/setup: commit the source, Edit the environment, prepare and
test it, then Republish. New tasks get the updated prepared state; existing tasks
retain theirs. The wrapper detects policy/lock drift when invoked, but cannot
make the platform republish itself.
