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


def visible(text: Any) -> str:
    """What a reader SEES of a line: TeX commands become their glyphs, delimiters and braces vanish."""
    if not isinstance(text, str):
        return ""
    t = text.replace("$$", "").replace("$", "")
    t = re.sub(r"\\d?frac\{([^{}]*)\}\{([^{}]*)\}", r"\1/\2", t)
    t = re.sub(r"\\sqrt\{([^{}]*)\}", r"√\1", t)
    for k in sorted(_TEX_CMD, key=len, reverse=True):
        t = t.replace(k, _TEX_CMD[k])
    t = re.sub(r"\\(?:left|right|,|;|!|quad|qquad|text|mathrm|mathbf)\b", "", t)
    t = re.sub(r"\\[A-Za-z]+", "", t)
    t = t.replace("{", "").replace("}", "")
    return _WS.sub(" ", t).strip()


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
        kind = "label" if len(visible(t)) <= TEXT_BUDGET["label_chars"] else "line"
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
        v = visible(t)
        if len(v) > B["line_chars"]:
            errs.append(
                "line %r is %d characters (max %d): one short line or equation per row; say the rest"
                % (v[:40] + ("…" if len(v) > 40 else ""), len(v), B["line_chars"])
            )
    words = sum(prose_words(t) for _k, t in items)
    if words > B["words"]:
        errs.append(
            "writes %d words of prose (max %d): sentences are narration — put them in `say`, and label "
            "the drawing with a few words instead" % (words, B["words"])
        )
    return errs


def validate_step_set(frames: Any, *, stem: bool = True) -> Tuple[bool, List[str]]:
    """(ok, errors) for a lesson's board steps at AUTHORING time: every step within the text budget, and
    a STEM step-set draws at least one figure."""
    if not isinstance(frames, list) or not frames:
        return False, ["steps: none"]
    errs: List[str] = []
    for i, fr in enumerate(frames, 1):
        for e in budget_errors(fr):
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
    if "$" in line and prose_words(line) <= 3 and len(visible(line)) <= TEXT_BUDGET["line_chars"]:
        return line                                   # already a line of maths: written as authored
    if "$" in line and not _equations(line):
        # inline maths with no relation: an expression worth writing if the prose around it is short
        return line if prose_words(line) <= 3 and len(visible(line)) <= TEXT_BUDGET["line_chars"] else None
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
        return body + " " + follows.rstrip(" .") + "."
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
        for i, sent in enumerate(sents):
            if i == len(sents) - 1:                 # only the run's last sentence can point past the speech
                sent = _close_lead_in(sent, follows)
            if sent:
                out.extend(_split_long(sent))

    for kind, text in segments:
        if kind == "say":
            run.append(text)
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


def teach_frame(frame: Any, context: Sequence[str] = ()) -> Any:
    """One step through the rule, returning a new dict (the input is not modified). A step already within
    budget that draws (or has nothing drawable) comes back equal to the input. `context` is the lesson's
    earlier step texts — used only to recognise a drawing, never to write a number."""
    if not isinstance(frame, dict) or frame.get("kind") == "sat_rw" or frame.get("graph"):
        return frame
    fr = copy.deepcopy(frame)
    steps = fr.get("steps") if isinstance(fr.get("steps"), list) else []
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
    for ln in lines:
        n = _norm(ln)
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
    spoken = [s for s in spoken_lines([(k, t) for k, t in seg])
              if _norm(s) and _norm(s) not in said and not _already_said(s, said_tokens)]
    changed = bool(spoken) or keep != lines
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
        return frame
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
    for fr in board["frames"]:
        t = teach_frame(fr, context)
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

