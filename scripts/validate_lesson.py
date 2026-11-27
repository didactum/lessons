#!/usr/bin/env python3
"""Validate lessons: python3 scripts/validate_lesson.py [file.json ...]   (default: every lessons/**/*.json)

Runs the same validator the site runs before a lesson can play (scripts/_package_adapter.py, vendored from the app:
do not edit it), and delegates didactum: 1 artifacts (.score, .yaml/.yml, or JSON with didactum: 1) to
scripts/didactum_validate.py. Each problem is printed as `<file>: <where>: <what to do>`. Exit code 0 means every
file passed.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _package_adapter as adapter  # vendored from didactum; do not edit  # noqa: E402
import didactum_validate  # noqa: E402

PATH_RE = re.compile(r"^lessons/[a-z0-9][a-z0-9-]*/([a-z0-9][a-z0-9-]*)\.json$")


def _is_didactum_v1(path: Path) -> bool:
    if path.suffix.lower() in (".yaml", ".yml", ".score"):
        return True
    if path.suffix.lower() == ".json":
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            return isinstance(doc, dict) and "didactum" in doc and "schema_version" not in doc
        except (OSError, ValueError):
            return False
    return False


def main(argv):
    root = HERE.parent
    raw_args = list(argv)
    if raw_args and any(_is_didactum_v1(Path(a)) for a in raw_args if Path(a).is_file()):
        return didactum_validate.main(raw_args)

    files = [Path(a) for a in raw_args] or sorted((root / "lessons").rglob("*.json"))
    if not files:
        print("no lessons found", file=sys.stderr)
        return 1
    bad = 0
    seen = {}
    for f in files:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"{f}: not valid JSON: {exc}", file=sys.stderr)
            bad += 1
            continue
        errs = adapter.playable_errors(doc)
        try:
            rel = f.resolve().relative_to(root).as_posix()
        except ValueError:
            rel = None
        if rel is not None and not errs:
            m = PATH_RE.match(rel)
            if not m:
                errs.append(f"file must be lessons/<subject>/<slug>.json (lower-case letters, digits, hyphens), got {rel}")
            elif m.group(1) != doc.get("slug"):
                errs.append(f"file name {m.group(1)!r} must equal the package slug {doc.get('slug')!r}")
        if not errs and isinstance(doc, dict) and doc.get("id") in seen:
            errs = [f"duplicate id {doc['id']!r} (also {seen[doc['id']]})"]
        if isinstance(doc, dict):
            seen[doc.get("id")] = f
        for e in errs:
            print(f"{f}: {e}", file=sys.stderr)
        bad += bool(errs)
        if not errs:
            print(f"ok  {f}")
    print("OK" if not bad else f"FAILED: {bad} file(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
