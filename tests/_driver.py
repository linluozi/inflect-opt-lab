"""Run one inflect build over a JSON case list and print canonical results.

Invoked as a child process by tests/test_diff.py so the two builds never share
an interpreter.  Values are serialised with repr() so that type and content
both participate in the comparison; exceptions are recorded by class name.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    sys.path.insert(0, args.src)
    inflect = importlib.import_module("inflect")
    loaded = inflect.__file__
    if not loaded.startswith(args.src):
        raise SystemExit(f"imported {loaded}, expected a build under {args.src}")

    with open(args.cases, encoding="utf-8") as fh:
        cases = json.load(fh)

    engine = inflect.engine()
    out = []
    for case in cases:
        op = case["op"]
        fn = getattr(engine, op)
        try:
            value = fn(*case["args"])
            out.append({"ok": True, "value": repr(value)})
        except Exception as exc:  # noqa: BLE001 - the comparison needs the class
            out.append({"ok": False, "error": type(exc).__name__})
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, sort_keys=True)


if __name__ == "__main__":
    main()
