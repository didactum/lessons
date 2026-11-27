# AGENTS.md — contributing to didactum/lessons (`didactum: 1`)

Read [`llms.txt`](llms.txt) in this repository and follow it exactly. It defines the `didactum: 1` envelope, bundled offline schemas (`schema/didactum-v1/`), composable facets, Medallion trust ladder (`Bronze → Silver → Gold → Platinum`), DCO `Signed-off-by:` requirement, and `<1s` self-repair loop.

## The loop

1. Pick an artifact kind:
   - Core lesson (`kind: lesson`, `.score` or compiled AST — zero raw `[x, y]` coordinates, `#node` scenes, `host-only` answer/transfer keys, `TRUTH_CHECKS`)
   - Perspective or locale (`kind: overlay`, required BCP-47 `lang`, preserves `numeric-locked` numerals)
   - Composable Teaching Style (`kind: overlay`, `role: style` — math truth locked, rhetorical texture open via number-free `say.aside` + `say.direct`)
   - 3D logical asset (`kind: asset`, glTF 2.0 `+Y` up in metres, `biometric_likeness: false`, third-party `license`, zero binary blobs)
   - Facet split (`kind: alias`)
2. Set `id: "@gh-<your-github-numeric-id>/<slug>"` (or your mapped contributor handle). `didactum/*` is maintainer-only. Never set `version`; never set `license` except on `kind: asset`; never use a live URL for `kind_schema`.
3. Place the file in its topic/namespace directory (directory-is-the-registry, `id != path`, zero central index edits).
4. Validate in `<1s` and apply any `fix` ops until `ok: true`:
   `python3 scripts/didactum_validate.py <your-file> --json`
5. Commit with DCO (`git commit -s` for `Signed-off-by:`) and open one pull request.

Never edit `schema/`, `scripts/_*.py`, or other contributors' artifacts, and never commit binary blobs (`> 100 KB`, `.glb`, `.png`, `.wav`, `.mp3`, `.m4a`) or executable code outside `scripts/`.
