# Contributing to `didactum/lessons`

Read [`llms.txt`](llms.txt) for the full `didactum: 1` specification, examples (`examples/`), and self-repair loop.

## Quick Start

1. Author a `didactum: 1` artifact (`.json`, `.yaml`/`.yml`, or `.score` — zero raw `[x, y]` coordinates) or a legacy `lesson-package.v2.json` file.
2. Use `id: "@gh-<your-github-actor-id>/<slug>"` (or a mapped contributor handle). `didactum/*` is maintainer-only.
3. Validate offline in `<1s`:
   ```bash
   python3 scripts/didactum_validate.py <path-to-artifact> --json
   ```
   Apply any `fix` ops returned in `diagnostics` until `"ok": true`.
4. Commit with DCO (`git commit -s`, adding `Signed-off-by: Name <email>`) and open a PR.

## Rules Enforced by CI

- **DCO `Signed-off-by:`** on every commit in the PR.
- **Namespace binding** (`github.actor_id` for community PRs; `didactum/*` maintainer-only).
- **Repo-level license (`CC-BY-4.0`)**: no per-artifact `license` except on `kind: asset`; no authored `version`; no live URL `kind_schema`.
- **No binary blobs or executable code**: files `> 100 KB`, `.glb`/`.png`/`.wav`/`.mp3`/`.m4a`, real-human biometric assets, and code outside `scripts/` are rejected.
- **Medallion trust:** passing community PRs publish immediately at **Bronze** by URL/digest and climb `Bronze → Silver → Gold → Platinum` through deterministic checks and randomized learner-outcome lift.

`schema/` and `scripts/_*.py` are vendored/synced from Didactum; changes to schemas or core validators belong upstream.
