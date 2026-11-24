# Vendored from github.com/didactum (source: app/services/tutor/board_constants.py) by scripts/vendor_lesson_validator.py. Do not edit.
"""Single source of truth for the readability floors (the "laws" in
docs/rendering-principles.md). One declaration, consumed everywhere so the
numbers can never drift across JS / CSS / Python:

  - app/services/tutor/board_layout.py  → BOUNDS, MIN_FONT_UNITS (virtual-space geometry)
  - app/eval/board_quality.py           → the readability/tap-target --lint gate
  - static/js/lesson/board.js           → window.didactumFloors (injected via base.html)
  - templates/base.html :root           → --text-floor / --tap-min CSS custom properties

Pure: stdlib only, imports nothing from the app, so anything may import it without
risking a cycle.
"""
from __future__ import annotations

from typing import Tuple

# Readability floor — nothing renders smaller than this on screen (px). The board
# camera's zoom floor, the lint's conflict line, and the caption policy all key off it.
MIN_TEXT_PX: int = 18

# Tap-target floor — every interactive control at least this big (px). WCAG 2.5.5 / HIG.
MIN_TAP_PX: int = 44

# Virtual-board geometry (units on the 100x70 board), shared with the collision pass
# and the camera's content-extent math.
Box = Tuple[float, float, float, float]
BOUNDS: Box = (6.0, 6.0, 94.0, 62.0)   # safe drawing area (x 6..94, y 6..62)
MIN_FONT_UNITS: float = 3.5            # collision-shrink floor, in virtual units
SAFE_PAD: float = 0.05                 # fractional inset the camera keeps around content


# What ONE board step may WRITE (the board is not the transcript). A teacher at a real board writes a
# heading, up to three short lines or equations, and a few words labelling the drawing; the sentences are
# spoken. Three lines is what a learner holds while listening (working-memory span for new material is
# ~3-4 chunks), and 44 characters is one row of 18px chalk on a 390px phone board, so a budgeted line
# never wraps into a paragraph. A label longer than `label_chars` is a line, not a label. The authoring
# gate (board_teach.budget_errors), the serve-time pass and board.js's layout all read these numbers.
TEXT_BUDGET = {
    "title_chars": 64,   # one heading row (two on a phone)
    "lines": 3,          # written lines/equations per step (labels on a drawing are not lines)
    "line_chars": 44,    # visible characters per line
    "words": 24,         # prose words across the step's lines and labels (maths symbols are free)
    "label_chars": 18,   # a label names a part of the drawing; longer is a line
}


def client_floors() -> dict:
    """The subset shipped to the browser — board.js global + CSS custom props."""
    return {"MIN_TEXT_PX": MIN_TEXT_PX, "MIN_TAP_PX": MIN_TAP_PX, "TEXT_BUDGET": dict(TEXT_BUDGET)}
