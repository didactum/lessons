# Prompt: contribute a `didactum: 1` artifact

Paste this to a coding agent in a clone of this repository:

> Read `llms.txt` end-to-end and follow BOTH its `didactum: 1` structural contract AND Section 3.5 (Exemplar Chalkboard Craft & Core-vs-Overlay Separation).
>
> Contribute one `didactum: 1` artifact (core lesson in `.score` or AST JSON/YAML with zero raw `[x, y]` coordinates, composable Teaching-Style or perspective/locale overlay, logical 3D `asset`, or `alias`).
>
> For core lessons:
> 1. Recite and draw the problem unmistakably on Slide 1 (`CHALK PIN` diagram + exact `?` question, zero spoilers), build 4–6 progressive steps cumulatively on the main working pane, try and visibly fail the tempting wrong move, weave history/humor/real-world stakes into the lesson (never bolted on as a "Why It Matters" appendix), and pin the final boxed answer back to the top band.
> 2. Run one self-critique pass using `prompts/editorial-review.md` and revise once before finalizing.
> 3. Run `python3 scripts/didactum_validate.py <your-file> --strict-craft --json` until `"ok": true` (0 errors and 0 craft warnings).
>
> Commit with `git commit -s` (`Signed-off-by:`) and open one pull request.
