# Release and operational evidence

Use for an authorized release; a coding task alone is not deployment authority.
Read the project's actual deployment configuration and existing release procedure.

1. Identify the target account/environment and current live deployment/version.
   Verify from the provider, not from a README. Record the last known-good version
   and the actual supported rollback command. Consider data/schema compatibility.
2. Finish checks on a clean committed source tree. For atproto-mcp run `verify`
   then `release-ready`. Retain verification JSON and the exact bundle hashes.
3. Identify how the upload command consumes the build. If it rebuilds, the earlier
   bundle hash is not proof of the uploaded bytes. Capture the uploaded artifact
   digest/manifest when the provider supports it; otherwise label that link
   unverified. Do not invent provenance from commit proximity.
4. Upload within existing authorization, record provider deployment ID, source
   commit, environment-recipe commit, tool versions and configuration identity.
   Do not export secrets or dump complete environment variables.
5. Verify that the intended route serves that version. Run unauthenticated denial,
   authorized MCP initialization/tool discovery, and representative read-only
   smoke calls where credentials permit. Check relevant negative cases.
6. If smoke checks fail, follow the agreed rollback procedure and verify restoration;
   report any material uncertainty. Record final live state and evidence sources.

A passing release-ready check is a local prerequisite, not deployment completion.
The Cloudflare Workers runtime is managed separately from local Node; audit the
correct layer for each claim. Package audit output doesn't certify the runtime,
OAuth configuration, live route, or application logic.

Useful release record fields: timestamp, source commit, environment commit,
lockfile hash, exact tool versions, verification result, uploaded artifact identity,
provider deployment ID, prior deployment ID, smoke observations, rollback procedure,
known gaps. The agent should use the generic chain ledger for these claims.
