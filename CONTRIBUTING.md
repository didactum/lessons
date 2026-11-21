# Contributing a lesson

1. Fork and clone. Branch: `lesson/<subject>-<slug>`.
2. Add `lessons/<subject>/<slug>.json` (one lesson per PR). Start from the closest flagship.
3. `npm run validate` must print `OK`. It checks the JSON Schema, natural chapter titles (no raw role labels),
   visual-first STEM, cue ranges, and the Never-Verbatim guard.
4. `npm run preview`, read it aloud, check the visuals make sense without the audio.
5. Open a PR; CI re-runs validation on changed lessons. Reviewers look for warm voice, honest history, correct math.

Rules of the road: CC-BY-4.0 unless you say otherwise, no copied textbook text, no answers in the teaching,
no audio or renderer code. Be kind in review.
