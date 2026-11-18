"""Differential test: unmodified inflect vs the patched build.

The two builds are imported in separate child processes (they cannot coexist
under the same module name), and every result is compared byte-for-byte after
``repr()`` serialisation.  Case generation is seeded and every case is
de-duplicated by sha256 over its canonical JSON, so the reported number is the
number of *independent* samples, not the number of loop iterations.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SEED = 20261118
COUNTS = [None, 0, 1, 2, "zero", "one", 3]


def corpus() -> list[str]:
    with open(os.path.join(ROOT, "benchmark", "corpus", "words.txt"), encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def edge_words() -> list[str]:
    return [
        "dog", "DOG", "Dog", "  cat  ", "mother-in-law", "attorney general",
        "déjà vu", "café", "北京", "naïve", "Ελλάδα", "a" * 200,
        "x", "1", "3.14", "-1", "", " ", "\t", "a b c",
    ]


def build_cases() -> list[dict]:
    rng = random.Random(SEED)
    words = corpus() + edge_words()
    cases: list[dict] = []
    # 1. every fixture word through the main inflection entry points
    for w in words:
        for count in COUNTS:
            cases.append({"op": "plural", "args": [w, count]})
        cases.append({"op": "singular_noun", "args": [w]})
        cases.append({"op": "plural_verb", "args": [w]})
        cases.append({"op": "plural_adj", "args": [w]})
        cases.append({"op": "inflect", "args": [f"plural('{w}')"]})
        cases.append({"op": "present_participle", "args": [w]})
        cases.append({"op": "a", "args": [w]})
        cases.append({"op": "an", "args": [w]})
        cases.append({"op": "no", "args": [w, rng.choice([0, 1, 2])]})
    # 2. paired comparisons over real words
    for _ in range(600):
        w1, w2 = rng.choice(words), rng.choice(words)
        for op in ("compare", "compare_nouns", "compare_verbs", "compare_adjs"):
            cases.append({"op": op, "args": [w1, w2]})
    # 3. numbers and ordinals
    for n in list(range(0, 60)) + [99, 100, 101, 1000, 12345, -3, "42", "one hundred"]:
        cases.append({"op": "ordinal", "args": [n]})
        cases.append({"op": "number_to_words", "args": [n]})
    for n in (0, 1, 2, 7, 19, 100, 101, "5"):
        cases.append({"op": "number_to_currency", "args": [n]})
    # 4. deterministic random tuples of the above
    ops = ["plural", "singular_noun", "plural_verb", "plural_adj", "compare"]
    for _ in range(800):
        op = rng.choice(ops)
        args = [rng.choice(words)]
        if op == "plural":
            args.append(rng.choice(COUNTS))
        elif op == "compare":
            args.append(rng.choice(words))
        cases.append({"op": op, "args": args})
    return cases


def dedupe(cases: list[dict]) -> tuple[list[dict], int]:
    seen: set[str] = set()
    unique: list[dict] = []
    for case in cases:
        digest = hashlib.sha256(
            json.dumps(case, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        unique.append(case)
    return unique, len(seen)


def run_build(src: str, cases_path: str, out_path: str) -> None:
    subprocess.run(
        [
            sys.executable,
            os.path.join(HERE, "_driver.py"),
            "--src",
            src,
            "--cases",
            cases_path,
            "--out",
            out_path,
        ],
        check=True,
    )


def main() -> int:
    cases, unique_count = dedupe(build_cases())
    with tempfile.TemporaryDirectory() as tmp:
        cases_path = os.path.join(tmp, "cases.json")
        with open(cases_path, "w", encoding="utf-8") as fh:
            json.dump(cases, fh, sort_keys=True, ensure_ascii=False)
        out = {}
        for label, src in (("baseline", "baseline_src"), ("optimized", "src")):
            path = os.path.join(tmp, f"{label}.json")
            run_build(os.path.join(ROOT, src), cases_path, path)
            with open(path, "rb") as fh:
                out[label] = fh.read()
    base, opt = out["baseline"], out["optimized"]
    base_hash = hashlib.sha256(base).hexdigest()
    opt_hash = hashlib.sha256(opt).hexdigest()
    mismatches = []
    if base != opt:
        base_rows, opt_rows = json.loads(base), json.loads(opt)
        for case, a, b in zip(cases, base_rows, opt_rows):
            if a != b:
                mismatches.append((case, a, b))
    errors = sum(1 for row in json.loads(base) if not row["ok"])
    print(f"cases generated        : {len(cases)}")
    print(f"independent samples    : {unique_count} (sha256 de-dup over canonical JSON)")
    print(f"mismatches             : {len(mismatches)}")
    print(f"cases raising in both  : {errors} (exception class compared, not message)")
    print(f"baseline sha256        : {base_hash}")
    print(f"optimized sha256       : {opt_hash}")
    print(f"byte-identical         : {base == opt}")
    if mismatches:
        for case, a, b in mismatches[:5]:
            print("MISMATCH", case, a, b)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
