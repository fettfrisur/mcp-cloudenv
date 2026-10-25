# Platform findings — checked 2026-10-25

Sources were read from current official documentation; OpenAI search and Exa
were both used to distinguish the current product from legacy instructions.

| Question | Finding and design consequence |
| --- | --- |
| Does a base-image repository automatically become the Cloud VM? | The current guide documents selected repos, setup conversation, Install script, Start skill and published filesystem. It does not document choosing a user Dockerfile as the agent's base. This repo supplies the recipe, not a claimed custom-image import. |
| Can one repo supply a shared environment for another? | Multiple GitHub repositories can be selected. Include this repo alongside each application and explicitly load its working agreement. |
| What persists? | Publishing captures prepared files for new tasks. Existing tasks retain separate state. Commit durable code/evidence; saved VM state is not source control. |
| Do setup commands rerun after repo updates? | Repository refresh preserves dependency caches without rerunning install/start commands. Explicit fingerprint checks and proactive agent instructions address stale state. |
| How are procedures carried forward? | Repository skills are available in Cloud. AGENTS.md supplies project guidance; skill/AGENTS discovery is scoped, so sibling-repo inheritance is not assumed. |
| Can a repository schedule its own Cloud republish? | No supported API for doing that was established by the consulted docs. This repo never claims automatic republishing or agent scheduling. |
| What about codex-universal? | The older single-repo product used universal plus setup/maintenance scripts. Its reference image is useful for local approximation; it is not evidence for a current custom-image upload capability. |

## Primary sources

- Current Cloud guide: https://learn.chatgpt.com/docs/environments/cloud-environments
- Cloud overview: https://learn.chatgpt.com/docs/cloud
- Legacy guide: https://learn.chatgpt.com/docs/environments/cloud-environment
- Instruction discovery: https://learn.chatgpt.com/docs/agent-configuration/agents-md
- Skills and repo discovery: https://learn.chatgpt.com/docs/build-skills
- Runtime release: https://nodejs.org/en/blog/release/v24.22.1
- Runtime checksums: https://nodejs.org/dist/v24.22.1/SHASUMS256.txt
- Runtime index: https://nodejs.org/dist/index.json
- npm engine semantics: https://docs.npmjs.com/cli/v11/configuring-npm/package-json/
- npm strict installation: https://docs.npmjs.com/cli/v11/using-npm/config/#engine-strict
- Dependabot configuration: https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference

The Node release page identifies 24.22.1 as a security release. The executable
profile chooses that exact Node 24 version; this does not certify all future
versions or all of the application's declared support range. Daily feed checks
raise a maintenance signal, and the 30-day review reminder catches policy neglect
including lifecycle questions the release index alone cannot answer.

Network-secret delivery differs from legacy setup-only secrets: current Cloud
uses HTTPS proxy substitution for configured destinations during setup and tasks.
Use the current guide for the current product. Instructions in this repository do
not install a personal skill into unrelated local environments.
