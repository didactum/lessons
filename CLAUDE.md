# AGENTS.md — adding a lesson to didactum/lessons

Read `llms.txt` in this repo and follow it exactly. It is the one set of instructions: where the file goes, the format
(`schema/lesson-package.v2.json`), a complete valid example, the validate and preview commands, the pull-request
checklist, and what review rejects.

The loop:

1. `ls lessons/` and pick a topic that is not there.
2. Write `lessons/<subject>/<slug>.json` (file name = `slug`).
3. `python3 scripts/validate_lesson.py lessons/<subject>/<slug>.json` until it prints `OK`.
4. `node scripts/preview.mjs`, open http://localhost:4173, read the lesson aloud.
5. Open one pull request with only that file.

Never edit `schema/` or `scripts/` (they are vendored from the site and CI checks them), and never edit another
person's lesson in the same pull request.
