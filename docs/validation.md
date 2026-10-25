# Validation record — 2026-10-25

## Exercised locally

- Downloaded the official Linux x64 Node 24.22.1 archive and matched the pinned
  SHA-256 before extraction. Managed Node reports 24.22.1; bundled npm 11.19.1.
- Ran 18 unit tests covering checksum rejection, tampered binary rejection,
  dependency freshness, release selection, stale evidence, changed/deleted/new file
  coverage, expected rejection tests, external evidence completeness, and blockers.
- Ran a real disposable npm/Git project through prepare, doctor, verify and release
  checks. Rejected altered build output, dirty source, failed tests, stale lockfiles
  and incompatible engine metadata. Permissive npm environment configuration did
  not defeat the strict installer. A test exposed npm's empty-dependency behavior;
  the cache check was corrected and the integration rerun successfully.
- Forward-tested the skill independently on a Python HTTP service with conflicting
  documentation. The agent checked configuration, consumer, tests, environment
  overrides and a real loopback HTTP response. It established default port 8080,
  identified README's incorrect 8000, preserved source, and completed the ledger.
- Queried the official Node release index: the pinned 24.22.1 was current within
  major 24 at the time of the check. This is a dated observation, not a permanent
  assurance of patch status.
- Validated skill frontmatter, Python compilation and shell syntax.
- Used the connected GitHub source to retrieve all 110 text blobs from atproto-mcp
  commit `d5db229910ca574d81c3242eb187cca0ffb00cdb`, verified each Git blob hash,
  and installed its locked dependencies. Its type generation, TypeScript check,
  test command and Wrangler dry-run build all exited successfully under the
  managed runtime. The documentation JPEG was excluded; no source files were
  changed. This is a local validation snapshot, not a production deployment.

## Execution boundaries

The private application is validated from a local source snapshot when available;
no application changes, credentials, production uploads or paid model trials are
part of this template's tests. Runtime tooling and profile support are deliberately
limited to Linux Node/npm plus the generic language-independent evidence workflow.

Linux arm64 archive digests are pinned from the official manifest, but arm64
execution has not been tested here. The Cloud platform setup/publication itself
has not been performed from this task: Install script registration, Start skill
loading in a fresh Cloud task, and environment publication remain acceptance
steps in `cloud-setup.md`. Repository CI outcomes should be read from GitHub for
the exact commit under review, not inferred from this local validation record.
