#!/usr/bin/env python3
"""Fast (<1s) offline validator for didactum: 1 artifacts (.json, .yaml/.yml, .score)
AND backwards-compatible legacy lesson-package.v2.json files.

Works both inside didactum-org (using app.services.lesson_score) and standalone
when cloned publicly as didactum/lessons (pure stdlib + bundled schema/didactum-v1/).

Usage:
    python3 scripts/didactum_validate.py [path...] [--json]
    python3 scripts/didactum_validate.py --scan-tree . --enforce-identity --json

Exit codes:
    0 — valid (zero errors; warnings may be present)
    1 — validation error(s) found
    2 — usage or file-read error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

HERE = Path(__file__).resolve().parent
ECO_ROOT = HERE.parent
SCHEMA_DIR = ECO_ROOT / "schema" / "didactum-v1"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import _package_adapter as legacy_adapter  # noqa: E402

_SUPPORTED_EXTS = frozenset({".json", ".yaml", ".yml", ".score"})

MAX_BLOB_BYTES = 102_400  # 100 KB
_FORBIDDEN_BLOB_EXTS = frozenset({
    ".glb", ".gltf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".ico",
    ".wav", ".mp3", ".m4a", ".ogg", ".opus", ".flac", ".aac",
    ".mp4", ".webm", ".mov", ".avi",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".wasm",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".pyc", ".pdf",
})
_EXECUTABLE_EXTS = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".sh", ".bash", ".zsh", ".fish", ".rb", ".pl", ".php", ".go", ".rs", ".c", ".cpp",
})
_DEFAULT_MAINTAINERS = frozenset({"teetra", "didactum-bot", "didactum"})

_ARTIFACT_ID_RE = re.compile(
    r"^(?:@[a-z0-9][a-z0-9_-]{0,63}|didactum)/[a-z0-9][a-z0-9._-]{0,127}$"
)
_FILE_EXT_IN_ID_RE = re.compile(r"\.(?:json|ya?ml|score|md|txt|py|js|ts|toml)$", re.I)
_OFFLINE_SCHEMA_RE = re.compile(
    r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*@[0-9]+(?:\.[0-9]+)*$"
)
_LIVE_URL_RE = re.compile(r"(?i)^(?:https?|ftp|file|ws|wss|data)://")
_BCP47_RE = re.compile(
    r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?(?:-[A-Za-z0-9]{5,8}|-[0-9][A-Za-z0-9]{3})*$"
)
_CONCEPT_ID_RE = re.compile(r"^concept:[a-z0-9][a-z0-9_-]*$")
_DRIVER_RE = re.compile(r"^(?:voice|learner|asset:[a-zA-Z0-9@_./:-]+|timer:[1-9][0-9]*)$")

CLOSED_OPS = frozenset({
    "say.replace",
    "say.aside",
    "say.aside(before)",
    "say.aside(after)",
    "say.direct",
    "node.set",
    "chapter.replace",
    "param.set",
    "meta.set",
})
NODE_KINDS = frozenset({"chalk_2d", "mesh_3d", "camera_3d", "clip_plane", "audio", "passage", "sim"})
TEXT_BEARING_KINDS = frozenset({"lesson", "overlay", "concept", "course"})
FORBIDDEN_BIOMETRIC_KINDS = frozenset({
    "voice-clone", "voice_clone", "voice-sample", "voice_sample",
    "voice-weights", "voice_weights", "speaker-embedding", "speaker_embedding",
    "face-weights", "face_weights", "face-model", "face_model",
    "face-lora", "face_lora", "biometric", "biometric-weights", "biometric_weights",
    "likeness", "real-human-voice", "real-human-face",
})
FORBIDDEN_BIOMETRIC_MIME_PREFIXES = (
    "application/x-voice-clone", "application/x-voice-weights", "application/x-speaker-embedding",
    "application/x-face-weights", "application/x-face-model", "application/x-biometric",
    "audio/x-voice-clone", "audio/x-voice-sample", "model/x-face-weights", "model/x-biometric",
)

_EN_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_EN_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_EN_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}
_EN_SPECIAL_FRACS = {
    "half": "1/2", "halves": "1/2", "quarter": "1/4", "quarters": "1/4",
    "third": "1/3", "thirds": "1/3", "fourth": "1/4", "fourths": "1/4",
    "fifth": "1/5", "fifths": "1/5", "sixth": "1/6", "sixths": "1/6",
    "eighth": "1/8", "eighths": "1/8", "tenth": "1/10", "tenths": "1/10",
    "double": "2", "twice": "2", "triple": "3", "thrice": "3", "quadruple": "4",
}
_ES_NUMBERS = {
    "cero": "0", "uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5",
    "seis": "6", "siete": "7", "ocho": "8", "nueve": "9", "diez": "10",
    "once": "11", "doce": "12", "trece": "13", "catorce": "14", "quince": "15",
    "veinte": "20", "treinta": "30", "cuarenta": "40", "cincuenta": "50",
    "sesenta": "60", "setenta": "70", "ochenta": "80", "noventa": "90",
    "cien": "100", "ciento": "100", "mil": "1000",
    "mitad": "1/2", "tercio": "1/3", "cuarto": "1/4", "doble": "2", "triple": "3",
}
_NUM_TOKEN_RE = re.compile(
    r"(?:(?<![A-Za-z0-9_])-?\d+(?:,\d{3})*(?:/\d+|\.\d+)?)"
    r"|(?:[A-Za-z\u00C0-\u024F]+(?:-[A-Za-z\u00C0-\u024F]+)*)"
)
_FORBIDDEN_EXPR_CHARS = frozenset('"\'`;[]{}\\$@#')
_FORBIDDEN_EXPR_IDENTS = frozenset({
    "eval", "exec", "compile", "open", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "dir", "type", "object", "breakpoint",
    "input", "import", "lambda", "def", "class", "while", "for", "return",
    "yield", "raise", "try", "except", "with", "assert", "del", "pass",
    "__import__", "__builtins__", "__class__", "__subclasses__", "__globals__",
})


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _diag(
    code: str,
    severity: str,
    artifact: str,
    address: str,
    pointer: str,
    message: str,
    fix: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "artifact": artifact,
        "address": address,
        "pointer": pointer,
        "message": message,
        "fix": list(fix) if fix else [],
    }


def _find_app_root() -> Optional[Path]:
    for anc in HERE.parents:
        if (anc / "app" / "services" / "lesson_score" / "validator.py").is_file():
            return anc
    return None


# ── Standalone schema + semantic fallback (when cloned publicly without app/) ─

_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}
_KIND_SCHEMA_FILES = {"lesson": "lesson.v3.json", "overlay": "overlay.v1.json", "asset": "asset.v1.json"}


def _load_schema(name: str) -> Dict[str, Any]:
    if name not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[name] = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[name]


def _matches_type(inst: Any, typ: str) -> bool:
    if typ == "integer":
        return isinstance(inst, int) and not isinstance(inst, bool)
    if typ == "number":
        return isinstance(inst, (int, float)) and not isinstance(inst, bool)
    return isinstance(inst, {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}.get(typ, object))


def _resolve_ref(ref: str, root: Mapping[str, Any]) -> Mapping[str, Any]:
    node: Any = root
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def _validate_node(inst: Any, schema: Mapping[str, Any], root: Mapping[str, Any], pointer: str, errs: List[Tuple[str, str]]) -> None:
    if "$ref" in schema:
        _validate_node(inst, _resolve_ref(schema["$ref"], root), root, pointer, errs)
        return
    if "const" in schema:
        exp = schema["const"]
        if (type(inst) is bool) != (type(exp) is bool) or inst != exp:
            errs.append((pointer, f"must equal {exp!r}, got {inst!r}"))
            return
    if "enum" in schema and inst not in schema["enum"]:
        errs.append((pointer, f"{inst!r} is not one of {schema['enum']}"))
        return
    typ = schema.get("type")
    if isinstance(typ, str) and not _matches_type(inst, typ):
        errs.append((pointer, f"expected type {typ!r}, got {type(inst).__name__}"))
        return
    if "not" in schema:
        sub_e: List[Tuple[str, str]] = []
        _validate_node(inst, schema["not"], root, pointer, sub_e)
        if not sub_e:
            errs.append((pointer, "violated 'not' schema constraint"))
    if "allOf" in schema:
        for sub in schema["allOf"]:
            _validate_node(inst, sub, root, pointer, errs)
    if "anyOf" in schema:
        if not any(not (lambda e: (_validate_node(inst, s, root, pointer, e), e)[1])([]) for s in schema["anyOf"]):
            errs.append((pointer, "failed all branches of 'anyOf'"))
    if "if" in schema:
        cond_e: List[Tuple[str, str]] = []
        _validate_node(inst, schema["if"], root, pointer, cond_e)
        if not cond_e and "then" in schema:
            _validate_node(inst, schema["then"], root, pointer, errs)
        elif cond_e and "else" in schema:
            _validate_node(inst, schema["else"], root, pointer, errs)
    if isinstance(inst, str):
        if "minLength" in schema and len(inst) < schema["minLength"]:
            errs.append((pointer, f"string shorter than minLength {schema['minLength']}"))
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            errs.append((pointer, f"string longer than maxLength {schema['maxLength']}"))
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            errs.append((pointer, f"string {inst!r} does not match pattern {schema['pattern']!r}"))
    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if "minimum" in schema and inst < schema["minimum"]:
            errs.append((pointer, f"value {inst} < minimum {schema['minimum']}"))
        if "maximum" in schema and inst > schema["maximum"]:
            errs.append((pointer, f"value {inst} > maximum {schema['maximum']}"))
    if isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            errs.append((pointer, f"array has {len(inst)} items, minimum is {schema['minItems']}"))
        if "maxItems" in schema and len(inst) > schema["maxItems"]:
            errs.append((pointer, f"array has {len(inst)} items, maximum is {schema['maxItems']}"))
        if isinstance(schema.get("items"), Mapping):
            for idx, item in enumerate(inst):
                _validate_node(item, schema["items"], root, f"{pointer}/{idx}", errs)
    if isinstance(inst, Mapping):
        for req in schema.get("required") or []:
            if req not in inst:
                errs.append((f"{pointer}/{req}" if pointer else f"/{req}", f"missing required property {req!r}"))
        props = schema.get("properties") or {}
        for k, sub in props.items():
            if k in inst:
                _validate_node(inst[k], sub, root, f"{pointer}/{k}" if pointer else f"/{k}", errs)
        addl = schema.get("additionalProperties", True)
        if addl is False:
            for k in inst:
                if k not in props:
                    errs.append((f"{pointer}/{k}", f"unexpected additional property {k!r}"))
        elif isinstance(addl, Mapping):
            for k, v in inst.items():
                if k not in props:
                    _validate_node(v, addl, root, f"{pointer}/{k}", errs)


def _extract_numerals(text: str) -> Counter:
    counts: Counter = Counter()
    for tok in _NUM_TOKEN_RE.findall(_nfc(text or "")):
        if re.fullmatch(r"-?\d+(?:,\d{3})*(?:/\d+|\.\d+)?", tok):
            cleaned = tok.replace(",", "")
            try:
                f = Fraction(cleaned)
                counts[str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"] += 1
            except (ValueError, ZeroDivisionError):
                counts[cleaned] += 1
        else:
            for part in tok.lower().split("-"):
                if part in _EN_UNITS:
                    counts[str(_EN_UNITS[part])] += 1
                elif part in _EN_TENS:
                    counts[str(_EN_TENS[part])] += 1
                elif part in _EN_SCALES:
                    counts[str(_EN_SCALES[part])] += 1
                elif part in _EN_SPECIAL_FRACS:
                    counts[_EN_SPECIAL_FRACS[part]] += 1
                elif part in _ES_NUMBERS:
                    counts[_ES_NUMBERS[part]] += 1
    return counts


def _has_numeric(text: str) -> bool:
    return bool(re.search(r"\d", text or "") or _extract_numerals(text))


def _is_valid_id(val: Any) -> bool:
    if not isinstance(val, str) or not val:
        return False
    s = _nfc(val)
    if ".." in s or "\\" in s or s.startswith("/") or _FILE_EXT_IN_ID_RE.search(s):
        return False
    return bool(_ARTIFACT_ID_RE.fullmatch(s))


def _is_biometric(doc: Mapping[str, Any]) -> Optional[str]:
    if doc.get("kind") != "asset":
        return None
    payload = doc.get("payload") if isinstance(doc.get("payload"), Mapping) else {}
    for c in (doc, payload):
        if c.get("biometric_likeness") is True:
            return "biometric_likeness: true is forbidden in kind: asset"
        for k in ("asset_kind", "subtype", "asset_type", "role"):
            v = c.get(k)
            if isinstance(v, str) and v.strip().lower() in FORBIDDEN_BIOMETRIC_KINDS:
                return f"forbidden biometric asset {k}={v!r}"
        for k in ("mime", "media_type", "content_type"):
            v = c.get(k)
            if isinstance(v, str):
                lv = v.strip().lower()
                if any(lv.startswith(p) for p in FORBIDDEN_BIOMETRIC_MIME_PREFIXES) or any(
                    tok in lv for tok in ("voice-clone", "face-weight", "biometric", "speaker-embedding")
                ):
                    return f"forbidden biometric MIME type {v!r}"
    return None


def _check_expr_standalone(expr: str, art_id: str, addr: str, ptr: str) -> List[Dict[str, Any]]:
    if len(expr) > 2048:
        return [_diag("DID-E008", "error", art_id, addr, ptr, "Expression exceeds 2048 characters.")]
    for ch in expr:
        if ch in _FORBIDDEN_EXPR_CHARS:
            return [_diag("DID-E007", "error", art_id, addr, ptr, f"Unsafe character {ch!r} in expression.")]
    stripped_dots = re.sub(r"\.\.", " ", re.sub(r"\b\d+\.\d+\b", "0", expr))
    if "." in stripped_dots:
        return [_diag("DID-E007", "error", art_id, addr, ptr, "Attribute access '.' is forbidden in expression.")]
    if re.search(r"(?<![=!<>])=(?!=)", expr):
        return [_diag("DID-E007", "error", art_id, addr, ptr, "Assignment '=' is forbidden; use '==' for equality.")]
    for ident in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr):
        if ident.startswith("__") or ident in _FORBIDDEN_EXPR_IDENTS:
            return [_diag("DID-E007", "error", art_id, addr, ptr, f"Forbidden identifier {ident!r} in expression.")]
    for m in re.finditer(r"(?:forall|exists)\s+[A-Za-z_][A-Za-z0-9_]*\s+in\s+(-?\d+)\.\.(-?\d+)", expr):
        if int(m.group(2)) - int(m.group(1)) + 1 > 1000:
            return [_diag("DID-E008", "error", art_id, addr, ptr, "Quantifier exceeds MAX_STEPS=1000.")]
    for m in re.finditer(r"\*\*\s*(-?\d+)", expr):
        if abs(int(m.group(1))) > 20:
            return [_diag("DID-E008", "error", art_id, addr, ptr, "Exponent exceeds MAX_EXPONENT=20.")]
    return []


def _standalone_parse_score(raw: str, path: Path) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"teaches": [], "prereqs": [], "truth_checks": [], "params": {}}
    chapters: List[Dict[str, Any]] = []
    cur_ch: Optional[Dict[str, Any]] = None
    cur_lines: List[Dict[str, Any]] = []
    for raw_ln in raw.splitlines():
        s = raw_ln.strip()
        if not s or s.startswith("<!--") or s.startswith("```"):
            continue
        if s.startswith("##"):
            if cur_ch is not None:
                cur_ch["beats"] = [{"id": f"{cur_ch['id']}.b1", "driver": "voice", "lines": cur_lines or [{"text": cur_ch["title"]}]}]
                chapters.append(cur_ch)
            cur_lines = []
            cid = f"c{len(chapters) + 1}"
            cur_ch = {"id": cid, "title": s.lstrip("#").strip()}
            continue
        if cur_ch is None and ":" in s:
            k, v = s.split(":", 1)
            k, v = k.strip().upper(), v.strip()
            if k == "ID":
                meta["id"] = v
            elif k == "LANG":
                meta["lang"] = v
            elif k == "SLUG":
                meta["slug"] = v
            elif k == "TITLE":
                meta["title"] = v
            elif k == "PROBLEM":
                meta["problem"] = v
            elif k == "TEACHES":
                meta["teaches"].extend([x.strip() for x in v.split(",") if x.strip()])
            elif k == "PREREQS":
                meta["prereqs"].extend([x.strip() for x in v.split(",") if x.strip()])
            elif k in ("TRUTH_CHECK", "TRUTH_CHECKS"):
                meta["truth_checks"].append(v)
        elif cur_ch is not None and re.match(r"^(?:- )?SAY(?:\s*\[[^\]]+\])?\s*:", s):
            txt = s.split(":", 1)[1].strip()
            if txt:
                cur_lines.append({"id": f"{cur_ch['id']}.b1.l{len(cur_lines) + 1}", "text": txt})
    if cur_ch is not None:
        cur_ch["beats"] = [{"id": f"{cur_ch['id']}.b1", "driver": "voice", "lines": cur_lines or [{"text": cur_ch["title"]}]}]
        chapters.append(cur_ch)
    slug = meta.get("slug") or path.stem
    return {
        "didactum": 1,
        "id": meta.get("id") or f"didactum/{slug}",
        "kind": "lesson",
        "kind_schema": "didactum.kind/lesson@3",
        "lang": meta.get("lang") or "en",
        "teaches": meta["teaches"] or [f"concept:{slug}"],
        "prereqs": meta["prereqs"],
        "payload": {
            "meta": {"title": meta.get("title", slug), "problem": meta.get("problem", "")},
            "params": meta["params"],
            "truth_checks": meta["truth_checks"],
            "chapters": chapters,
        },
    }


def _standalone_validate_artifacts(docs: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    diags: List[Dict[str, Any]] = []
    env_schema = _load_schema("envelope.v1.json")
    for idx, doc in enumerate(docs):
        peers = [d for j, d in enumerate(docs) if j != idx]
        art_id = _nfc(str(doc.get("id") or "<unnamed>"))
        kind = _nfc(str(doc.get("kind") or ""))

        if doc.get("didactum") != 1 or isinstance(doc.get("didactum"), bool):
            diags.append(_diag("DID-E001", "error", art_id, "#meta.didactum", "/didactum",
                               f"Expected didactum: 1, got {doc.get('didactum')!r}.",
                               [{"op": "meta.set", "address": "#meta.didactum", "value": 1}]))
        if "version" in doc:
            diags.append(_diag("DID-E002", "error", art_id, "#meta.version", "/version",
                               "Authored 'version' field is forbidden on didactum: 1 artifacts; revisions are content digests.",
                               [{"op": "meta.set", "address": "#meta.version", "value": None}]))
        if "license" in doc and kind != "asset":
            diags.append(_diag("DID-E003", "error", art_id, "#meta.license", "/license",
                               f"Per-artifact 'license' is forbidden on kind={kind!r}; permitted only on kind='asset'.",
                               [{"op": "meta.set", "address": "#meta.license", "value": None}]))
        if not _is_valid_id(doc.get("id")):
            diags.append(_diag("DID-E014", "error", art_id, "#meta.id", "/id",
                               f"Invalid artifact id {doc.get('id')!r}; expected '@<ns>/<slug>' or 'didactum/<slug>' (id != path)."))
        ks = doc.get("kind_schema")
        if not isinstance(ks, str) or _LIVE_URL_RE.match(ks.strip()) or "://" in ks or not _OFFLINE_SCHEMA_RE.fullmatch(_nfc(ks.strip())):
            sug = f"didactum.kind/{kind or 'lesson'}@{'3' if kind == 'lesson' else '1'}"
            diags.append(_diag("DID-E004", "error", art_id, "#meta.kind_schema", "/kind_schema",
                               f"Invalid kind_schema {ks!r}; must be an offline name (e.g. {sug!r}), live URLs are forbidden.",
                               [{"op": "meta.set", "address": "#meta.kind_schema", "value": sug}]))
        payload = doc.get("payload") if isinstance(doc.get("payload"), Mapping) else {}
        is_text = kind in TEXT_BEARING_KINDS or any(k in payload for k in ("chapters", "text", "title", "statement"))
        lang = doc.get("lang")
        if is_text and not lang:
            diags.append(_diag("DID-E005", "error", art_id, "#meta.lang", "/lang",
                               f"Missing required BCP-47 'lang' on text-bearing artifact {art_id!r}.",
                               [{"op": "meta.set", "address": "#meta.lang", "value": "en"}]))
        elif lang is not None and (not isinstance(lang, str) or not _BCP47_RE.fullmatch(_nfc(lang))):
            diags.append(_diag("DID-E005", "error", art_id, "#meta.lang", "/lang",
                               f"Invalid BCP-47 language tag {lang!r}.",
                               [{"op": "meta.set", "address": "#meta.lang", "value": "en"}]))
        for fn in ("teaches", "prereqs"):
            vals = doc.get(fn)
            if isinstance(vals, list):
                for ci, cid in enumerate(vals):
                    if not isinstance(cid, str) or not _CONCEPT_ID_RE.fullmatch(_nfc(cid)):
                        clean = re.sub(r"[^a-z0-9_-]+", "-", str(cid).lower()).strip("-") or "concept"
                        diags.append(_diag("DID-E001", "error", art_id, f"#meta.{fn}", f"/{fn}/{ci}",
                                           f"Invalid concept ID {cid!r}; expected 'concept:<slug>'.",
                                           [{"op": "meta.set", "address": f"#meta.{fn}", "value": f"concept:{clean}"}]))
        bio = _is_biometric(doc)
        if bio:
            diags.append(_diag("DID-E006", "error", art_id, "#asset.biometric", "/payload", bio))

        handled = {"/didactum", "/version", "/license", "/id", "/kind_schema", "/lang"}
        schema_errs: List[Tuple[str, str]] = []
        _validate_node(doc, env_schema, env_schema, "", schema_errs)
        for ptr, msg in schema_errs:
            if ptr in handled or (ptr == "" and "not" in msg and ("version" in doc or ("license" in doc and kind != "asset"))):
                continue
            diags.append(_diag("DID-E001", "error", art_id, f"#schema{ptr}", ptr, f"Envelope schema: {msg}"))
        if kind in _KIND_SCHEMA_FILES:
            ks_obj = _load_schema(_KIND_SCHEMA_FILES[kind])
            k_errs: List[Tuple[str, str]] = []
            _validate_node(doc, ks_obj, ks_obj, "", k_errs)
            for ptr, msg in k_errs:
                if ptr in handled or (kind == "asset" and bio and ("biometric" in ptr or "asset_kind" in ptr)):
                    continue
                diags.append(_diag("DID-E001", "error", art_id, f"#schema{ptr}", ptr, f"{kind} schema: {msg}"))

        if kind == "lesson":
            for ti, tc in enumerate(payload.get("truth_checks") or []):
                if not isinstance(tc, str):
                    diags.append(_diag("DID-E007", "error", art_id, f"#truth_checks/{ti}", f"/payload/truth_checks/{ti}", "TRUTH_CHECK must be a string."))
                else:
                    diags.extend(_check_expr_standalone(tc, art_id, f"#truth_checks/{ti}", f"/payload/truth_checks/{ti}"))
            for ci, ch in enumerate(payload.get("chapters") or []):
                if not isinstance(ch, Mapping):
                    continue
                for bi, bt in enumerate(ch.get("beats") or []):
                    if not isinstance(bt, Mapping):
                        continue
                    drv = bt.get("driver", "voice")
                    if not isinstance(drv, str) or not _DRIVER_RE.fullmatch(drv):
                        diags.append(_diag("DID-E001", "error", art_id, f"#{bt.get('id', 'beat')}",
                                           f"/payload/chapters/{ci}/beats/{bi}/driver", f"Invalid beat driver {drv!r}."))
                    for ni, nd in enumerate(bt.get("nodes") or []):
                        if isinstance(nd, Mapping) and nd.get("kind", "chalk_2d") not in NODE_KINDS:
                            diags.append(_diag("DID-E001", "error", art_id, f"#{nd.get('id', 'node')}",
                                               f"/payload/chapters/{ci}/beats/{bi}/nodes/{ni}/kind", f"Unsupported node kind {nd.get('kind')!r}."))

        if kind == "overlay":
            ops = payload.get("ops") if isinstance(payload.get("ops"), list) else []
            for oi, op_entry in enumerate(ops):
                if not isinstance(op_entry, Mapping):
                    continue
                raw_op = str(op_entry.get("op", ""))
                addr = _nfc(str(op_entry.get("address") or op_entry.get("target") or ""))
                ptr = f"/payload/ops/{oi}"
                if raw_op not in CLOSED_OPS:
                    diags.append(_diag("DID-E009", "error", art_id, addr or "#op", ptr, f"Op {raw_op!r} is not in the 7 closed overlay ops."))
                    continue
                if raw_op.startswith("say.aside"):
                    txt = _nfc(str(op_entry.get("text") or op_entry.get("value") or ""))
                    if _has_numeric(txt):
                        cleaned = re.sub(r"\s{2,}", " ", re.sub(r"\b\d+(?:[.,/]\d+)?%?\b", "", txt)).strip(" ,;:-") or "Take a moment to check."
                        pos = "before" if "before" in raw_op else str(op_entry.get("position") or "after")
                        diags.append(_diag("DID-E012", "error", art_id, addr, ptr,
                                           f"say.aside must be number-free; found numeric quantity in {txt!r}.",
                                           [{"op": "say.aside", "position": pos, "address": addr, "text": cleaned}]))

        if kind == "alias":
            src = payload.get("from")
            dst = payload.get("to") or payload.get("expands_to")
            if isinstance(src, str) and ":" in src and isinstance(dst, Mapping):
                fk = src.split(":", 1)[0]
                if fk in dst and f"{fk}:{dst[fk]}" == src:
                    diags.append(_diag("DID-E015", "error", art_id, f"#alias/{fk}", "/payload/to", "Self-referential alias cycle detected."))
                for peer in peers:
                    if peer.get("kind") == "alias" and isinstance(peer.get("payload"), Mapping):
                        psrc = peer["payload"].get("from")
                        pdst = peer["payload"].get("to")
                        if isinstance(psrc, str) and ":" in psrc and isinstance(pdst, Mapping):
                            pk, pv = psrc.split(":", 1)
                            if dst.get(pk) == pv and f"{fk}:{pdst.get(fk)}" == src:
                                diags.append(_diag("DID-E015", "error", art_id, f"#alias/{fk}", "/payload/to", "Alias cycle detected with peer alias."))
    return diags


# ── Identity binding & repo blob/executable guards ───────────────────────────

def check_identity_binding(
    doc: Mapping[str, Any],
    artifact_ref: str,
    *,
    actor_id: Optional[str] = None,
    actor: Optional[str] = None,
    maintainers: Sequence[str] = tuple(_DEFAULT_MAINTAINERS),
    contributor_map: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Enforce `didactum/*` maintainer-only and community `@gh-<actor_id>` / mapped-handle binding."""
    art_id = _nfc(str(doc.get("id") or ""))
    if not art_id:
        return []
    maint_set = {m.strip().lower() for m in maintainers if m.strip()}
    actor_norm = (actor or "").strip().lower()
    is_maintainer = bool(actor_norm and actor_norm in maint_set)

    if art_id.startswith("didactum/"):
        if not is_maintainer:
            return [_diag(
                "DID-E016", "error", art_id, "#meta.id", "/id",
                f"Namespace 'didactum/*' on {artifact_ref} is maintainer-only (actor={actor or '<none>'!r}). "
                f"Use '@gh-{actor_id or '<github_actor_id>'}/<slug>' for community PRs.",
            )]
        return []

    if art_id.startswith("@") and "/" in art_id and not is_maintainer:
        ns = art_id[1:].split("/", 1)[0]
        allowed: Set[str] = set()
        if actor_id:
            aid_s = str(actor_id).strip()
            if aid_s:
                allowed.add(f"gh-{aid_s}")
                allowed.add(aid_s)
            if contributor_map and aid_s in contributor_map:
                allowed.add(str(contributor_map[aid_s]).lstrip("@").lower())
        if allowed and ns.lower() not in allowed:
            return [_diag(
                "DID-E016", "error", art_id, "#meta.id", "/id",
                f"Community PR namespace '@{ns}' on {artifact_ref} does not match actor_id={actor_id!r} "
                f"(expected one of {sorted('@' + a for a in allowed)}).",
            )]
    return []


def check_file_security(path: Path, repo_root: Path) -> List[Dict[str, Any]]:
    """Reject binary blobs (>100 KB or binary media extensions) and executable code outside scripts/."""
    diags: List[Dict[str, Any]] = []
    try:
        rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        rel = path.name
    suffix = path.suffix.lower()

    if suffix in _FORBIDDEN_BLOB_EXTS:
        diags.append(_diag(
            "DID-E017", "error", rel, "#repo.blob", "",
            f"Binary blob extension {suffix!r} is forbidden in git ({rel}); commit metadata-only kind: asset instead.",
        ))
        return diags

    try:
        size = path.stat().st_size
    except OSError as exc:
        diags.append(_diag("DID-E000", "error", rel, "#file", "", str(exc)))
        return diags

    if size > MAX_BLOB_BYTES:
        diags.append(_diag(
            "DID-E017", "error", rel, "#repo.blob", "",
            f"File {rel} is {size} bytes (> {MAX_BLOB_BYTES} bytes / 100 KB limit); binary blobs are forbidden in git.",
        ))

    in_scripts = rel.startswith("scripts/")
    if not in_scripts:
        if suffix in _EXECUTABLE_EXTS:
            diags.append(_diag(
                "DID-E018", "error", rel, "#repo.executable", "",
                f"Executable code file {rel} ({suffix}) is forbidden outside scripts/.",
            ))
        elif not rel.startswith(".github/"):
            try:
                head = path.read_bytes()[:512]
                if b"\x00" in head:
                    diags.append(_diag("DID-E017", "error", rel, "#repo.blob", "", f"Binary NUL bytes detected in {rel}."))
                elif head.startswith(b"#!") or os.access(path, os.X_OK):
                    diags.append(_diag("DID-E018", "error", rel, "#repo.executable", "", f"Executable file/shebang forbidden outside scripts/: {rel}."))
            except OSError:
                pass
    return diags


# ── Collection, loading & main entry point ───────────────────────────────────

def _collect_paths(raw_paths: Sequence[str], *, check_blobs: bool = False) -> Tuple[List[Path], List[Path], List[str]]:
    artifact_files: List[Path] = []
    all_files: List[Path] = []
    errors: List[str] = []
    for rp in raw_paths:
        p = Path(rp)
        if not p.exists():
            errors.append(f"path not found: {rp}")
            continue
        if p.is_dir():
            for child in sorted(p.rglob("*")):
                if any(part in (".git", "__pycache__", "node_modules") for part in child.parts):
                    continue
                if child.is_file():
                    all_files.append(child)
                    if child.suffix.lower() in _SUPPORTED_EXTS:
                        artifact_files.append(child)
        else:
            all_files.append(p)
            if p.suffix.lower() in _SUPPORTED_EXTS or not check_blobs:
                artifact_files.append(p)
    return artifact_files, all_files, errors


def _load_raw(path: Path, app_root: Optional[Path]) -> Tuple[str, Dict[str, Any]]:
    """Return (kind_tag, parsed_dict) where kind_tag is 'legacy' or 'v1'."""
    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8")
    if suffix == ".json":
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: top-level JSON value must be an object")
        if "didactum" not in data and "schema_version" in data:
            return "legacy", data
        return "v1", data
    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(f"PyYAML is required to load {path}") from exc
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: top-level YAML value must be a mapping")
        return "v1", data
    if suffix == ".score":
        if app_root is not None:
            if str(app_root) not in sys.path:
                sys.path.insert(0, str(app_root))
            from app.services.lesson_score.kernel import compile_score_to_ast
            return "v1", compile_score_to_ast(raw).envelope.to_dict()
        return "v1", _standalone_parse_score(raw, path)
    raise ValueError(f"{path}: unsupported artifact extension {suffix!r}")


def main(argv: Sequence[str] | None = None) -> int:
    t0 = time.perf_counter()
    parser = argparse.ArgumentParser(
        prog="didactum_validate.py",
        description="Fast (<1s) offline validator for didactum: 1 and legacy v2 artifacts.",
    )
    parser.add_argument("paths", nargs="*", help="Artifact files or directories (defaults to lessons/ and examples/)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON diagnostics")
    parser.add_argument("--standalone", action="store_true", help="Force standalone mode without app.services.lesson_score")
    parser.add_argument("--enforce-identity", action="store_true", help="Enforce maintainer/GitHub actor_id namespace binding")
    parser.add_argument("--actor-id", default="", help="Immutable GitHub numeric actor_id for community PR checks")
    parser.add_argument("--actor", default="", help="GitHub actor login")
    parser.add_argument("--maintainers", default="", help="Comma-separated maintainer logins")
    parser.add_argument("--contributor-map", default="", help="Optional JSON file mapping numeric actor_id -> handle")
    parser.add_argument("--check-blobs", action="store_true", help="Scan files/directories for >100KB blobs and executable code")
    args = parser.parse_args(argv)

    raw_paths = list(args.paths)
    if not raw_paths:
        for default_dir in ("lessons", "examples"):
            cand = ECO_ROOT / default_dir
            if cand.is_dir():
                raw_paths.append(str(cand))
        if not raw_paths:
            raw_paths.append(str(ECO_ROOT))

    app_root = None if args.standalone else _find_app_root()
    artifact_files, all_files, path_errs = _collect_paths(raw_paths, check_blobs=args.check_blobs)
    if path_errs:
        payload = {
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "diagnostics": [_diag("DID-E000", "error", "<cli>", "#cli", "", m) for m in path_errs],
        }
        if args.as_json:
            print(json.dumps(payload))
        else:
            for m in path_errs:
                print(f"error: {m}", file=sys.stderr)
        return 2

    diags: List[Dict[str, Any]] = []
    scan_set = all_files if args.check_blobs else [f for f in all_files if f.suffix.lower() not in _SUPPORTED_EXTS]
    for sf in scan_set:
        diags.extend(check_file_security(sf, ECO_ROOT))
    for af in artifact_files:
        if af.suffix.lower() in _SUPPORTED_EXTS:
            diags.extend(check_file_security(af, ECO_ROOT))

    v1_docs: List[Mapping[str, Any]] = []
    v1_paths: List[Path] = []
    legacy_items: List[Tuple[Path, Dict[str, Any]]] = []

    for f in artifact_files:
        if f.suffix.lower() in _FORBIDDEN_BLOB_EXTS:
            continue
        try:
            tag, doc = _load_raw(f, app_root)
            if tag == "legacy":
                legacy_items.append((f, doc))
            else:
                v1_docs.append(doc)
                v1_paths.append(f)
        except Exception as exc:
            diags.append(_diag("DID-E000", "error", str(f), "#file", "", str(exc)))

    # Validate legacy v1/v2 lesson packages (100% backwards-compatible)
    seen_legacy_ids: Dict[str, Path] = {}
    for f, doc in legacy_items:
        errs = legacy_adapter.playable_errors(doc)
        lid = doc.get("id")
        if not errs and isinstance(lid, str) and lid in seen_legacy_ids:
            errs = [f"duplicate id {lid!r} (also {seen_legacy_ids[lid]})"]
        if isinstance(lid, str):
            seen_legacy_ids[lid] = f
        for e in errs:
            diags.append(_diag("DID-E020", "error", str(lid or f), "#legacy", "", e))

    # Validate didactum: 1 artifacts
    if v1_docs:
        if app_root is not None:
            if str(app_root) not in sys.path:
                sys.path.insert(0, str(app_root))
            from app.services.lesson_score.validator import validate_artifacts
            diags.extend(validate_artifacts(v1_docs))
        else:
            diags.extend(_standalone_validate_artifacts(v1_docs))

    # Optional identity / namespace binding enforcement
    actor_id = args.actor_id or (os.environ.get("GITHUB_ACTOR_ID", "") if args.enforce_identity else "")
    actor = args.actor or (os.environ.get("GITHUB_ACTOR", "") if args.enforce_identity else "")
    if args.enforce_identity or args.actor_id:
        maint_raw = args.maintainers or os.environ.get("DIDACTUM_MAINTAINERS", "")
        maintainers = [m.strip() for m in maint_raw.split(",") if m.strip()] if maint_raw else list(_DEFAULT_MAINTAINERS)
        contrib_map: Dict[str, str] = {}
        if args.contributor_map and Path(args.contributor_map).is_file():
            contrib_map = json.loads(Path(args.contributor_map).read_text(encoding="utf-8"))
        for f, doc in zip(v1_paths, v1_docs):
            diags.extend(check_identity_binding(
                doc, str(f), actor_id=actor_id, actor=actor, maintainers=maintainers, contributor_map=contrib_map
            ))
        for f, doc in legacy_items:
            diags.extend(check_identity_binding(
                doc, str(f), actor_id=actor_id, actor=actor, maintainers=maintainers, contributor_map=contrib_map
            ))

    has_errors = any(d.get("severity") == "error" for d in diags)
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    if args.as_json:
        print(json.dumps({
            "ok": not has_errors,
            "mode": "repo-wired" if app_root is not None else "standalone",
            "files": [str(f) for f in artifact_files],
            "elapsed_ms": elapsed_ms,
            "diagnostics": diags,
        }, ensure_ascii=False))
    else:
        for d in diags:
            fix_note = f" (fix: {len(d['fix'])} op(s))" if d.get("fix") else ""
            print(f"[{d['severity'].upper()}] {d['code']} {d['artifact']} {d['address']} ({d['pointer']}): {d['message']}{fix_note}")
        status = "OK" if not has_errors else "FAILED"
        print(f"{status}: {len(artifact_files)} file(s), {len(diags)} diagnostic(s) in {elapsed_ms} ms")

    return 1 if has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
