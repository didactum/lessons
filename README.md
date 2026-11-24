# didactum/lessons

Open lessons for [Didactum](https://didactum.org), a free tutor that teaches on a chalkboard and speaks aloud.
A lesson is one JSON file (a *lesson package*, [schema v2](schema/lesson-package.v2.json)); it says what to teach,
what to draw and what to say, and any player can play it.

- **Contribute a lesson:** read [`llms.txt`](llms.txt) (written so a coding agent can follow it with no other context).
- **Validate:** `python3 scripts/validate_lesson.py` (Python 3.9+, no dependencies).
- **Preview:** `node scripts/preview.mjs` then open http://localhost:4173.
- **Merged lessons** play on didactum.org within minutes of the merge.

Lessons: `lessons/algebra/where-two-prices-meet.json` (a graph), `lessons/geometry/the-longest-side.json` (a figure,
with a sports perspective), `lessons/sat/backsolve-from-the-choices.json` (a test method), and the first contributed lesson,
`lessons/geometry/area-of-a-triangle.json`, written by an agent that read only `llms.txt`.

Players (how lessons are drawn and voiced) live in [didactum/players](https://github.com/didactum/players).
License: lessons are CC-BY-4.0 unless a file says otherwise.
