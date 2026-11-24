# Vendored from github.com/didactum (source: app/services/tutor/board_validate.py) by scripts/vendor_lesson_validator.py. Do not edit.
"""Server-side validator for the Living Chalkboard board-script DSL.

The agent emits a tiny typed JSON "board" (never SVG/HTML/JS); the browser player
(static/js/lesson/board.js) renders it. This module is the SERVER half of the same
gate — it must reject anything the client validator would, so a malformed or unsafe
board never reaches the database or a learner's screen. The two validators are kept
deliberately in lockstep (same OPS, CAPS, and numeric bounds as board.js `validate()`).

Security: this never executes author strings. `math.tex` is rendered by KaTeX with
trust:false on the client; here we only bound its length and shape. A board that
fails validation is dropped (board_json stays NULL → the step renders as text), never
"repaired" — a bounded weird drawing is the worst case, and even that can't pass.
"""

from __future__ import annotations

import json
import math as _math
import re
from typing import Any, List, Optional, Tuple

from _math_regex import _NUMRE

# ── Allow-list + caps — MUST mirror board.js (OPS / CAPS) ───────────────────
OPS = frozenset(
    {
        "line",
        "polyline",
        "polygon",
        "curve",
        "circle",
        "arc",
        "label",
        "math",
        "digitgrid",
        "numberline",
        "baseten",
        "arrow",
        "highlight",
        "pause",
        "group",
        "erase",
        "strike",
        "brace",
        "callout_arrow",
        "chalk_cursor",
    }
)
# Ops that put a FIGURE on the slate (a mark a teacher's hand draws), as opposed to words. A STEM
# board whose every op is `label`/`math` is a page of text, not a teacher drawing. Used by
# validate_visual_density(). `highlight`/`strike`/`erase`/`pause`/`group` are not figures by
# themselves — they act on, or wrap, other ops.
DRAW_OPS = frozenset(
    {
        "line", "polyline", "polygon", "curve", "circle", "arc", "digitgrid",
        "numberline", "baseten", "arrow", "brace", "callout_arrow",
    }
)
CAPS = {
    "steps": 60,
    "pts": 64,
    "str": 280,
    "tex": 400,
    "digits": 12,
    "marks": 16,
    "depth": 2,
    "dur": 20000,
}

_DIGITS = re.compile(r"^\d{1,12}$")
_BASETEN = re.compile(r"^\d{1,3}$")
_OPERS = frozenset({"+", "-", "×"})
_SHAPES = frozenset({"box", "circle", "underline"})


def _num(v: Any, lo: float, hi: float) -> bool:
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and _math.isfinite(v)
        and lo <= v <= hi
    )


def _pt(p: Any) -> bool:
    return (
        isinstance(p, list)
        and len(p) == 2
        and _num(p[0], -50, 250)
        and _num(p[1], -50, 250)
    )


def _pts(a: Any) -> bool:
    return isinstance(a, list) and 1 <= len(a) <= CAPS["pts"] and all(_pt(p) for p in a)


def _str_ok(s: Any, cap: int) -> bool:
    return isinstance(s, str) and len(s) <= cap


def _valid_step(s: Any, depth: int, errs: List[str]) -> bool:
    if not isinstance(s, dict) or s.get("op") not in OPS:
        errs.append(
            "bad op: %s" % (s.get("op") if isinstance(s, dict) else type(s).__name__)
        )
        return False
    op = s["op"]
    if s.get("dur") is not None and not _num(s["dur"], 0, CAPS["dur"]):
        errs.append(op + ": dur")
        return False
    if s.get("say") is not None and not _str_ok(s["say"], CAPS["str"]):
        errs.append(op + ": say")
        return False
    if op in ("line", "arrow", "brace", "callout_arrow"):
        if not _pt(s.get("from")) or not _pt(s.get("to")):
            errs.append(op + ": from/to")
            return False
    elif op in ("polyline", "polygon", "curve"):
        if not _pts(s.get("pts")):
            errs.append(op + ": pts")
            return False
    elif op == "circle":
        if not _pt(s.get("c")) or not _num(s.get("r"), 0.5, 200):
            errs.append("circle: c/r")
            return False
    elif op == "arc":
        if (
            not _pt(s.get("c"))
            or not _num(s.get("r"), 0.5, 200)
            or not _num(s.get("a0"), -720, 720)
            or not _num(s.get("a1"), -720, 720)
        ):
            errs.append("arc")
            return False
    elif op == "chalk_cursor":
        if not _pt(s.get("at")):
            errs.append("chalk_cursor: at")
            return False
    elif op == "label":
        if not _pt(s.get("at")) or not _str_ok(s.get("text"), CAPS["str"]):
            errs.append("label")
            return False
    elif op == "math":
        if not _pt(s.get("at")) or not _str_ok(s.get("tex"), CAPS["tex"]):
            errs.append("math")
            return False
    elif op == "digitgrid":
        a, b = s.get("a"), s.get("b")
        if not (
            isinstance(a, str)
            and isinstance(b, str)
            and _DIGITS.match(a)
            and _DIGITS.match(b)
            and (s.get("oper", "+")) in _OPERS
        ):
            errs.append("digitgrid")
            return False
    elif op == "numberline":
        if (
            not _pt(s.get("at"))
            or not _num(s.get("len"), 5, 200)
            or not _num(s.get("lo"), -1e6, 1e6)
            or not _num(s.get("hi"), -1e6, 1e6)
            or s.get("hi") == s.get("lo")
        ):
            errs.append("numberline")
            return False
        if s.get("divisions") is not None and not _num(s.get("divisions"), 1, 50):
            errs.append("numberline: divisions")
            return False
        marks = s.get("marks")
        if marks is not None:
            if not isinstance(marks, list) or len(marks) > CAPS["marks"]:
                errs.append("numberline: marks")
                return False
            for mk in marks:
                if (
                    not isinstance(mk, dict)
                    or not _num(mk.get("v"), -1e6, 1e6)
                    or (mk.get("text") is not None and not _str_ok(mk.get("text"), 40))
                ):
                    errs.append("numberline: mark")
                    return False
    elif op == "baseten":
        if (
            not _pt(s.get("at"))
            or not isinstance(s.get("n"), str)
            or not _BASETEN.match(s.get("n"))
        ):
            errs.append("baseten")
            return False
        if s.get("cell") is not None and not _num(s.get("cell"), 0.5, 30):
            errs.append("baseten: cell")
            return False
    elif op == "highlight":
        box = s.get("box")
        if box is not None and not (
            isinstance(box, list)
            and len(box) == 4
            and all(_num(n, -50, 250) for n in box)
        ):
            errs.append("highlight: box")
            return False
        if s.get("target") is not None and not isinstance(s.get("target"), str):
            errs.append("highlight: target")
            return False
        if s.get("shape") is not None and s.get("shape") not in _SHAPES:
            errs.append("highlight: shape")
            return False
    elif op in ("erase", "strike"):
        # id-only in-place mutation (erase smudges / strike crosses out a prior op). Carries NO
        # numeric content — only a target id, like highlight — so the faithfulness gates see nothing.
        if not isinstance(s.get("target"), str) or not s.get("target"):
            errs.append(op + ": target")
            return False
    elif op == "pause":
        if not _num(s.get("dur"), 0, CAPS["dur"]):
            errs.append("pause: dur")
            return False
    elif op == "group":
        if depth >= CAPS["depth"]:
            errs.append("group too deep")
            return False
        children = s.get("children")
        if not isinstance(children, list) or len(children) > CAPS["steps"]:
            errs.append("group: children")
            return False
        return all(_valid_step(c, depth + 1, errs) for c in children)
    return True


def validate_board(board: Any, *, budget: bool = False) -> Tuple[bool, List[str]]:
    """Return (ok, errors). Mirrors board.js validate(): a steps array of 1..60 typed
    ops, optional w/h in [10,400], optional tempo in [0.1,3].

    `budget=True` is the AUTHORING gate: the board (one step — its ops, and its `title`/`html` when it
    carries them) must also write no more than board_constants.TEXT_BUDGET (board_teach.budget_errors).
    Off by default: boards already stored are served through the teaching pass instead of dropped."""
    errs: List[str] = []
    if not isinstance(board, dict):
        return False, ["not an object"]
    steps = board.get("steps")
    if not isinstance(steps, list) or len(steps) == 0 or len(steps) > CAPS["steps"]:
        return False, ["steps 1..%d" % CAPS["steps"]]
    if board.get("w") is not None and not _num(board["w"], 10, 400):
        errs.append("w")
    if board.get("h") is not None and not _num(board["h"], 10, 400):
        errs.append("h")
    if board.get("tempo") is not None and not _num(board["tempo"], 0.1, 3):
        errs.append("tempo")
    ok = all(_valid_step(s, 0, errs) for s in steps) and len(errs) == 0
    if ok and budget:
        from _board_teach import budget_errors

        errs.extend(budget_errors(board))
        ok = not errs
    return ok, errs


def validate_deck(deck: Any, *, stem: bool = True) -> Tuple[bool, List[str]]:
    """The AUTHORING gate for a whole lesson board ({frames:[{title, html, steps}]}): every step is a valid
    board within the text budget, and a STEM step-set draws at least one figure. Errors say what to draw."""
    from _board_teach import validate_step_set

    frames = deck.get("frames") if isinstance(deck, dict) else None
    if not isinstance(frames, list) or not frames:
        return False, ["deck: no frames"]
    errs: List[str] = []
    for i, fr in enumerate(frames, 1):
        if not isinstance(fr, dict):
            errs.append("step %d: not an object" % i)
            continue
        if fr.get("steps"):
            ok, why = validate_board({"w": deck.get("w") or 100, "h": deck.get("h") or 70, "steps": fr["steps"]})
            if not ok:
                errs.extend("step %d: %s" % (i, w) for w in why)
    ok2, why2 = validate_step_set(frames, stem=stem)
    errs.extend(why2)
    return (not errs), errs


def parse_and_validate(raw: Any) -> Optional[dict]:
    """Coerce a board (dict or JSON string) and return it only if valid, else None.
    The single chokepoint callers use before persisting a board_json."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    ok, _errs = validate_board(raw)
    return raw if ok else None


def _count_draw_ops(ops: Any) -> int:
    n = 0
    for op in ops or []:
        if not isinstance(op, dict):
            continue
        if op.get("op") in DRAW_OPS:
            n += 1
        elif op.get("op") == "group":
            n += _count_draw_ops(op.get("children"))
    return n


def validate_visual_density(deck: Any, *, stem: bool = True) -> Tuple[bool, List[str]]:
    """(ok, errors) — does a STEM deck actually DRAW? A deck is {frames:[{steps:[ops]}]} (or a bare
    board {steps:[ops]}). A board whose only ops are `label`/`math` passes validate_board and renders
    as a visually blank, text-only slate; this is the gate that names it. Non-STEM decks (prose
    subjects) are exempt. A deck with no ops at all is not this gate's business (it is `undrawn`)."""
    if not stem:
        return True, []
    if isinstance(deck, dict) and isinstance(deck.get("frames"), list):
        frames = [f.get("steps") if isinstance(f, dict) else None for f in deck["frames"]]
    elif isinstance(deck, dict) and isinstance(deck.get("steps"), list):
        frames = [deck["steps"]]
    else:
        return False, ["visual_density: no frames/steps"]
    if not any(fr for fr in frames):
        return True, []
    drawn = sum(_count_draw_ops(fr) for fr in frames)
    if drawn:
        return True, []
    return False, [
        "visual_density: the board has text ops only (label/math) and no figure — draw the "
        "situation with at least one of %s; words belong in `say`" % sorted(DRAW_OPS)
    ]


# ── Answer-free SCAFFOLD gate (the Solve "Yours" board) ─────────────────────
# A scaffold draws the SETUP of the student's OWN problem — the givens + an empty
# structure, the unknown always shown as "?" — on the board while they work. This is
# the never-verbatim invariant applied to a drawing: it must NEVER show a computed
# value. On top of validate_board (DSL safety) we enforce two deterministic rules so
# even a misbehaving model cannot leak an answer:
#   • `digitgrid` is forbidden — it animates the full worked column arithmetic, i.e.
#     it draws the result by construction.
#   • every numeral written in any label/math text must already appear in the problem
#     statement (`allowed_numbers`). A product / sum / difference / quotient / the
#     answer is, by definition, NOT in the statement → it is rejected. `say` is
#     stripped upstream (a scaffold is silent — no audible leak either).
# A scaffold that fails any rule is dropped (the step stays text-only) — never repaired.
# Forbidden on the answer-free scaffold: `digitgrid` animates the worked answer; `numberline`
# and `baseten` could likewise encode a computed value as a position / block-count. The scaffold
# is the highest-stakes never-verbatim surface, so it stays on the simplest provably-safe ops.
SCAFFOLD_OPS = OPS - {"digitgrid", "numberline", "baseten", "erase", "strike"}


# ── the board's ASK ────────────────────────────────────────────────────────────────────────────
# The board stops at the end of a frame and asks the learner to commit, right before the card that
# walks the misconception to its failure.
#
# It is a property of the FRAME, not a drawing op — and that is a load-bearing choice, not a detail:
#   • it fires when the hand has finished writing and the teacher has finished speaking. A question
#     that interrupts the drawing it is about is not a question, it is an ambush. An op would fire
#     mid-stroke by construction;
#   • an op would have to be added to the DSL allow-list, and board.js's validate() is all-or-nothing
#     while the service worker caches board.js — so the first phone still holding last week's bundle
#     would get NO BOARD AT ALL, from a change that was perfectly lockstepped in the repo. A frame
#     with an extra key is simply ignored by a player that has never heard of it. (The player is
#     ALSO now tolerant of unknown ops — but a fix that requires the field to have already deployed
#     is not a fix you can deploy.)
#
# It carries the question and the SHUFFLED choice TEXTS, and it must carry nothing else, ever:
# board_json is served to the client whole, so a `correct` index — or even a stable ordering — hands
# the answer to anyone who opens the network tab. The truth is a server row.
_ASK_LEAKS = (
    "correct",
    "correct_i",
    "answer",
    "key",
    "correct_index",
    "right",
    "is_correct",
)


def validate_frame_ask(ask: Any) -> Tuple[bool, List[str]]:
    """A frame's `ask` blob is servable — or it names what is wrong with it."""
    if not isinstance(ask, dict):
        return False, ["ask: not an object"]
    q = ask.get("q")
    if not isinstance(q, str) or not (1 <= len(q) <= CAPS["str"]):
        return False, ["ask: q"]
    ch = ask.get("choices")
    if not isinstance(ch, list) or not (2 <= len(ch) <= 5):
        return False, ["ask: choices 2..5"]
    if not all(isinstance(c, str) and 1 <= len(c) <= CAPS["str"] for c in ch):
        return False, ["ask: choice text"]
    if len({c.strip().casefold() for c in ch}) != len(ch):
        return False, ["ask: duplicate choices — one of them would be right AND wrong"]
    figs = ask.get("figs")
    if figs is not None:
        # figure choices: figs[i] renders choices[i]. Small board-DSL blobs, shape/label
        # ops only, one per choice — the alt text (the choice itself) stays the identity.
        if not isinstance(figs, list) or len(figs) != len(ch):
            return False, ["ask: figs must align 1:1 with choices"]
        allowed = {
            "line",
            "polyline",
            "polygon",
            "curve",
            "circle",
            "arc",
            "label",
            "group",
        }
        for i, fig in enumerate(figs):
            if not isinstance(fig, dict) or not isinstance(fig.get("ops"), list):
                return False, ["ask: figs[%d] must be {ops, w, h}" % i]
            ops = fig["ops"]
            if not 1 <= len(ops) <= 14:
                return False, ["ask: figs[%d] needs 1-14 ops" % i]
            names = {str(o.get("op")) for o in ops if isinstance(o, dict)}
            if names - allowed:
                return False, [
                    "ask: figs[%d] op(s) %s not allowed in a choice tile"
                    % (i, sorted(names - allowed))
                ]
            ok, why = validate_board(
                {"w": fig.get("w") or 24, "h": fig.get("h") or 24, "steps": ops}
            )
            if not ok:
                return False, [
                    "ask: figs[%d] fails board validation: %s" % (i, why[:2])
                ]
    for leak in _ASK_LEAKS:
        if leak in ask:
            return False, ["ask: '%s' must NEVER ship to the client" % leak]
    return True, []


def numbers_in(text: Any) -> set:
    """The set of numeric values (as floats) written in a string."""
    out = set()
    if not isinstance(text, str):
        return out
    for m in _NUMRE.findall(text):
        try:
            out.add(float(m))
        except ValueError:
            pass
    return out


def _num_str(v: Any) -> str:
    """Stringify a JSON number so numbers_in() can read it; pass strings through, drop the rest."""
    if isinstance(v, bool):
        return ""
    if isinstance(v, (int, float)):
        return repr(v)
    return v if isinstance(v, str) else ""


def _iter_ops(ops: Any):
    """Yield every op, descending into group children (the scaffold can nest)."""
    if not isinstance(ops, list):
        return
    for s in ops:
        if isinstance(s, dict):
            yield s
            if s.get("op") == "group":
                yield from _iter_ops(s.get("children"))


def validate_scaffold(ops: Any, allowed_numbers) -> Tuple[bool, List[str]]:
    """(ok, errors) for an answer-free scaffold op list — stricter than validate_board.
    `allowed_numbers` = the numerals (any iterable of numbers) present in the problem
    statement; nothing else may be written."""
    ok, errs = validate_board({"w": 100, "h": 70, "steps": ops})
    if not ok:
        return False, errs
    try:
        allowed = {float(n) for n in allowed_numbers}
    except (TypeError, ValueError):
        allowed = set()
    for s in _iter_ops(ops):
        if s.get("op") not in SCAFFOLD_OPS:
            return False, ["scaffold: op %s not allowed" % s.get("op")]
        for field in ("text", "tex"):
            for n in numbers_in(s.get(field)):
                if n not in allowed:
                    return False, [
                        "scaffold: leaked number %r in %s" % (n, s.get("op"))
                    ]
    return True, errs


def strip_say(ops: Any) -> Any:
    """Remove `say` from every op (recursively) — scaffolds draw silently."""
    if not isinstance(ops, list):
        return ops
    for s in ops:
        if isinstance(s, dict):
            s.pop("say", None)
            if s.get("op") == "group":
                strip_say(s.get("children"))
    return ops


# ── Themed-vs-skeleton fidelity (the decompose path) ────────────────────────
# A themed perspective board is built by re-skinning the faithful `none` skeleton: same
# math, new motif/colour/captions. Faithfulness is STRUCTURAL — a theme may change the
# motif, colours, scenery and the spoken `say` captions, but it may NOT change any NUMBER
# WRITTEN on the board (a label, a math expression, a digitgrid). We compare the set of
# written numbers frame-by-frame; on any divergence the themed board is rejected and the
# caller falls back to the neutral skeleton (faithful, just un-themed). This makes the
# "4 gems labelled 35" class of drift impossible to ship through theming.


def frame_written_numbers(ops: Any) -> frozenset:
    """The numbers WRITTEN in a frame's ops — label text, math tex, digitgrid digits.
    `say` (the spoken caption) is intentionally excluded: it is free to be re-themed."""
    nums: set = set()
    for s in _iter_ops(ops):
        op = s.get("op")
        if op == "label":
            nums |= numbers_in(s.get("text"))
        elif op == "math":
            nums |= numbers_in(s.get("tex"))
        elif op == "digitgrid":
            nums |= numbers_in(s.get("a")) | numbers_in(s.get("b"))
        elif op == "baseten":
            nums |= numbers_in(s.get("n"))
        elif op == "numberline":
            nums |= numbers_in(_num_str(s.get("lo"))) | numbers_in(
                _num_str(s.get("hi"))
            )
            for mk in s.get("marks") or []:
                if isinstance(mk, dict):
                    nums |= numbers_in(_num_str(mk.get("v"))) | numbers_in(
                        mk.get("text")
                    )
    return frozenset(nums)


_frame_numbers = frame_written_numbers


def board_written_numbers(frames: Any) -> set:
    """Extract all numbers written (label, math, digitgrid, baseten, numberline)
    across every frame's ops — the answer-free allow-list for the alt description."""
    nums: set = set()
    for fr in frames or []:
        if isinstance(fr, dict):
            nums |= frame_written_numbers(fr.get("ops") or fr.get("steps"))
    return nums


def themed_matches_skeleton(skeleton: Any, themed: Any) -> Tuple[bool, List[str]]:
    """(ok, errors) — is `themed` a faithful re-skin of `skeleton`? Both are decks of the
    shape {frames:[{..., steps:[ops]}]}. The themed deck must have the SAME number of frames
    and, per frame, the SAME set of written numbers. Motif/colour/scenery/captions may differ."""
    sf = skeleton.get("frames") if isinstance(skeleton, dict) else None
    tf = themed.get("frames") if isinstance(themed, dict) else None
    if not isinstance(sf, list) or not isinstance(tf, list):
        return False, ["frames missing"]
    if len(sf) != len(tf):
        return False, ["frame count %d != skeleton %d" % (len(tf), len(sf))]
    for i, (a, b) in enumerate(zip(sf, tf)):
        an = _frame_numbers(a.get("steps") if isinstance(a, dict) else None)
        bn = _frame_numbers(b.get("steps") if isinstance(b, dict) else None)
        if an != bn:
            return False, [
                "frame %d numbers %s != skeleton %s" % (i + 1, sorted(bn), sorted(an))
            ]
    return True, []
