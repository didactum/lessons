# didactum/lessons

Free, open, world-class lessons for [Didactum](https://didactum.org). Each lesson is one JSON file in the
**LessonPackage v1** format: what to teach, how to say it, what to draw. Not how it looks or sounds; that is a
[player](https://github.com/didactum/players).

```
lessons/algebra/completing-the-square.json     5 moments, with a Babylonian story
lessons/geometry/pythagorean-theorem.json      4 moments, a visual proof
lessons/sat/parallel-lines-trap.json           2 moments, a direct strategy
```

## Contribute in one prompt

Paste this into Claude Code, Cursor, Codex or Antigravity inside a clone of this repo:

> Read AGENTS.md and prompts/create-lesson.md, then write a lesson on **<your topic>** for **<grade>**, validate it,
> preview it, and open a PR.

Or clone, copy a flagship, edit, `npm run validate`, `npm run preview`, open a PR. See [CONTRIBUTING.md](CONTRIBUTING.md).

Requires Python 3.9+ and Node 18+. `pip install jsonschema` is optional (a built-in checker is used without it).
