# Contributing a lesson

Everything you need is in [`llms.txt`](llms.txt): the format, a complete example, the commands, the checklist, and what
review rejects. In short: add one file `lessons/<subject>/<slug>.json`, run `python3 scripts/validate_lesson.py` until it
prints `OK`, and open a pull request. CI runs the same validator the site runs and attaches a preview of your board.

After a maintainer merges your pull request, the site pulls this repository and your lesson plays on
https://didactum.org within minutes, credited to the `authors` you list, under the license you chose (CC-BY-4.0 by
default).

`schema/` and `scripts/_*.py` are copied from the Didactum app (`scripts/vendor_lesson_validator.py` there); changes to
them go to the app, not here.
