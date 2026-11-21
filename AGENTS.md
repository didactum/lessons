# AGENTS.md — writing lessons for Didactum

You are adding a **lesson** (`lessons/<subject>/<slug>.json`, a LessonPackage v1). You are NOT building a player:
lessons never contain pixels, audio files, or renderer code. Any teacher (chalkboard, comic, voice, Griffin video)
will play your lesson, so write the *teaching*.

## The loop (do this every time)

1. Read `prompts/create-lesson.md` and one flagship in `lessons/` closest to your topic.
2. Write `lessons/<subject>/<slug>.json`.
3. `npm run validate` until it prints `OK`.
4. `npm run preview`, open the printed URL, read your lesson aloud. Fix anything that sounds like a textbook.
5. Open a PR. CI runs the same validator.

## Craft rules

- **Chapters fit the topic.** Use as many "teaching moments" as the topic deserves: 2 (crisp strategy), 4 (visual proof),
  5 (story), whatever is natural. Never force why/history/uses/seek/how/check. `role` is optional metadata.
- **Titles are for humans.** "Babylon, 1800 BCE: the clay-tablet geometers", never "history" or "Chapter 2".
- **Warm spoken dialogue.** Contractions, short sentences, a question now and then, real numbers said as words
  ("thirty six", not "36"). No `$`, `\`, `^`, `=` in `narration.text`; it will be spoken aloud by a TTS or a face.
  Put math in `visuals`, not in speech.
- **Draw first.** STEM lessons need visuals (`fraction_bar`, `number_line`, `geometry_figure`, `coordinate_graph`,
  `equation_steps`, `balance_scale`, `diagram`, `callout`, `brace`). Use `layout.region` (left/right/center/top/bottom/full),
  never pixel coordinates. A cue (`narration.cues[].word_index`) says which spoken word a visual appears on.
- **Never verbatim.** `problem.assessment.answer` must not appear anywhere a student sees or hears. Teach the method on a
  *different* worked example and let the student finish their own problem. Set `never_verbatim_verified: true` only when
  that is true. Check-in hints may nudge; they never state the answer.
- **No provider audio.** Never include audio URLs, clip hashes, voices or TTS settings.
- `problem_chapter_index` only when context chapters precede the problem; players then offer "Skip to Problem".
- License your work (`CC-BY-4.0` default) and list `authors`.

## Do not

Edit `schema/`, `scripts/_package_adapter.py`, or other people's lessons in the same PR as a new lesson.
