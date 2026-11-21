"""LessonPackage v1 <-> tutor-content adapter and validator.

A LessonPackage is renderer-agnostic and TTS-agnostic: no pixel coordinates, no audio URLs, no clip hashes.
This module is deliberately stdlib-only (jsonschema is used when installed, a small built-in Draft 2020-12
subset otherwise) so the identical file is vendored into the public `didactum/lessons` CI.

Tutor content here is the frame-list shape the board player consumes:
    {"schema": "tutor_content/1", "id", "slug", "metadata", "problem", "problem_chapter_index"?,
     "perspectives"?, "chapters": [{id, role?, title, skippable?, duration_hint_s?}],
     "frames": [{"id", "chapter_id", "say", "cues", "pause_ms"?, "intent"?, "steps": [{"op": "visual", ...}],
                 "ask"?, "board_ops"?}]}
"""

from __future__ import annotations

import copy
import json
import os
import re
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1.0"
CHAPTER_ROLES = ("why", "history", "uses", "seek", "how", "check")
# Internal role labels (current and legacy DSS) that must never surface as a student-facing title.
RAW_ROLE_TOKENS = frozenset(CHAPTER_ROLES) | {
    "recite", "orient", "strategise", "strategize", "decompose", "solve", "synthesize", "synthesise",
    "miss", "sowhat", "so what", "intro", "introduction", "conclusion", "summary", "chapter", "act", "beat",
}
_PLACEHOLDER_TITLE_RE = re.compile(r"^(chapter|act|beat|step|part|stage|moment)\s*[#:]?\s*\d*$", re.I)
STEM_SUBJECTS = frozenset({
    "math", "maths", "mathematics", "algebra", "geometry", "trigonometry", "calculus", "statistics",
    "sat-math", "act-math", "physics", "chemistry", "stem",
})
_ANSWER_SKIP_KEYS = frozenset({"id", "type", "role", "region", "emphasis", "relative_to", "reveal_cue"})


# ---------------------------------------------------------------------------------------------------------
# JSON Schema
# ---------------------------------------------------------------------------------------------------------

def _find_schema_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for rel in (("..", "..", "..", "schemas"), ("..", "schema"), ("schema",), ("schemas",)):
        p = os.path.join(here, *rel, "lesson-package.v1.json")
        if os.path.isfile(p):
            return os.path.normpath(p)
    raise FileNotFoundError("lesson-package.v1.json not found next to package_adapter")


def load_schema(path: Optional[str] = None) -> dict:
    with open(path or _find_schema_path(), encoding="utf-8") as fh:
        return json.load(fh)


_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool, "null": type(None),
}


def _is_type(v: Any, t: str) -> bool:
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t])


def _mini_validate(inst: Any, schema: dict, root: dict, path: str, errs: List[str]) -> None:
    """Draft 2020-12 subset: exactly the keywords lesson-package.v1.json uses."""
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
        errs.append(f"{path}: {inst!r} not in {schema['enum']}")
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
            errs.append(f"{path}: longer than {schema['maxLength']}")
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
        if "items" in schema:
            for i, item in enumerate(inst):
                _mini_validate(item, schema["items"], root, f"{path}[{i}]", errs)
    if isinstance(inst, dict):
        for key in schema.get("required", []):
            if key not in inst:
                errs.append(f"{path}: missing required '{key}'")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, val in inst.items():
            if key in props:
                _mini_validate(val, props[key], root, f"{path}.{key}", errs)
            elif extra is False:
                errs.append(f"{path}: unexpected property '{key}'")
            elif isinstance(extra, dict):
                _mini_validate(val, extra, root, f"{path}.{key}", errs)


def schema_errors(doc: Any, schema: Optional[dict] = None) -> List[str]:
    schema = schema or load_schema()
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
# Semantic validation
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
                              _ANSWER_SKIP_KEYS | {"correct_index"}))
    seen.append((doc.get("problem") or {}).get("statement", ""))
    out = []
    for a in answers:
        for s in seen:
            if _contains_token(s, a):
                out.append(f"never-verbatim: answer {a!r} appears verbatim in {s[:60]!r}")
                break
    return out


def validate_lesson_package(doc: Any, schema: Optional[dict] = None) -> List[str]:
    """Return a list of problems; an empty list means the package is valid."""
    if not isinstance(doc, dict):
        return ["$: package must be a JSON object"]
    errs = schema_errors(doc, schema)
    if errs:
        return errs  # semantic checks assume a structurally sound document
    chapters = get_chapters(doc)
    meta = doc["metadata"]
    seen_ids: set = set()
    visual_count = 0
    for ci, ch in enumerate(chapters):
        if ch["id"] in seen_ids:
            errs.append(f"chapters[{ci}]: duplicate id {ch['id']!r}")
        seen_ids.add(ch["id"])
        msg = _title_error(ch["title"])
        if msg:
            errs.append(f"chapters[{ci}]: {msg}")
        for bi, beat in enumerate(ch["beats"]):
            where = f"chapters[{ci}].beats[{bi}]"
            if beat["id"] in seen_ids:
                errs.append(f"{where}: duplicate id {beat['id']!r}")
            seen_ids.add(beat["id"])
            visual_count += len(beat.get("visuals") or [])
            nar = beat["narration"]
            words = len(nar["text"].split())
            for cue in nar.get("cues") or []:
                if cue["word_index"] > words:
                    errs.append(f"{where}: cue {cue['id']!r} word_index {cue['word_index']} beyond {words} words")
            if re.search(r"https?://\S+\.(mp3|wav|ogg|m4a|opus|webm)\b", nar["text"], re.I):
                errs.append(f"{where}: narration must not reference provider audio")
            ci_ = beat.get("checkin")
            if ci_ and "correct_index" in ci_ and ci_["correct_index"] >= len(ci_["choices"]):
                errs.append(f"{where}: checkin.correct_index out of range")
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
    errs.extend(never_verbatim_leaks(doc))
    return errs


def strip_answers(doc: dict) -> dict:
    """Answer-free view: drops the assessment block and check-in answer keys."""
    out = copy.deepcopy(doc)
    (out.get("problem") or {}).pop("assessment", None)
    for ch in get_chapters(out):
        for b in ch["beats"]:
            (b.get("checkin") or {}).pop("correct_index", None)
    return out


# ---------------------------------------------------------------------------------------------------------
# Bidirectional adapter
# ---------------------------------------------------------------------------------------------------------

_CHAPTER_META_KEYS = ("id", "role", "title", "skippable", "duration_hint_s")


def tutor_content_to_package(content: dict) -> dict:
    """Inverse of package_to_tutor_content (tutor content must carry the package-derived structure)."""
    if content.get("schema") != "tutor_content/1":
        raise ValueError("not tutor_content/1")
    chapters = []
    by_id: Dict[str, dict] = {}
    for meta in content["chapters"]:
        ch = {k: meta[k] for k in _CHAPTER_META_KEYS if k in meta}
        ch["beats"] = []
        chapters.append(ch)
        by_id[ch["id"]] = ch
    for fr in content["frames"]:
        nar: Dict[str, Any] = {"text": fr["say"]}
        if fr.get("cues"):
            nar["cues"] = copy.deepcopy(fr["cues"])
        if "pause_ms" in fr:
            nar["pause_ms"] = fr["pause_ms"]
        if "intent" in fr:
            nar["intent"] = fr["intent"]
        beat: Dict[str, Any] = {"id": fr["id"], "narration": nar}
        visuals = [copy.deepcopy(s["visual"]) for s in fr.get("steps", []) if s.get("op") == "visual"]
        if visuals:
            beat["visuals"] = visuals
        if fr.get("ask"):
            ask = fr["ask"]
            ci: Dict[str, Any] = {"prompt": ask["q"], "choices": list(ask["choices"])}
            if "hints" in ask:
                ci["hints"] = list(ask["hints"])
            if "correct_index" in ask:
                ci["correct_index"] = ask["correct_index"]
            beat["checkin"] = ci
        if fr.get("board_ops"):
            beat["board_ops_compat"] = copy.deepcopy(fr["board_ops"])
        by_id[fr["chapter_id"]]["beats"].append(beat)
    doc: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "id": content["id"], "slug": content["slug"],
        "metadata": copy.deepcopy(content["metadata"]), "problem": copy.deepcopy(content["problem"]),
    }
    if "problem_chapter_index" in content:
        doc["problem_chapter_index"] = content["problem_chapter_index"]
    doc["chapters"] = chapters
    if content.get("perspectives"):
        doc["perspectives"] = copy.deepcopy(content["perspectives"])
    return doc


def package_to_tutor_content(doc: dict) -> dict:
    """One beat -> one frame; visuals become semantic steps (no coordinates are invented here)."""
    frames = []
    for ch in get_chapters(doc):
        for b in ch["beats"]:
            nar = b["narration"]
            fr: Dict[str, Any] = {
                "id": b["id"], "chapter_id": ch["id"], "say": nar["text"],
                "cues": copy.deepcopy(nar.get("cues") or []),
                "steps": [{"op": "visual", "visual": copy.deepcopy(v)} for v in b.get("visuals") or []],
            }
            if "pause_ms" in nar:
                fr["pause_ms"] = nar["pause_ms"]
            if "intent" in nar:
                fr["intent"] = nar["intent"]
            ci = b.get("checkin")
            if ci:
                ask: Dict[str, Any] = {"q": ci["prompt"], "choices": list(ci["choices"])}
                if "hints" in ci:
                    ask["hints"] = list(ci["hints"])
                if "correct_index" in ci:
                    ask["correct_index"] = ci["correct_index"]
                fr["ask"] = ask
            if b.get("board_ops_compat"):
                fr["board_ops"] = copy.deepcopy(b["board_ops_compat"])
            frames.append(fr)
    content: Dict[str, Any] = {
        "schema": "tutor_content/1", "id": doc["id"], "slug": doc["slug"],
        "metadata": copy.deepcopy(doc["metadata"]), "problem": copy.deepcopy(doc["problem"]),
        "chapters": [{k: ch[k] for k in _CHAPTER_META_KEYS if k in ch} for ch in get_chapters(doc)],
        "frames": frames,
    }
    if "problem_chapter_index" in doc:
        content["problem_chapter_index"] = doc["problem_chapter_index"]
    if doc.get("perspectives"):
        content["perspectives"] = copy.deepcopy(doc["perspectives"])
    return content


def normalize_package(doc: dict) -> dict:
    """Canonical form: `acts` alias folded into `chapters`."""
    out = copy.deepcopy(doc)
    if "acts" in out and "chapters" not in out:
        out["chapters"] = out.pop("acts")
    return out
