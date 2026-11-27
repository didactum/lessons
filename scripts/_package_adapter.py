# Vendored from github.com/didactum (source: app/services/tutor/package_adapter.py) by scripts/vendor_lesson_validator.py. Do not edit.
"""LessonPackage: the public format for a lesson, and the ONE validator for it.

A lesson package is independent of any player. Schema v1 carries the teaching (chapters, beats, spoken
narration, semantic visuals, check-ins, the problem and its answer, perspectives). Schema v2 adds what the
Didactum chalkboard actually plays — a drawn board per beat (a heading, at most three short written lines, drawing
ops in the 100x70 board space), the reading prose, check-in replies, and per-perspective boards. A v1 package
is still accepted and is mapped forward (`upgrade`).

`validate_lesson_package` is the one validator: the JSON schema, the content rules, the hostile-input rules (size,
depth, no HTML, no URLs, no control characters) and — for v2 — the same board gates a generated lesson passes
(board_validate.validate_deck: the DSL allow-list, the text budget of board_constants.TEXT_BUDGET, a STEM lesson
draws). The app's ingest, the MCP `validate_lesson` tool and the public `didactum/lessons` CI all call it. The
public repo runs a vendored copy (scripts/vendor_lesson_validator.py writes it; a test keeps it identical), which is
why this module is stdlib-only: jsonschema when installed, a small built-in Draft 2020-12 subset otherwise.

`package_to_board` / `package_to_cards` turn a package into the stored shape the lesson player serves
(TutorLessonContent.board_json / lesson_cards). Every string an author wrote reaches HTML only through
`html.escape` here; labels and math in ops are drawn as text by the player (KaTeX with trust:false).
"""

from __future__ import annotations

import copy
import html as _html
import json
import os
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

try:  # the app
    from app.services.tutor import board_validate as _bv
except ImportError:  # the vendored copy in didactum/lessons (scripts/didactum/)
    import _board_validate as _bv  # type: ignore

SCHEMA_VERSION = "2.0"
SCHEMA_FILES = {"1.0": "lesson-package.v1.json", "2.0": "lesson-package.v2.json"}
SCHEMA_URL = "https://didactum.org/schemas/lesson-package.v2.json"
CHAPTER_ROLES = ("why", "history", "uses", "seek", "how", "check")
PERSPECTIVES = ("sports", "fantasy", "history", "astronomy")
BOARD_W, BOARD_H = 100, 70
# Hostile-input bounds: a package is text written by a stranger that will be shown and spoken to students.
LIMITS = {"bytes": 200_000, "depth": 12, "strings": 6000, "beats": 60}

# Internal role labels (current and legacy DSS) that must never surface as a student-facing title.
RAW_ROLE_TOKENS = frozenset(CHAPTER_ROLES) | {
    "recite", "orient", "strategise", "strategize", "decompose", "solve", "synthesize", "synthesise",
    "miss", "sowhat", "so what", "intro", "introduction", "conclusion", "summary", "chapter", "act", "beat",
}
_PLACEHOLDER_TITLE_RE = re.compile(r"^(chapter|act|beat|step|part|stage|moment)\s*[#:]?\s*\d*$", re.I)
STEM_SUBJECTS = frozenset({
    "math", "maths", "mathematics", "algebra", "geometry", "trigonometry", "calculus", "statistics",
    "sat-math", "act-math", "sat", "physics", "chemistry", "stem",
})
_ANSWER_SKIP_KEYS = frozenset({"id", "type", "role", "region", "emphasis", "relative_to", "reveal_cue", "op", "intent"})
# Spoken text is read aloud by a voice: TeX and code symbols are unspeakable (math goes on the board).
_UNSPEAKABLE = ("$", "\\", "^", "=", "{", "}")

# Hostile-text patterns. Lesson text is plain text everywhere; these reject it at the door with a message an
# author can act on (the escape in `_esc_lines` is the second, independent line of defence).
_TAG_RE = re.compile(r"<[A-Za-z/!?]")
_HANDLER_RE = re.compile(
    r"\bon(?:error|load|click|dblclick|mouse\w*|focus\w*|blur|key\w*|abort|change|submit|input|animation\w*|"
    r"transition\w*|pointer\w*|touch\w*|toggle|begin|end|wheel|scroll|drag\w*|drop|paste|copy|cut)\s*=", re.I)
_URL_RE = re.compile(r"(?i)\b(?:https?|ftp|file|javascript|vbscript)\s*:|\bdata:[a-z]+/|\bwww\.[a-z0-9-]+\.")
_CTRL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f‪-‮⁦-⁩]")
_PATH_RE = re.compile(r"(?:^|[\s\"'])(?:\.\./|~/|/(?:etc|home|Users|var|tmp|usr|private)/)")


# ---------------------------------------------------------------------------------------------------------
# JSON Schema
# ---------------------------------------------------------------------------------------------------------

def _find_schema_path(version: str = SCHEMA_VERSION) -> str:
    name = SCHEMA_FILES[version]
    here = os.path.dirname(os.path.abspath(__file__))
    for rel in (("..", "..", "..", "schemas"), ("..", "schema"), ("..", "..", "schema"), ("schema",), ("schemas",)):
        p = os.path.join(here, *rel, name)
        if os.path.isfile(p):
            return os.path.normpath(p)
    raise FileNotFoundError(f"{name} not found next to package_adapter")


def load_schema(path: Optional[str] = None, version: str = SCHEMA_VERSION) -> dict:
    with open(path or _find_schema_path(version), encoding="utf-8") as fh:
        return json.load(fh)


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _is_type(v: Any, t: str) -> bool:
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t])


def _mini_validate(inst: Any, schema: dict, root: dict, path: str, errs: List[str]) -> None:
    """Draft 2020-12 subset: exactly the keywords the lesson-package schemas use."""
    if "$ref" in schema:
        node: Any = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        _mini_validate(inst, node, root, path, errs)
        return
    if "const" in schema and inst != schema["const"]:
        errs.append(f"{path}: must equal {schema['const']!r}")
        return
    if "enum" in schema and inst not in schema["enum"]:
        errs.append(f"{path}: {inst!r} is not one of {schema['enum']}")
        return
    t = schema.get("type")
    if t and not _is_type(inst, t):
        errs.append(f"{path}: expected {t}")
        return
    if "oneOf" in schema:
        ok = 0
        for sub in schema["oneOf"]:
            sub_errs: List[str] = []
            _mini_validate(inst, sub, root, path, sub_errs)
            ok += not sub_errs
        if ok != 1:
            errs.append(f"{path}: must match exactly one of {schema['oneOf']}")
    if isinstance(inst, str):
        if len(inst) < schema.get("minLength", 0):
            errs.append(f"{path}: shorter than {schema['minLength']}")
        if len(inst) > schema.get("maxLength", 10**9):
            errs.append(f"{path}: longer than {schema['maxLength']} characters")
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            errs.append(f"{path}: does not match {schema['pattern']}")
    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if "minimum" in schema and inst < schema["minimum"]:
            errs.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and inst > schema["maximum"]:
            errs.append(f"{path}: above maximum {schema['maximum']}")
    if isinstance(inst, list):
        if len(inst) < schema.get("minItems", 0):
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        if len(inst) > schema.get("maxItems", 10**9):
            errs.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(inst):
                _mini_validate(item, schema["items"], root, f"{path}[{i}]", errs)
    if isinstance(inst, dict):
        for key in schema.get("required", []):
            if key not in inst:
                errs.append(f"{path}: missing required '{key}'")
        if len(inst) > schema.get("maxProperties", 10**9):
            errs.append(f"{path}: more than {schema['maxProperties']} properties")
        names = schema.get("propertyNames")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, val in inst.items():
            if names is not None:
                _mini_validate(key, names, root, f"{path}.{key}(name)", errs)
            if key in props:
                _mini_validate(val, props[key], root, f"{path}.{key}", errs)
            elif extra is False:
                errs.append(f"{path}: unexpected property '{key}'")
            elif isinstance(extra, dict):
                _mini_validate(val, extra, root, f"{path}.{key}", errs)


def schema_errors(doc: Any, schema: Optional[dict] = None) -> List[str]:
    if schema is None:
        version = doc.get("schema_version") if isinstance(doc, dict) else None
        schema = load_schema(version=version if version in SCHEMA_FILES else SCHEMA_VERSION)
    try:
        import jsonschema  # type: ignore
    except ImportError:
        errs: List[str] = []
        _mini_validate(doc, schema, schema, "$", errs)
        return errs
    validator = jsonschema.Draft202012Validator(schema)
    return [f"${''.join(f'.{p}' if isinstance(p, str) else f'[{p}]' for p in e.absolute_path)}: {e.message}"
            for e in sorted(validator.iter_errors(doc), key=lambda e: list(map(str, e.absolute_path)))]


# ---------------------------------------------------------------------------------------------------------
# Hostile input
# ---------------------------------------------------------------------------------------------------------

def _walk(node: Any, path: str = "$", depth: int = 0) -> Iterator[Tuple[str, Any, int]]:
    yield path, node, depth
    if isinstance(node, dict):
        for k, v in node.items():
            yield f"{path}.{k}(name)", k, depth + 1
            yield from _walk(v, f"{path}.{k}", depth + 1)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]", depth + 1)


def safety_errors(doc: Any) -> List[str]:
    """Size, depth and plain-text rules for every string (values and keys). Empty = safe to read further."""
    try:
        size = len(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return ["$: not JSON-serialisable"]
    if size > LIMITS["bytes"]:
        return [f"$: package is {size} bytes (max {LIMITS['bytes']}); split it into two lessons"]
    errs: List[str] = []
    n_str = 0
    for path, node, depth in _walk(doc):
        if depth > LIMITS["depth"]:
            return [f"{path}: nested deeper than {LIMITS['depth']} levels"]
        if isinstance(node, float) and (node != node or node in (float("inf"), float("-inf"))):
            errs.append(f"{path}: NaN/Infinity is not allowed")
        if not isinstance(node, str):
            continue
        n_str += 1
        if _TAG_RE.search(node) or _HANDLER_RE.search(node):
            errs.append(f"{path}: looks like HTML ({node[:40]!r}); lesson text is plain text — write 'x < y' with a "
                        f"space or use ≤ ≥, and never markup or event handlers")
        if _URL_RE.search(node):
            errs.append(f"{path}: contains a link ({node[:40]!r}); lessons do not link out — teach it in the lesson")
        if _CTRL_RE.search(node):
            errs.append(f"{path}: contains control or bidirectional-override characters")
        if _PATH_RE.search(node):
            errs.append(f"{path}: contains a file path ({node[:40]!r})")
        if len(errs) >= 20:
            break
    if n_str > LIMITS["strings"]:
        errs.append(f"$: {n_str} strings (max {LIMITS['strings']})")
    return errs


# ---------------------------------------------------------------------------------------------------------
# Content rules
# ---------------------------------------------------------------------------------------------------------

def get_chapters(doc: dict) -> List[dict]:
    """`acts` is an alias for `chapters`."""
    return doc.get("chapters") if doc.get("chapters") is not None else doc.get("acts") or []


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _title_error(title: str) -> Optional[str]:
    t = re.sub(r"[^\w\s]", " ", title.lower()).strip()
    t = re.sub(r"\s+", " ", t)
    if t in RAW_ROLE_TOKENS or _PLACEHOLDER_TITLE_RE.match(t):
        return f"chapter title {title!r} is an internal role/placeholder label; write a curiosity-sparking human title"
    return None


def _walk_strings(node: Any, skip_keys=_ANSWER_SKIP_KEYS):
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for x in node:
            yield from _walk_strings(x, skip_keys)
    elif isinstance(node, dict):
        for k, v in node.items():
            if k not in skip_keys:
                yield from _walk_strings(v, skip_keys)


def _contains_token(haystack: str, needle: str) -> bool:
    n = _norm(needle)
    if not n:
        return False
    return re.search(r"(?<![\w.])" + re.escape(n) + r"(?![\w])", _norm(haystack)) is not None


def never_verbatim_leaks(doc: dict) -> List[str]:
    """Answer strings that appear verbatim in anything a student sees or hears."""
    assess = (doc.get("problem") or {}).get("assessment") or {}
    answers = [a for a in (assess.get("answer"), assess.get("answer_value")) if isinstance(a, str) and a.strip()]
    if not answers:
        return []
    seen = list(_walk_strings({"chapters": get_chapters(doc), "perspectives": doc.get("perspectives") or {}},
                              _ANSWER_SKIP_KEYS | {"correct_index", "branches"}))
    seen.append((doc.get("problem") or {}).get("statement", ""))
    out = []
    for a in answers:
        for s in seen:
            if _contains_token(s, a):
                out.append(f"never-verbatim: answer {a!r} appears verbatim in {s[:60]!r}; teach the method on a "
                           f"different worked example and let the student finish their own problem")
                break
    return out


def _beats(doc: dict) -> Iterator[Tuple[str, dict, dict]]:
    for ci, ch in enumerate(get_chapters(doc)):
        for bi, beat in enumerate(ch["beats"]):
            yield f"chapters[{ci}].beats[{bi}] (id {beat['id']!r})", ch, beat


def _content_errors(doc: dict) -> List[str]:
    errs: List[str] = []
    chapters = get_chapters(doc)
    meta = doc["metadata"]
    v2 = doc.get("schema_version") == "2.0"
    seen_ids: set = set()
    visual_count = 0
    n_beats = 0
    for ci, ch in enumerate(chapters):
        if ch["id"] in seen_ids:
            errs.append(f"chapters[{ci}]: duplicate id {ch['id']!r}")
        seen_ids.add(ch["id"])
        msg = _title_error(ch["title"])
        if msg:
            errs.append(f"chapters[{ci}]: {msg}")
        for bi, beat in enumerate(ch["beats"]):
            n_beats += 1
            where = f"chapters[{ci}].beats[{bi}] (id {beat['id']!r})"
            if beat["id"] in seen_ids:
                errs.append(f"{where}: duplicate id {beat['id']!r}")
            seen_ids.add(beat["id"])
            visual_count += len(beat.get("visuals") or [])
            visual_count += sum(1 for o in ((beat.get("board") or {}).get("draw") or []) if o.get("op") in _bv.DRAW_OPS)
            nar = beat["narration"]
            words = len(nar["text"].split())
            for cue in nar.get("cues") or []:
                if cue["word_index"] > words:
                    errs.append(f"{where}: cue {cue['id']!r} word_index {cue['word_index']} beyond {words} words")
            if re.search(r"https?://\S+\.(mp3|wav|ogg|m4a|opus|webm)\b", nar["text"], re.I):
                errs.append(f"{where}: narration must not reference provider audio")
            ck = beat.get("checkin")
            if ck and "correct_index" in ck and ck["correct_index"] >= len(ck["choices"]):
                errs.append(f"{where}: checkin.correct_index out of range")
            if v2:
                errs.extend(_speech_errors(where, beat))
    if n_beats > LIMITS["beats"]:
        errs.append(f"$: {n_beats} beats (max {LIMITS['beats']}); split it into two lessons")
    pci = doc.get("problem_chapter_index")
    if pci is not None and pci >= len(chapters):
        errs.append(f"problem_chapter_index {pci} out of range for {len(chapters)} chapters")
    if str(meta["subject"]).lower() in STEM_SUBJECTS and visual_count == 0:
        errs.append("visual-first: STEM lesson has zero visual primitives; draw it, don't just say it")
    if meta["never_verbatim_verified"] is not True:
        errs.append("metadata.never_verbatim_verified must be true (author attests the answer is never stated)")
    beat_ids = {b["id"] for ch in chapters for b in ch["beats"]}
    for name, persp in (doc.get("perspectives") or {}).items():
        for bid in persp["beats"]:
            if bid not in beat_ids:
                errs.append(f"perspectives.{name}: unknown beat id {bid!r}")
    if v2:
        roles = [ch.get("role") for ch in chapters if ch.get("role")]
        order = [CHAPTER_ROLES.index(r) for r in roles]
        if order != sorted(order):
            errs.append(f"chapter roles {roles} are out of the teaching order {list(CHAPTER_ROLES)} "
                        f"(why it matters, where it came from, where it is used, what the problem asks, how, check)")
    errs.extend(never_verbatim_leaks(doc))
    return errs


def _speech_errors(where: str, beat: dict) -> List[str]:
    """Narration is spoken by a voice; op `say`s, when an author pins them, are the same sentences in order."""
    errs = []
    text = beat["narration"]["text"]
    bad = [c for c in _UNSPEAKABLE if c in text]
    if bad:
        errs.append(f"{where}: narration.text contains {' '.join(bad)} — it is spoken aloud; say the maths in words "
                    f"and write the symbols in board.lines")
    pinned = [o["say"] for o in _iter_ops((beat.get("board") or {}).get("draw")) if isinstance(o.get("say"), str)]
    if not pinned and len(text) > _bv.CAPS["str"]:
        errs.append(f"{where}: narration.text is {len(text)} characters; one beat speaks at most {_bv.CAPS['str']} — "
                    f"split it into two beats, or put each sentence as `say` on the draw op it belongs to")
    if pinned and _norm(" ".join(pinned)) != _norm(text):
        errs.append(f"{where}: the `say` lines on board.draw ops must be narration.text split in order "
                    f"(got {' / '.join(p[:30] for p in pinned)!r})")
    return errs


def _iter_ops(ops: Any) -> Iterator[dict]:
    for o in ops or []:
        if isinstance(o, dict):
            yield o
            if o.get("op") == "group":
                yield from _iter_ops(o.get("children"))


def is_stem(doc: dict) -> bool:
    return str((doc.get("metadata") or {}).get("subject", "")).lower() in STEM_SUBJECTS


def board_errors(doc: dict) -> List[str]:
    """The chalkboard gates a generated lesson passes, run on the board this package becomes (every perspective).
    Messages name the beat: `chapters[1].beats[0] (id 'b3'): writes 4 lines (max 3): ...`."""
    where = [w for w, _ch, _b in _beats(doc)]
    errs: List[str] = []
    for persp in (None, *sorted((doc.get("perspectives") or {}))):
        board = package_to_board(doc, persp)
        tag = f"perspectives.{persp}: " if persp else ""
        ok, why = _bv.validate_deck(board, stem=is_stem(doc))
        for w in why:
            m = re.match(r"step (\d+): (.*)", w)
            if m and not m.group(2).startswith(("writes", "line", "title", "geometry:")):
                errs.append(f"{tag}{where[int(m.group(1)) - 1]}: board.draw op {m.group(2)!r} is malformed or off the "
                            f"board (ops use x 0..100, y 0..70; see the op reference in llms.txt)")
            else:
                errs.append(tag + (f"{where[int(m.group(1)) - 1]}: board {m.group(2)}" if m else w))
        ok, why = _bv.validate_visual_density(board, stem=is_stem(doc))
        errs.extend(tag + w for w in why)
        prev_ids: set = set()
        for i, fr in enumerate(board["frames"]):
            ids = {o["id"] for o in _iter_ops(fr["steps"]) if isinstance(o.get("id"), str)}
            for o in _iter_ops(fr["steps"]):
                if isinstance(o.get("say"), str) and o.get("id") in prev_ids:
                    errs.append(f"{tag}{where[i]}: the line is spoken on op id {o['id']!r}, which is already on the board "
                                f"from the beat before, so the player keeps it and never speaks the line — speak it on a "
                                f"new op (put a new op first, or remove the id)")
            prev_ids = ids
            if "ask" in fr:
                ok, why = _bv.validate_frame_ask(fr["ask"])
                errs.extend(f"{tag}{where[i]}: checkin {w}" for w in why)
    return errs


def validate_lesson_package(doc: Any, schema: Optional[dict] = None) -> List[str]:
    """Return a list of problems; an empty list means the package is valid. v2 packages must also pass the
    chalkboard gates; a v1 package passes the v1 rules (it is checked against the board when it is ingested)."""
    if not isinstance(doc, dict):
        return ["$: package must be a JSON object"]
    errs = safety_errors(doc)
    if errs:
        return errs
    if doc.get("schema_version") not in SCHEMA_FILES:
        return [f"$.schema_version: must be \"{SCHEMA_VERSION}\" (or \"1.0\"); schema: {SCHEMA_URL}"]
    errs = schema_errors(doc, schema)
    if errs:
        return errs  # semantic checks assume a structurally sound document
    errs = _content_errors(doc)
    if doc["schema_version"] == "2.0" and not errs:
        errs = board_errors(doc)
    return errs


def playable_errors(doc: Any) -> List[str]:
    """What stops this package from playing on the chalkboard: the validator, then (for v1) the board gates on its
    v2 form. Ingest calls this."""
    errs = validate_lesson_package(doc)
    if errs or doc.get("schema_version") == "2.0":
        return errs
    errs = validate_lesson_package(upgrade(doc))
    if errs:
        errs.append("v1 `visuals` are semantic and are not drawn on the chalkboard: add `board` (title, lines, draw) "
                    f"to each beat and set schema_version \"2.0\" ({SCHEMA_URL})")
    return errs


# ---------------------------------------------------------------------------------------------------------
# v1 -> v2
# ---------------------------------------------------------------------------------------------------------

def upgrade(doc: dict) -> dict:
    """Map a v1 package forward to v2 (`acts` folded into `chapters`; the unbounded v1-only fields dropped)."""
    out = copy.deepcopy(doc)
    if out.get("schema_version") == "2.0":
        return out
    out["schema_version"] = "2.0"
    if "acts" in out and "chapters" not in out:
        out["chapters"] = out.pop("acts")
    (out.get("problem") or {}).pop("param_spec", None)
    for ch in out.get("chapters") or []:
        for b in ch.get("beats") or []:
            b.pop("board_ops_compat", None)
    return out


def normalize_package(doc: dict) -> dict:
    """Canonical form: `acts` alias folded into `chapters`."""
    out = copy.deepcopy(doc)
    if "acts" in out and "chapters" not in out:
        out["chapters"] = out.pop("acts")
    return out


def strip_answers(doc: dict) -> dict:
    """Answer-free view: drops the assessment block and check-in answer keys."""
    out = copy.deepcopy(doc)
    (out.get("problem") or {}).pop("assessment", None)
    for ch in get_chapters(out):
        for b in ch["beats"]:
            (b.get("checkin") or {}).pop("correct_index", None)
    return out


# ---------------------------------------------------------------------------------------------------------
# Package -> the stored shape the lesson player serves
# ---------------------------------------------------------------------------------------------------------

def _esc_lines(lines: List[str]) -> str:
    """Written lines -> the board's html. THE escape: author text never reaches the page as markup."""
    return "".join(f"<p>{_html.escape(str(t), quote=True)}</p>" for t in lines if str(t).strip())


def _prose_html(prose: str) -> str:
    return _esc_lines([p.strip() for p in re.split(r"\n\s*\n", prose or "") if p.strip()])


def place_say(ops: List[dict], say: str, intent: str = "") -> None:
    """The beat's narration rides on its first op (the player speaks it as the hand starts to move); an op-less beat
    gets a bare pause to carry it. Same rule as the generated path (board_service._place_say)."""
    if not ops:
        ops.append({"op": "pause", "dur": 0})
    for j, op in enumerate(ops):
        if j == 0:
            op["say"] = say
            if intent:
                op["intent"] = intent
        else:
            op.pop("say", None)


def _swap_labels(ops: List[dict], swaps: Dict[str, str]) -> None:
    for o in _iter_ops(ops):
        for k in ("text", "tex"):
            if isinstance(o.get(k), str):
                for a, b in swaps.items():
                    o[k] = o[k].replace(a, b)


def _beat_view(beat: dict, ch: dict, persp: Optional[dict]) -> Dict[str, Any]:
    ov = ((persp or {}).get("beats") or {}).get(beat["id"]) or {}
    board = copy.deepcopy(ov.get("board") or beat.get("board") or {})
    nar = beat["narration"]
    say = ov.get("say") or nar["text"]
    ops = board.get("draw") or []
    if ov.get("label_swaps"):
        _swap_labels(ops, ov["label_swaps"])
    if ov.get("say") and not ov.get("board"):
        for o in _iter_ops(ops):
            o.pop("say", None)
    if not any(isinstance(o.get("say"), str) for o in _iter_ops(ops)):
        place_say(ops, say, nar.get("intent") or "")
    return {
        "title": ov.get("title") or board.get("title") or "",
        "lines": list(board.get("lines") or []),
        "ops": ops,
        "say": say,
        "intent": nar.get("intent") or "",
        "role": beat.get("role") or ch.get("role") or "",
        "prose": beat.get("prose") or "",
        "checkin": beat.get("checkin"),
    }


def _ask(ck: Optional[dict]) -> Optional[dict]:
    if not ck:
        return None
    ask: Dict[str, Any] = {"q": ck["prompt"], "choices": list(ck["choices"])}
    if ck.get("branches"):
        ask["branches"] = dict(ck["branches"])
    return ask


def package_to_board(doc: dict, perspective: Optional[str] = None) -> dict:
    """The chalkboard deck: one frame per beat — its written lines, its drawing, its spoken line(s), its check-in
    (question and choice texts only: the key never ships)."""
    doc = upgrade(doc)
    persp = (doc.get("perspectives") or {}).get(perspective) if perspective else None
    frames = []
    for ch in get_chapters(doc):
        for beat in ch["beats"]:
            v = _beat_view(beat, ch, persp)
            fr: Dict[str, Any] = {"title": v["title"], "html": _esc_lines(v["lines"]), "steps": v["ops"]}
            # the transport names its chapters from this (static/js/lesson/transport.js buildChapters): the lesson's
            # own chapter titles, not "Part 1" for a lesson whose beats carry no heading of their own
            if isinstance(ch.get("title"), str) and ch["title"].strip():
                fr["chapter"] = ch["title"].strip()
            if v["role"]:
                fr["role"] = v["role"]
            if v["lines"]:
                fr["chalk"] = True
            fr["scripted"] = True
            ask = _ask(v["checkin"])
            if ask:
                fr["ask"] = ask
            frames.append(fr)
    return {"w": BOARD_W, "h": BOARD_H, "frames": frames}


def package_to_cards(doc: dict, perspective: Optional[str] = None) -> List[dict]:
    """The reading deck (TutorLessonContent.lesson_cards): title, prose html, the chalk, the spoken line."""
    doc = upgrade(doc)
    persp = (doc.get("perspectives") or {}).get(perspective) if perspective else None
    cards = []
    for ch in get_chapters(doc):
        for beat in ch["beats"]:
            v = _beat_view(beat, ch, persp)
            card: Dict[str, Any] = {
                "title": v["title"] or ch["title"],
                "html": _prose_html(v["prose"]),   # never the narration: a player writes card html on the board
                "chalk": "\n".join(v["lines"]),
                "say": v["say"],
                "intent": v["intent"],
                "role": v["role"],
            }
            ask = _ask(v["checkin"])
            if ask:
                card["ask"] = {"q": ask["q"], "choices": ask["choices"]}
            cards.append(card)
    return cards


def spoken_lines(board: dict) -> List[str]:
    """Every line the board speaks, in order (op `say`s across frames)."""
    return [o["say"] for fr in board.get("frames") or [] for o in _iter_ops(fr.get("steps"))
            if isinstance(o.get("say"), str) and o["say"].strip()]
