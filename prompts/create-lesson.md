# Prompt: create a Didactum lesson

You are an expert teacher and a careful JSON author. Write ONE file, `lessons/<subject>/<slug>.json`, a LessonPackage v1
(schema: `schema/lesson-package.v1.json`). Topic: **{{TOPIC}}**. Audience: **{{GRADE_BAND}}**.

1. Pick the student's *problem* (`problem.statement`, `givens`, `unknown`) and write its answer ONLY in
   `problem.assessment` (never anywhere else).
2. Decide how many teaching moments the topic wants. A trick may be 2 chapters; a concept with a story may be 5.
   Give each chapter a human title that sparks curiosity (never "why", "history", "Chapter 3").
3. For each beat write `narration.text` as speech: contractions, short sentences, numbers as words, no symbols.
   Add `cues` (word index where a visual appears) and a `pause_ms` after big ideas.
4. For each beat choose visuals first (`geometry_figure`, `number_line`, `equation_steps`, ...) with `layout.region`.
   No pixel coordinates.
5. Teach on a *different worked example*, then add a `checkin` (prompt, choices, hints, `correct_index`) that
   makes the student apply it to their own problem.
6. Set `metadata.never_verbatim_verified` to true only after searching your text for the answer.
7. Run `npm run validate` and `npm run preview`; fix everything; open a PR.
