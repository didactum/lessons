#!/usr/bin/env python3
"""Validate lessons: python3 scripts/validate_lesson.py [file.json ...]  (default: every lessons/**/*.json)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _package_adapter as adapter  # vendored from didactum; do not edit  # noqa: E402


def main(argv):
    root = HERE.parent
    files = [Path(a) for a in argv] or sorted((root / "lessons").rglob("*.json"))
    if not files:
        print("no lessons found", file=sys.stderr)
        return 1
    bad = 0
    seen = {}
    for f in files:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"{f}: invalid JSON: {exc}", file=sys.stderr)
            bad += 1
            continue
        errs = adapter.validate_lesson_package(doc)
        if not errs and doc["id"] in seen:
            errs = [f"duplicate id {doc['id']!r} (also {seen[doc['id']]})"]
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
