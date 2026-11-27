# Vendored from github.com/didactum (source: app/services/tutor/board_teach.py) by scripts/vendor_lesson_validator.py. Do not edit.
"""The board is not the transcript.

A teacher at a board writes a heading, a few short lines or equations, and labels on a drawing; the
sentences are SPOKEN. Boards authored before this rule carry a paragraph of prose in each step's `html`
(the owner's "Multi-step linear equations" step 5: nine lines of handwriting, no drawing). This module is
that rule, in two places:

* `budget_errors` / `validate_step_set` — the AUTHORING gate. A step that writes more than
  `TEXT_BUDGET` (board_constants) or a STEM step-set that draws nothing is rejected, with a message that
  says what to draw instead.
* `teach_board` — the deterministic SERVE-TIME pass for lessons that already exist (no model call). Per
  step: lines that repeat the narration go; equations and short key terms stay (compressed to the
  budget); sentences move to the narration (a `pause` op carrying `say`, so they are spoken and
  captioned, and the narration service mints their clip like any other line); and when the step's own
  numbers describe a shape — two linear expressions in one variable — the matching drawing is added.
  Conservative by construction: a number is only ever copied from the step, never computed into text,
  and a step the pass does not understand keeps its lines (trimmed to the budget) with no picture.

Pure: stdlib only, no DB, no LLM (the e2e fixture server imports it).
"""
from __future__ import annotations

import copy
import html as _html
import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from _board_constants import TEXT_BUDGET

# Ops that put a FIGURE on the board (mirror of board_validate.DRAW_OPS; imported lazily there to keep this
# module free of the validator's regex dependencies).
_DRAW_OPS = frozenset(
    {
        "line", "polyline", "polygon", "curve", "circle", "arc", "digitgrid",
        "numberline", "baseten", "arrow", "brace", "callout_arrow",
    }
)
_SAY_CAP = 280            # board_validate CAPS["str"]
_STEPS_CAP = 60           # board_validate CAPS["steps"]

# ── text extraction ────────────────────────────────────────────────────────────────────────────────────
_BLOCK_SPLIT = re.compile(r"<\s*br\s*/?>|</\s*(?:p|div|li|h[1-6]|tr)\s*>|\n", re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_TEX_CMD = {
    r"\times": "×", r"\cdot": "·", r"\approx": "≈", r"\le": "≤", r"\leq": "≤", r"\ge": "≥",
    r"\geq": "≥", r"\neq": "≠", r"\div": "÷", r"\pm": "±", r"\to": "→", r"\rightarrow": "→",
    r"\pi": "π", r"\%": "%", r"\$": "$",
}


def html_lines(html: Any) -> List[str]:
    """The lines a step's `html` writes on the board, as plain text (math delimiters kept)."""
    if not isinstance(html, str) or not html.strip():
        return []
    out = []
    for part in _BLOCK_SPLIT.split(html):
        t = _WS.sub(" ", _html.unescape(_TAG.sub(" ", part))).strip()
        if t:
            out.append(t)
    return out


_GREEK = {n: chr(c) for n, c in zip(
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi "
    "psi omega".split(), range(0x3B1, 0x3CA)) if n != "omicron"}
_GREEK.update({"Delta": "Δ", "Sigma": "Σ", "Omega": "Ω", "Pi": "Π", "Theta": "Θ", "Phi": "Φ", "varepsilon": "ε", "varphi": "φ"})
_TEX_WORDS = {
    "times": "×", "cdot": "·", "approx": "≈", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "neq": "≠", "ne": "≠",
    "div": "÷", "pm": "±", "mp": "∓", "to": "→", "rightarrow": "→", "Rightarrow": "⇒", "implies": "⇒", "infty": "∞",
    "circ": "°", "degree": "°", "checkmark": "✓", "cdots": "…", "ldots": "…", "dots": "…", "%": "%", "$": "$",
    "angle": "∠", "triangle": "△", "perp": "⊥", "parallel": "∥", "cong": "≅", "sim": "∼", "propto": "∝", "in": "∈",
    "sin": "sin", "cos": "cos", "tan": "tan", "log": "log", "ln": "ln", "exp": "exp", "min": "min", "max": "max",
    "lt": "<", "gt": ">", "{": "{", "}": "}",
}
_TEX_TEXT = {"text", "textbf", "textit", "mathrm", "mathbf", "mathit", "operatorname", "mbox", "boxed", "overline", "underline"}
_TEX_SPACE = {"left", "right", "big", "Big", "bigg", "Bigg", "displaystyle", "textstyle", "quad", "qquad", ",", ";", ":", "!", " "}
_SIMPLE = re.compile(r"^[A-Za-z0-9.°%]+$|^-?\d+(?:\.\d+)?$")


def _group(t: str, i: int) -> Tuple[str, int]:
    """The argument starting at t[i] (after spaces): a {balanced group} or one character. → (text, next index)."""
    while i < len(t) and t[i] == " ":
        i += 1
    if i >= len(t):
        return "", i
    if t[i] != "{":
        if t[i] == "\\":
            m = re.match(r"\\[A-Za-z]+", t[i:])
            if m:
                return m.group(0), i + len(m.group(0))
        return t[i], i + 1
    depth, j = 0, i
    while j < len(t):
        if t[j] == "{" and (j == 0 or t[j - 1] != "\\"):
            depth += 1
        elif t[j] == "}" and t[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return t[i + 1:j], j + 1
        j += 1
    return t[i + 1:], len(t)


def _tex_plain(t: str, stacked: bool = False) -> str:
    """One run of TeX as a reader would write it in plain text: \\frac{a}{b} → a/b (bracketed when compound),
    \\text{…} → its words, \\sqrt → √, operators → their glyphs, Greek → its letter. Never leaves a backslash."""
    out, i = [], 0
    while i < len(t):
        c = t[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+|.)", t[i:])
            name = m.group(1) if m else ""
            i += 1 + len(name)
            if name in ("frac", "dfrac", "tfrac", "cfrac"):
                a, i = _group(t, i)
                b, i = _group(t, i)
                a, b = _tex_plain(a, stacked).strip(), _tex_plain(b, stacked).strip()
                if stacked:                                # typeset, a fraction is as wide as its wider row
                    out.append("x" * max(len(a), len(b)))
                    continue
                wrap = lambda x: x if _SIMPLE.match(x) else "(%s)" % x
                out.append("%s/%s" % (wrap(a), wrap(b)))
            elif name == "sqrt":
                a, i = _group(t, i)
                a = _tex_plain(a, stacked).strip()
                out.append("√" + (a if _SIMPLE.match(a) or stacked else "(%s)" % a))
            elif name in _TEX_TEXT:
                a, i = _group(t, i)
                out.append(_tex_plain(a, stacked))
            elif name in _TEX_SPACE:
                out.append(" ")
            elif name in _GREEK:
                out.append(_GREEK[name])
            elif name in ("begin", "end"):
                _env, i = _group(t, i)                     # \\begin{aligned} … \\end{aligned}: the rows, not the names
            elif name == "\\":
                out.append("; ")
            elif name in _TEX_WORDS:
                w = _TEX_WORDS[name]
                nxt = t[i:i + 1]
                out.append((w + " ") if w.isalpha() and (nxt.isalnum() or nxt == "\\") else w)
            else:
                out.append(name if name.isalpha() and len(name) > 1 else "")
        elif c in "^_":
            a, i = _group(t, i + 1)
            a = _tex_plain(a, stacked).strip()
            out.append(("" if stacked else c) + (a if len(a) <= 1 or _SIMPLE.match(a) or stacked else "(%s)" % a))
        elif c in "{}&":
            i += 1
        elif c == "~":
            out.append(" ")
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


_TEX_RUN = re.compile(r"\$\$([\s\S]*?)\$\$|\\\[([\s\S]*?)\\\]|\\\(([\s\S]*?)\\\)|\$([^$]+?)\$")


def plain_maths(text: Any) -> str:
    """A line with its TeX written as plain maths ("Divide 360 by 6: 360 ÷ 6 = 60."): what a caption shows and the
    voice reads (speech_text.normalize says "three hundred sixty divided by six equals sixty"). Every `$…$`, `$$…$$`,
    `\\(…\\)` and `\\[…\\]` run is converted; prose outside them is left as written (a price, "$5", stays)."""
    if not isinstance(text, str):
        return ""
    def run(m: "re.Match") -> str:
        inline = m.group(4)
        if inline is not None and (inline[:1].isspace() or inline[-1:].isspace()) and not re.search(r"[=\\^_<>×÷]", inline):
            return m.group(0)                              # "$5 and $3" is money (render.js's rule: no space inside)
        return " " + _tex_plain(next(g for g in m.groups() if g is not None)).strip() + " "

    t = _TEX_RUN.sub(run, text)
    if "\\" in t:                                       # a bare TeX command outside any delimiter
        t = _tex_plain(t)
    t = _WS.sub(" ", t).strip()
    return re.sub(r"(?<![=<>≤≥≈≠])\s+([.,;:!?])", r"\1", t)


def rendered_len(text: Any) -> int:
    """A line's width in characters as the board typesets it: a stacked fraction counts its wider row, a
    superscript its characters, `\\text{…}` its words — never the TeX source's length."""
    if not isinstance(text, str):
        return 0
    t = _TEX_RUN.sub(lambda m: " " + _tex_plain(next(g for g in m.groups() if g is not None), True).strip() + " ", text)
    if "\\" in t or "{" in t:                         # an op's bare TeX (a `math` op carries no delimiters)
        t = _tex_plain(t, True)
    return len(_WS.sub(" ", t.replace("$", "")).strip())


def is_tex_block(line: Any) -> bool:
    """A line that is nothing but maths (one or more `$…$` / `$$…$$` runs and the punctuation between them)."""
    return isinstance(line, str) and "$" in line and not re.sub(r"[\s.,;:]", "", _TEX_RUN.sub("", line))


def visible(text: Any) -> str:
    """What a reader SEES of a line: TeX typeset as its glyphs (\\frac{1}{6} → 1/6), delimiters and braces gone.
    Its length is the line's rendered width in characters, never its source length."""
    if not isinstance(text, str):
        return ""
    return _WS.sub(" ", plain_maths(text).replace("$$", "")).strip()


_WORD = re.compile(r"[A-Za-z]{2,}")


def prose_words(text: str) -> int:
    """Words of prose (two or more letters); variables, numbers and operators are free."""
    return len(_WORD.findall(visible(text)))


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9=+\-×*/<>≈≤≥.]", "", visible(text).lower().replace("−", "-"))


_NUM_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
_LABEL = re.compile(r"^\s*(?:frame|step|slide|part)\s*\d+\s*[:.)\-–—]\s*", re.I)
_TOKEN = re.compile(r"[a-z]+|\d+(?:\.\d+)?")


def _tokens(text: str) -> List[str]:
    """The words of a line as the ear hears them: lower-case, number words as digits ("two" = "2")."""
    return [_NUM_WORDS.get(t, t) for t in _TOKEN.findall(visible(text).lower())]


def _already_said(text: str, said_tokens: set) -> bool:
    """The narration already says this line: its words (less a "Frame 1:" label) are, but for one in five,
    words the step speaks. A near-copy of the spoken line ("Frame 1: add 2 to both sides." under "Add two to
    both sides.") is not a second thing to say — it would be heard twice."""
    toks = _tokens(_LABEL.sub("", visible(text)))
    return bool(toks) and sum(t in said_tokens for t in toks) >= 0.8 * len(toks)


def _iter_ops(ops: Any):
    if not isinstance(ops, list):
        return
    for s in ops:
        if isinstance(s, dict):
            yield s
            if s.get("op") == "group":
                yield from _iter_ops(s.get("children"))


def written_items(frame: dict) -> List[Tuple[str, str]]:
    """Every piece of text a step WRITES, as (kind, text): 'line' for its html lines, and for ops a
    'label' (short, names part of a drawing) or a 'line' (a label/math long enough to be a line)."""
    out: List[Tuple[str, str]] = [("line", t) for t in html_lines(frame.get("html"))]
    for s in _iter_ops(frame.get("steps")):
        op = s.get("op")
        if op == "label" and isinstance(s.get("text"), str):
            t = s["text"]
        elif op == "math" and isinstance(s.get("tex"), str):
            t = s["tex"]
        elif op == "brace" and isinstance(s.get("text"), str) and s["text"]:
            t = s["text"]
        else:
            continue
        if s.get("pane"):          # a Reading & Writing passage is the text itself, not board writing
            continue
        kind = "label" if rendered_len(t) <= TEXT_BUDGET["label_chars"] else "line"
        out.append((kind, t))
    return out


def has_drawing(frame: dict) -> bool:
    return any(s.get("op") in _DRAW_OPS for s in _iter_ops(frame.get("steps")))


def budget_errors(frame: Any) -> List[str]:
    """Why a step writes too much — empty when it is within TEXT_BUDGET. Each message says what to do."""
    if not isinstance(frame, dict) or frame.get("kind") == "sat_rw":
        return []
    B = TEXT_BUDGET
    errs: List[str] = []
    title = visible(frame.get("title") or "")
    if len(title) > B["title_chars"]:
        errs.append(
            "title is %d characters (max %d): a heading names the step; the explanation is spoken"
            % (len(title), B["title_chars"])
        )
    items = written_items(frame)
    lines = [t for k, t in items if k == "line"]
    if len(lines) > B["lines"]:
        errs.append(
            "writes %d lines (max %d): keep the equations, move the sentences into `say`, and draw "
            "the situation (two cost lines crossing, a balance, a number line, a table, a bar model)"
            % (len(lines), B["lines"])
        )
    for t in lines:
        v, n = visible(t), rendered_len(t)
        if n > B["line_chars"]:
            errs.append(
                "line %r is %d characters wide (max %d): one short line or equation per row; say the rest"
                % (v[:40] + ("…" if len(v) > 40 else ""), n, B["line_chars"])
            )
    words = sum(prose_words(t) for _k, t in items)
    if words > B["words"]:
        errs.append(
            "writes %d words of prose (max %d): sentences are narration — put them in `say`, and label "
            "the drawing with a few words instead" % (words, B["words"])
        )
    return errs


# ── what the layout cannot fix: references and repeats an author got wrong ──────────────────────────────────────
# The board places every label clear of every stroke and computes each highlight from where its target ends up
# (board.js), so geometry is the renderer's job. What it cannot fix is a step that is wrong as written: a highlight,
# strike or erase whose target no earlier op of the step draws (it rings nothing, or rubs out nothing), a label or
# equation that repeats the step's heading or one of its written lines (the same words twice on one board), and a
# spoken line carrying TeX or markup source (its caption would show `\\frac`). `geometry_errors` is the authoring
# gate's message for each (board_validate.validate_deck → the generated-lesson path and the community ingest);
# `repair_frame` is the serve-time repair for the boards already stored.
_REF_OPS = ("highlight", "strike", "erase")
_TEX_LABEL = re.compile(r"\\[A-Za-z]{2,}|[\^_]\{")
_RAW_SAY = re.compile(r"\\[A-Za-z]{2,}|\$\$|[\^_]\{|\$\s*[\\A-Za-z{]|</?[a-z][a-z0-9]*[^>]*>|&(?:amp|lt|gt|nbsp|quot|#\d+);")


def pinned_ids(frames: Any) -> List[frozenset]:
    """Per step, the ids an EARLIER step pinned (`"pin": true`, LQ-BOARD-ROOM): the player keeps a pinned mark on the
    board for the rest of the lesson (static/js/lesson/board.js, the room deck), so a later step may highlight, strike
    or erase it without drawing it again."""
    out: List[frozenset] = []
    seen: set = set()
    for fr in frames if isinstance(frames, list) else []:
        out.append(frozenset(seen))
        if isinstance(fr, dict):
            seen |= {s["id"] for s in _iter_ops(fr.get("steps")) if s.get("pin") is True and isinstance(s.get("id"), str)}
    return out


def _frame_issues(frame: dict, pinned: frozenset = frozenset()) -> List[Tuple[str, dict]]:
    """(message, op) for each op of a step that is wrong as written (see above). Ops inside a group count. `pinned`:
    the ids earlier steps pinned (on the board already)."""
    out: List[Tuple[str, dict]] = []
    seen_ids: set = set(pinned)
    heading = _norm(frame.get("title") or "")
    lines = {_norm(t) for t in html_lines(frame.get("html"))}
    for s in _iter_ops(frame.get("steps")):
        op = s.get("op")
        if op in _REF_OPS and isinstance(s.get("target"), str) and s["target"] not in seen_ids:
            out.append(("%s targets %r, which no earlier op of this step draws" % (op, s["target"]), s))
        if op in ("label", "math") and not s.get("pane"):
            n = _norm(s.get("text") if op == "label" else s.get("tex"))
            if len(n) >= 3 and (n == heading or n in lines):
                out.append(("%s %r repeats the step's %s: the same words twice on one board"
                            % (op, visible(s.get("text") or s.get("tex"))[:40], "heading" if n == heading else "written line"), s))
        if op == "label" and isinstance(s.get("text"), str) and _TEX_LABEL.search(s["text"]):
            out.append(("label %r is written in TeX: make it a math op (a label is shown as typed)" % s["text"][:40], s))
        if isinstance(s.get("say"), str) and _RAW_SAY.search(s["say"]):
            out.append(("say %r carries TeX or markup source: speak it in words (a caption shows what `say` holds)"
                        % s["say"][:50], s))
        if isinstance(s.get("id"), str):
            seen_ids.add(s["id"])
    return out


def geometry_errors(frame: Any, pinned: frozenset = frozenset()) -> List[str]:
    """The authoring gate's messages for a step that is wrong as written (see `_frame_issues`)."""
    if not isinstance(frame, dict) or frame.get("kind") == "sat_rw":
        return []
    return ["geometry: " + m for m, _s in _frame_issues(frame, pinned)]


def repair_frame(frame: dict, pinned: frozenset = frozenset()) -> dict:
    """A stored step made right where it can be without changing what it teaches: a dangling highlight, strike or
    erase is dropped; a label that repeats the heading or a written line is dropped; TeX in a `say` becomes plain
    maths. An op dropped for these reasons keeps its voice (a pause carrying its `say`). Returns a new dict, or
    the same one when there is nothing to repair."""
    issues = _frame_issues(frame, pinned)
    if not issues:
        return frame
    # a repeated heading: the op goes (the heading stays). A repeated written line: the LINE goes (the op is placed in
    # the drawing, where it means something) — teach_frame drops it as already shown and closes the sentence that
    # introduced it, so the line is left to that pass here.
    to_math = {id(s) for m, s in issues if "is written in TeX" in m}
    drop = {id(s) for m, s in issues if not m.startswith("say ") and "written line" not in m and id(s) not in to_math}
    fix_say = {id(s) for m, s in issues if m.startswith("say ")}

    def walk(ops: list) -> list:
        out = []
        for s in ops:
            if not isinstance(s, dict):
                out.append(s)
                continue
            if id(s) in drop:
                if isinstance(s.get("say"), str):
                    out.append({"op": "pause", "dur": s.get("dur") or _say_ms(s["say"]), "say": plain_maths(s["say"]),
                                **({"say_clip": s["say_clip"]} if s.get("say_clip") and id(s) not in fix_say else {})})
                continue
            s2 = dict(s)
            if id(s) in to_math:
                s2["op"], s2["tex"] = "math", s2.pop("text")
            if id(s) in fix_say:
                s2["say"] = plain_maths(s["say"])
                s2.pop("say_clip", None)                      # the clip spoke the old words
            if s.get("op") == "group" and isinstance(s.get("children"), list):
                s2["children"] = walk(s["children"])
            out.append(s2)
        return out

    fr = dict(frame)
    fr["steps"] = walk(list(frame.get("steps") or []))
    return repair_frame(fr, pinned) if _frame_issues(fr, pinned) and fr["steps"] != frame.get("steps") else fr


def validate_step_set(frames: Any, *, stem: bool = True) -> Tuple[bool, List[str]]:
    """(ok, errors) for a lesson's board steps at AUTHORING time: every step within the text budget, and
    a STEM step-set draws at least one figure."""
    if not isinstance(frames, list) or not frames:
        return False, ["steps: none"]
    errs: List[str] = []
    pins = pinned_ids(frames)
    for i, fr in enumerate(frames, 1):
        for e in budget_errors(fr) + geometry_errors(fr, pins[i - 1]):
            errs.append("step %d: %s" % (i, e))
    if stem and not any(isinstance(fr, dict) and has_drawing(fr) for fr in frames):
        errs.append(
            "no step draws anything: a STEM lesson is drawn, not written — add a figure (line, polygon, "
            "numberline, arrow, …) to the steps whose content has a shape; the words belong in `say`"
        )
    return (not errs), errs


# ── equations inside a line ─────────────────────────────────────────────────────────────────────────────
_REL = "=≈<>≤≥≠"
# One token of mathematics: a number, a lone letter (a variable, never part of a word), a TeX command,
# an operator or bracket, or space. A run of these that contains a relation is an equation.
_MATH_RUN = re.compile(
    r"(?:\d+(?:[.,]\d+)*|(?<![A-Za-z])[A-Za-z](?![A-Za-z])|\\[A-Za-z]+|[+\-−×÷·*/^()=≈<>≤≥≠%√_\[\]{}| ]|\$)+"
)


def _equations(line: str) -> List[str]:
    runs = []
    for m in _MATH_RUN.finditer(line):
        r = m.group(0).strip(" $")
        if not r or not any(c in r for c in _REL) and "\\approx" not in r and "\\le" not in r and "\\ge" not in r:
            continue
        r = r.replace("$", "").strip()
        parts = re.split(r"\s*(?:=|≈|<|>|≤|≥|≠|\\approx|\\leq?|\\geq?)\s*", r)
        if len(parts) < 2 or not all(re.search(r"[0-9A-Za-z]", p) for p in parts):
            continue
        runs.append(_WS.sub(" ", r))
    return runs


def _compress_chain(eq: str) -> str:
    """`a ≈ b ≈ c ≈ d` → `a ≈ d`: the board keeps where the working starts and where it lands."""
    toks = re.split(r"(\s*(?:=|≈|<|>|≤|≥|≠)\s*)", eq)
    if len(toks) <= 3:
        return eq
    return (toks[0] + toks[-2] + toks[-1]).strip()


_LEAD = re.compile(r"\b(?:at|for|when|with|if|where|on|in)\b\s*$", re.I)


def _tex(eq: str) -> str:
    """An equation lifted out of a line keeps its maths typesetting: TeX goes back inside `$…$`."""
    return "$%s$" % eq if re.search(r"\\|\^|_|\{", eq) else eq


def _board_line(line: str) -> Optional[str]:
    """The line a teacher would WRITE for this text, or None when it is prose (said, not written)."""
    if is_tex_block(line):
        # an equation set as maths is ONE item: written whole when its typeset width fits a row, else spoken
        return line if rendered_len(line) <= TEXT_BUDGET["line_chars"] else None
    if "$" in line and prose_words(line) <= 3 and rendered_len(line) <= TEXT_BUDGET["line_chars"]:
        return line                                   # already a line of maths: written as authored
    if "$" in line and not _equations(line):
        # inline maths with no relation: an expression worth writing if the prose around it is short
        return line if prose_words(line) <= 3 and rendered_len(line) <= TEXT_BUDGET["line_chars"] else None
    eqs = _equations(line)
    if eqs and prose_words(line) >= 6:
        return None                                   # a sentence that happens to contain maths is said
    if not eqs:
        v = visible(line)
        # a short key term ("Distributive property") is written; a sentence or a lead-in ("leaving:") is said
        if (
            2 <= prose_words(line) <= 3 and len(v) <= 28 and not v.endswith((":", ".", "?", "!"))
        ):
            return v
        return None
    eqs = [_tex(_compress_chain(e)) for e in eqs]
    label = ""
    if ":" in line:
        head = line.rsplit(":", 1)[0]
        tail = line.rsplit(":", 1)[1]
        if _equations(tail):
            # "Company A at m = 4.17: 25 + 3.50(4.17) ≈ 39.60" → label "Company A", the working after the colon
            lab = re.sub(r"\s+(?:at|when|for|if|with)\s+[a-z]\s*=.*$", "", visible(head)).strip(" ,;")
            lab = _LEAD.sub("", lab).strip(" ,;")
            if lab and prose_words(lab) <= 3 and len(lab) <= 16:
                label = lab
            eqs = [_tex(_compress_chain(e)) for e in _equations(tail)]
    body = " → ".join(eqs[-2:])
    out = (label + ": " + body) if label else body
    if len(visible(out)) > TEXT_BUDGET["line_chars"] and label:
        out = label.split()[-1] + ": " + body
    if len(visible(out)) > TEXT_BUDGET["line_chars"]:
        out = eqs[-1]
    return out if len(visible(out)) <= TEXT_BUDGET["line_chars"] else None


# A sentence ends at . ! ? (or at a colon) followed by a space and a capital / quote / bracket — so "3.50m" and
# "per mile: 25 + 3.50m" stay inside their sentence.
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(“$])|(?<=:)\s+(?=[A-Z\"“])")


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENT.split(text) if s.strip()]


_LEAD_IN_WORDS = 2          # "…one side, leaving:" — a trailing clause this short only points at what follows
_SPLICE_CHARS = 40          # a board line short enough to be said inside the sentence that introduces it


def _close_lead_in(sentence: str, follows: Optional[str]) -> str:
    """A sentence that ended in a colon pointed at the line after it. When that line left the speech (written on
    the board, or dropped as already shown), the sentence would dangle ("…leaving: But this breaks…"). By rule:
    a short board line is said inside the sentence ("…leaving 25 = 6m, which gives m ≈ 4.17."); otherwise the
    pointing words go and the sentence ends ("Let's check why it fails."). Returns "" when nothing is left."""
    s = sentence.rstrip()
    if not s.endswith(":"):
        if s and s[-1] not in ".!?":
            s = s.rstrip(",;—– ") + "."             # a fragment cut off by a board line ends where it stops
        return s
    body = s[:-1].rstrip()
    if follows and ":" not in follows and len(visible(follows)) <= _SPLICE_CHARS:
        return body + (": " if is_tex_block(follows) else " ") + follows.rstrip(" .") + "."
    head, sep, tail = body.rpartition(",")
    if sep and prose_words(tail) <= _LEAD_IN_WORDS and not re.search(r"\d", tail):
        body = head.rstrip()
    body = body.rstrip(",;—– ")
    return (body + ".") if prose_words(body) >= 2 else ""


def _split_long(sentence: str) -> List[str]:
    """A sentence longer than one `say` may hold is cut at word boundaries (rare: the cap is 280 characters)."""
    if len(sentence) <= _SAY_CAP:
        return [sentence]
    out, cur = [], ""
    for w in sentence.split():
        if cur and len(cur) + 1 + len(w) > _SAY_CAP:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    return out


def spoken_lines(segments: Sequence[Tuple[str, str]]) -> List[str]:
    """The sentences a step speaks, one per line, in board order. `segments` is the step's html lines in order as
    (kind, text): 'say' for prose moved into the voice, 'board' for a line written on the board (its source text),
    'gone' for a line dropped because the board already shows or says it. Neighbouring 'say' lines are one run of
    speech (a sentence may wrap across html lines: "Whatever you do to one side," / "you must do to the other.");
    a run ends at a line that left the speech, and the run's last sentence is closed against that line."""
    out: List[str] = []
    run: List[str] = []

    def flush(follows: Optional[str]) -> None:
        if not run:
            return
        sents = _sentences(" ".join(run))
        run.clear()
        # a lead-in ("So:", "Step 2:", "Multiply the numerator by 360:") is said WITH what it introduces, as one line:
        # alone, its caption would point at nothing
        joined: List[str] = []
        for sent in sents:
            if joined and joined[-1].rstrip().endswith(":") and len(joined[-1]) + 1 + len(sent) <= _SAY_CAP:
                joined[-1] = joined[-1].rstrip() + " " + sent
            else:
                joined.append(sent)
        sents = joined
        for i, sent in enumerate(sents):
            if i == len(sents) - 1:                 # only the run's last sentence can point past the speech
                sent = _close_lead_in(sent, follows)
            if sent:
                out.extend(_split_long(sent))

    for kind, text in segments:
        if kind == "say":
            # a line of maths said aloud is a sentence of its own, never run on into the next one
            run.append(text.rstrip() + "." if is_tex_block(text) and not plain_maths(text).endswith((".", "!", "?", ":")) else text)
        else:
            flush(text if kind == "board" else None)
    flush(None)
    return out


# ── the drawing a step's numbers describe ───────────────────────────────────────────────────────────────
_NUM = r"\d+(?:\.\d+)?"


def _linear(expr: str, var: str) -> Optional[Tuple[float, float]]:
    """(intercept, slope) of `expr` if it is linear in `var` with plain decimal coefficients, else None."""
    e = visible(expr).replace("−", "-").replace("$", "").replace(" ", "")
    e = e.replace("·", "*").replace("×", "*")
    if not e or re.search(r"[A-Za-z]", e.replace(var, "")):
        return None
    terms = re.findall(r"[+-]?[^+-]+", e)
    if not terms or len(terms) > 3:
        return None
    a = b = 0.0
    seen_var = False
    for t in terms:
        sign = -1.0 if t.startswith("-") else 1.0
        t = t.lstrip("+-")
        m = re.fullmatch(r"(%s)?\*?\(?%s\)?" % (_NUM, re.escape(var)), t)
        if m:
            b += sign * float(m.group(1) or 1)
            seen_var = True
            continue
        if re.fullmatch(_NUM, t):
            a += sign * float(t)
            continue
        return None
    return (a, b) if seen_var else None


def _nice(x: float) -> float:
    if x <= 0:
        return 1.0
    p = 10 ** math.floor(math.log10(x))
    for k in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if k * p >= x:
            return k * p
    return 10 * p


def _two_lines(texts: Sequence[str]) -> Optional[Tuple[str, List[Tuple[str, str, Tuple[float, float]]]]]:
    """Two labelled linear expressions in one variable, read from the step's own text:
      * "<name> at m = 4.17: 25 + 3.50(4.17) ≈ …" — the expression with its value substituted back, or
      * "25 + 3.50m = 6m" — an equation whose two sides are both linear in the same variable.
    Returns (var, [(label, expr_text, (a, b)), …]) with exactly two distinct slopes, or None."""
    found: List[Tuple[str, str, Tuple[float, float]]] = []
    var_seen: Optional[str] = None
    sub = re.compile(r"([A-Za-z][\w ]{0,24}?)\s+(?:at|when|for)\s+([a-z])\s*=\s*(%s)\s*:\s*([^≈=<>]+)" % _NUM)
    for t in texts:
        v = visible(t)
        for m in sub.finditer(v):
            name, var, val, rhs = m.group(1).strip(), m.group(2), m.group(3), m.group(4).strip()
            if "(" + val + ")" not in rhs.replace(" ", ""):
                continue
            expr = rhs.replace(" ", "").replace("(" + val + ")", var)
            lin = _linear(expr, var)
            if lin and (var_seen in (None, var)):
                var_seen = var
                pretty = re.sub(r"(?<=[0-9])\+|\+(?=[0-9])", " + ", expr)
                found.append((name, pretty, lin))
    if len(found) < 2:
        for t in texts:
            for eq in _equations(t):
                sides = re.split(r"\s*=\s*", visible(eq))
                if len(sides) != 2:
                    continue
                vs = set(re.findall(r"(?<![A-Za-z])[a-z](?![A-Za-z])", eq))
                if len(vs) != 1:
                    continue
                var = vs.pop()
                L, R = _linear(sides[0], var), _linear(sides[1], var)
                if L and R and L[1] != R[1] and L[1] != 0 and R[1] != 0:
                    found = [("", sides[0].strip(), L), ("", sides[1].strip(), R)]
                    var_seen = var
                    break
            if len(found) >= 2:
                break
    uniq: List[Tuple[str, str, Tuple[float, float]]] = []
    for f in found:
        if all(abs(f[2][1] - u[2][1]) > 1e-9 or abs(f[2][0] - u[2][0]) > 1e-9 for u in uniq):
            uniq.append(f)
    if len(uniq) != 2 or abs(uniq[0][2][1] - uniq[1][2][1]) < 1e-9 or not var_seen:
        return None
    return var_seen, uniq


def figure_ops(texts: Sequence[str]) -> List[dict]:
    """The drawing a step's numbers describe, as board ops — or [] when the pass is not sure.

    Two linear expressions in one variable become two lines on axes, each labelled with the expression
    the step wrote, crossing at a dot (the crossing is drawn, never written: its value may be the answer).
    Nothing else is recognised yet; a step it does not recognise gets no picture rather than a wrong one."""
    two = _two_lines(texts)
    if not two:
        return []
    var, lines = two
    (n1, e1, (a1, b1)), (n2, e2, (a2, b2)) = lines
    cross = (a2 - a1) / (b1 - b2)
    xmax = _nice(cross * 1.6) if cross > 0 else _nice(10.0)
    f = lambda a, b, x: a + b * x  # noqa: E731
    ys = [f(a1, b1, 0), f(a1, b1, xmax), f(a2, b2, 0), f(a2, b2, xmax)]
    if min(ys) < 0:
        return []                      # a line below the axis needs a different frame — show less, not wrong
    ymax = _nice(max(ys) * 1.08)
    X0, Y0, X1, Y1 = 14.0, 60.0, 74.0, 10.0      # plot box on the 100x70 board; right margin holds labels
    px = lambda x: round(X0 + (X1 - X0) * x / xmax, 2)  # noqa: E731
    py = lambda y: round(Y0 - (Y0 - Y1) * y / ymax, 2)  # noqa: E731
    ops: List[dict] = [
        {"op": "arrow", "from": [X0, Y0], "to": [X1 + 6, Y0], "dur": 500, "taught": True},
        {"op": "arrow", "from": [X0, Y0], "to": [X0, Y1 - 4], "dur": 500, "taught": True},
        {"op": "label", "at": [X1 + 8, Y0], "text": var, "size": 5, "taught": True},
    ]
    for (name, expr, (a, b)), col in ((lines[0], "accent"), (lines[1], "cool")):
        p0, p1 = [px(0), py(f(a, b, 0))], [px(xmax), py(f(a, b, xmax))]
        ops.append({"op": "line", "from": p0, "to": p1, "color": col, "dur": 900, "taught": True})
        text = (name.split()[-1] + ": " + expr) if name else expr
        if len(text) > TEXT_BUDGET["label_chars"]:
            text = expr if len(expr) <= TEXT_BUDGET["label_chars"] else (name.split()[-1] if name else "")
        if text:
            ops.append({"op": "label", "at": [p1[0] + 2, p1[1]], "text": text, "size": 4.5,
                        "color": col, "taught": True})
    if 0 < cross < xmax:
        ops.append({"op": "circle", "c": [px(cross), py(f(a1, b1, cross))], "r": 1.4, "color": "good",
                    "fill": "solid", "dur": 300, "taught": True})
    return ops


# ── the serve-time pass ─────────────────────────────────────────────────────────────────────────────────


def teach_frame(frame: Any, context: Sequence[str] = (), pinned: frozenset = frozenset()) -> Any:
    """One step through the rule, returning a new dict (the input is not modified). A step already within
    budget that draws (or has nothing drawable) comes back equal to the input. `context` is the lesson's
    earlier step texts — used only to recognise a drawing, never to write a number."""
    if not isinstance(frame, dict) or frame.get("kind") == "sat_rw" or frame.get("graph"):
        return frame
    repaired = repair_frame(frame, pinned)
    fr = copy.deepcopy(repaired)
    steps = fr.get("steps") if isinstance(fr.get("steps"), list) else []
    # One spoken line per sentence: a community package or authored op that packed multiple sentences onto one
    # `say` clips on the caption bar. Split each into its first sentence on the op plus pause ops for the rest,
    # strictly within remaining `_STEPS_CAP` headroom so splitting never displaces authored drawing ops.
    budget = max(0, _STEPS_CAP - len(steps))
    split_steps: List[dict] = []
    say_split = False
    for st in steps:
        if budget > 0 and isinstance(st, dict) and isinstance(st.get("say"), str):
            sents = [plain_maths(s) for s in _sentences(st["say"]) if s.strip()]
            if len(sents) > 1:
                take = min(len(sents) - 1, budget)
                say_split = True
                budget -= take
                split_steps.append(dict(st, say=sents[0]))
                for extra in sents[1:take]:
                    split_steps.append({"op": "pause", "dur": _say_ms(extra), "say": extra, "taught": True})
                tail = " ".join(sents[take:])
                split_steps.append({"op": "pause", "dur": _say_ms(tail), "say": tail, "taught": True})
                continue
        split_steps.append(st)
    steps = split_steps
    fr["steps"] = steps
    says = " ".join(s.get("say") for s in _iter_ops(steps) if isinstance(s.get("say"), str))
    said = _norm(says)
    said_tokens = set(_tokens(says))
    written_ops = {_norm(t) for k, t in written_items({"steps": steps})}
    lines = html_lines(fr.get("html"))
    # Each source line in order: ('say', text) moves into the voice, ('board', text) is written (its board form in
    # `board_of`), ('gone', text) is dropped because the board already says or shows it.
    seg: List[List[str]] = []
    board_of: Dict[int, str] = {}
    op_maths = "".join(_norm(t) for _k, t in written_items({"steps": steps}))
    for ln in lines:
        n = _norm(ln)
        # the line's maths is already drawn by the step's own ops (its equation split over two `math` ops, say), and
        # what is left is a word or two of units: writing it again shows the same equation twice
        mp = "".join(_norm(m.group(0)) for m in _TEX_RUN.finditer(ln))
        if mp and len(mp) >= 4 and mp in op_maths and prose_words(_TEX_RUN.sub("", ln)) <= 3:
            seg.append(["gone", ln])
            continue
        if n and (n in said or n in written_ops):
            seg.append(["gone", ln])                   # the board already says/shows it
            continue
        bl = _board_line(ln)
        if bl is None:
            # prose only: an equation's numbers are not its words
            seg.append(["gone" if _already_said(ln, said_tokens) else "say", ln])
            continue
        nb = _norm(bl)
        if nb in written_ops or any(nb in _norm(board_of[j]) for j in board_of):
            seg.append(["gone", ln])
            continue
        board_of[len(seg)] = bl
        seg.append(["board", ln])
    room = max(0, TEXT_BUDGET["lines"] - sum(1 for k, _t in written_items({"steps": steps}) if k == "line"))
    kept_at = sorted(board_of)
    for j in kept_at[: max(0, len(kept_at) - room)]:  # a board shows where the working lands: the first ones are said
        seg[j][0] = "say"
        del board_of[j]
    keep = [board_of[j] for j in sorted(board_of)]
    # spoken and captioned as words and plain maths, never TeX source ("Divide 360 by 6: 360 ÷ 6 = 60.")
    spoken = [plain_maths(s) for s in spoken_lines([(k, t) for k, t in seg])
              if _norm(s) and _norm(s) not in said and not _already_said(s, said_tokens)]
    changed = bool(spoken) or keep != lines or say_split
    # title: one heading
    title = fr.get("title") or ""
    if isinstance(title, str) and len(visible(title)) > TEXT_BUDGET["title_chars"]:
        cut = visible(title)[: TEXT_BUDGET["title_chars"] - 1].rsplit(" ", 1)[0].rstrip(",;:")
        fr["title"] = cut + "…"
        changed = True
    added: List[dict] = []
    if not has_drawing(fr):
        texts = lines + [t for _k, t in written_items({"steps": steps})] + [says]
        added = figure_ops(texts) or figure_ops(list(texts) + list(context))
        if added and not _two_lines(texts) and not _mentions_var(texts, added):
            added = []                                  # context may only explain a step about the same thing
    if not changed and not added:
        return repaired
    fr["html"] = "".join("<p>%s</p>" % _html.escape(k, quote=False) for k in keep)
    # One spoken line per sentence: each is its own clip, caption and word timings, and its own time on the step's
    # timeline (the deck stretches the step to its voice, so the lines come one after another; at one instant they
    # overran the player's one-line queue and all but the last were dropped).
    say_ops = [{"op": "pause", "dur": _say_ms(c), "say": c, "taught": True} for c in spoken]
    if not says and say_ops:
        fr["steps"] = say_ops[:1] + added + say_ops[1:] + steps
    else:
        fr["steps"] = added + steps + say_ops
    fr["steps"] = fr["steps"][:_STEPS_CAP]
    return fr


def _say_ms(text: str) -> int:
    """Nominal board time for a spoken line: a calm 330 ms a word (the deck rescales a step to its real voice)."""
    return int(max(600, min(20000, 330 * len(text.split()))))


def _mentions_var(texts: Sequence[str], ops: List[dict]) -> bool:
    var = next((o.get("text") for o in ops if o.get("op") == "label" and len(o.get("text", "")) == 1), None)
    return bool(var) and any(re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(var), visible(t)) for t in texts)


def teach_board(board: Any) -> Any:
    """Every step of a deck through `teach_frame` (a copy; the stored board is untouched). Idempotent."""
    if not isinstance(board, dict) or not isinstance(board.get("frames"), list):
        return board
    if board.get("kind") == "sat_rw":
        return board
    out = dict(board)
    frames = []
    context: List[str] = []
    pins = pinned_ids(board["frames"])
    for fr, pinned in zip(board["frames"], pins):
        t = teach_frame(fr, context, pinned)
        frames.append(t)
        if isinstance(fr, dict):
            context = (html_lines(fr.get("html")) + [x for _k, x in written_items(fr)] + context)[:40]
    out["frames"] = frames
    return out


def voice_board_as_stored(board: Any) -> Any:
    """The `board_teach` kill switch's board: every step WRITTEN exactly as stored (no line moved, no drawing
    added), but still SPOKEN — the sentences the teaching pass would say are said, as the same lines (so the same
    stored clips play). Turning the rewrite off must never turn the voice off: a stored step whose prose was never
    a `say` would otherwise be a silent lesson (prod, 2026-11-24: `board_teach=false` served a board with no
    voice). A copy; idempotent; the stored board is untouched."""
    taught = teach_board(board)
    if taught is board or not isinstance(board, dict):
        return board
    out = dict(board)
    frames = []
    for fr, tf in zip(board["frames"], taught["frames"]):
        if not isinstance(fr, dict) or not isinstance(tf, dict) or tf is fr:
            frames.append(fr)
            continue
        have = {s.get("say") for s in _iter_ops(fr.get("steps")) if isinstance(s.get("say"), str)}
        add = [copy.deepcopy(s) for s in (tf.get("steps") or []) if isinstance(s, dict) and s.get("op") == "pause"
               and s.get("taught") and isinstance(s.get("say"), str) and s["say"] not in have]
        if not add:
            frames.append(fr)
            continue
        f2 = dict(fr)
        steps = list(fr.get("steps") or [])
        f2["steps"] = (add + steps) if not have else (steps + add)
        frames.append(f2)
    out["frames"] = frames
    return out

