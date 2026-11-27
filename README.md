# didactum/lessons

Open lessons, perspectives, Teaching Styles, translations, 3D logical assets, and facet aliases for [Didactum](https://didactum.org) (`didactum: 1` + legacy `lesson-package.v2.json` compatibility).

- **Contribute in one shot:** read [`llms.txt`](llms.txt) (agent-native specification, Medallion trust tiers, composable facets, and self-repair loop).
- **Fast `<1s` validator:** `python3 scripts/didactum_validate.py lessons examples --json` (Python 3.9+, standalone offline schemas in `schema/didactum-v1/`).
- **Legacy v2 validator:** `python3 scripts/validate_lesson.py`
- **Preview:** `node scripts/preview.mjs` then open http://localhost:4173.

## What's in this repository

- **Reference `didactum: 1` examples (`examples/`):**
  - [`examples/river-pen-core.json`](examples/river-pen-core.json) — core `didactum: 1` lesson (`#node` scene, `driver: voice`, `host-only` transfer key, parsed `TRUTH_CHECKS`)
  - [`examples/history-humor-style.overlay.json`](examples/history-humor-style.overlay.json) — composable Teaching-Style overlay (number-free `say.aside` historical origin + dry humor, `say.direct`, digest-pinned `base`)
  - [`examples/conic-3d.asset.json`](examples/conic-3d.asset.json) — 3D glTF 2.0 (`+Y` up, metres) logical asset metadata (`biometric_likeness: false`, third-party `license`)
  - [`examples/teacher-split.alias.json`](examples/teacher-split.alias.json) — `kind: alias` splitting one composite facet into three composable facets
- **Legacy `lesson-package.v2.json` lessons (`lessons/`):** `where-two-prices-meet.json`, `the-longest-side.json`, `backsolve-from-the-choices.json`, `area-of-a-triangle.json`.
- **Bundled offline schemas (`schema/`):** `schema/didactum-v1/{envelope.v1,lesson.v3,overlay.v1,asset.v1}.json` and legacy `schema/lesson-package.v{1,2}.json`.

## Trust, Identity & Licensing

- **Directory-is-the-registry & `id != path`:** zero central index files; artifact `id` (`@<ns>/<slug>`) is independent of file path. Community PRs bind `@<ns>` to `@gh-<github_actor_id>` (or a mapped contributor handle); `didactum/*` is maintainer-only.
- **4-tier Medallion ladder:** `Bronze → Silver → Gold → Platinum`. Passing community PRs publish cleanly at **Bronze** by URL/digest immediately and advance via deterministic validators and learner-outcome lift.
- **Repo-level license + DCO:** repo-level `CC-BY-4.0` ([`LICENSE`](LICENSE)); per-artifact `license` is forbidden except on `kind: asset`. Every commit must include `Signed-off-by:` (`git commit -s`).
- Players live in [didactum/players](https://github.com/didactum/players).
