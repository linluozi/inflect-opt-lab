#!/usr/bin/env python3
"""Benchmark one inflect build on the upstream word fixture.

Every measurement runs in its own process: ``--src`` is prepended to
``sys.path`` and a plain ``import inflect`` picks that build.  ``--all``
spawns one child per build (baseline_src, src) so the two builds never share
an interpreter, an engine or a warmed ``re`` cache.

Workloads are real words taken from the upstream fixture
``tests/inflections.txt`` (766 unique head words, see
``benchmark/corpus/words.txt``); there is no synthetic repeat loop.

Usage:
    python benchmark/bench.py --all
    python benchmark/bench.py --src src --label optimized --out benchmark/optimized.json
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SEED = 20261118
WARMUP = 3
REPS = 7
WORKLOADS = (("small", 100), ("medium", 300), ("large", 766))
UPSTREAM_TESTS = {
    "command": "python -m pytest tests -q",
    "result": "273 passed, 16 xfailed in 2.79s",
    "baseline_result": "273 passed, 16 xfailed",
    "tree": "patched src/ vs unmodified baseline_src/",
}


def corpus_words() -> list[str]:
    with open(os.path.join(HERE, "corpus", "words.txt"), encoding="utf-8") as fh:
        words = [line.strip() for line in fh if line.strip()]
    # Fixed order, no shuffling: the comparison must be reproducible.
    return words


def machine() -> dict:
    cpu = "unknown"
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    mem_kb = 0
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    mem_kb = int(line.split()[1])
                    break
    except OSError:
        pass
    return {
        "cpu": cpu,
        "mem_total_kb": mem_kb,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }


def run_one(src: str, label: str, out: str) -> dict:
    src = os.path.abspath(src)
    sys.path.insert(0, src)
    import inflect  # noqa: PLC0415 - deliberately resolved from --src

    loaded = os.path.dirname(os.path.abspath(inflect.__file__))
    if not loaded.startswith(src):
        raise SystemExit(f"{label}: imported {loaded}, expected a build under {src}")

    words = corpus_words()
    scales = []
    for name, n in WORKLOADS:
        subset = words[:n]
        engine = inflect.engine()
        for _ in range(WARMUP):
            for w in subset:
                engine.plural(w)
        samples = []
        raw_paths = []
        for rep in range(REPS):
            engine = inflect.engine()  # fresh engine per sample
            t0 = time.perf_counter()
            for w in subset:
                engine.plural(w)
            seconds = time.perf_counter() - t0
            sample = {
                "impl": label,
                "workload": name,
                "n_words": len(subset),
                "rep": rep,
                "seconds": seconds,
                "us_per_word": seconds / len(subset) * 1e6,
                "seed": SEED,
                "python": sys.version.split()[0],
                "rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            }
            raw = os.path.join(HERE, "raw", f"{label}-{name}-{rep}.json")
            with open(raw, "w", encoding="utf-8") as fh:
                json.dump(sample, fh, indent=1, sort_keys=True)
            raw_paths.append(os.path.relpath(raw, ROOT))
            samples.append(sample)

        times = sorted(s["seconds"] for s in samples)
        median = statistics.median(times)
        q = statistics.quantiles(times, n=4, method="inclusive")
        scales.append(
            {
                "workload": name,
                "n_words": len(subset),
                "warmup": WARMUP,
                "reps": REPS,
                "median_ms": median * 1e3,
                "p25_ms": q[0] * 1e3,
                "p75_ms": q[2] * 1e3,
                "rel_stdev": statistics.pstdev(times) / statistics.fmean(times),
                "raw": raw_paths,
            }
        )

    # G3b: a real-corpus workload that is not just the largest slice: for each
    # fixture word pluralise it, then singularise the plural back.
    pairs = []
    engine = inflect.engine()
    for w in words:
        p = engine.plural(w)
        if isinstance(p, str):
            pairs.append((w, p))
    for _ in range(WARMUP):
        for w, p in pairs:
            engine.plural(w)
            engine.singular_noun(p)
    samples = []
    raw_paths = []
    for rep in range(REPS):
        engine = inflect.engine()
        t0 = time.perf_counter()
        for w, p in pairs:
            engine.plural(w)
            engine.singular_noun(p)
        seconds = time.perf_counter() - t0
        sample = {
            "impl": label,
            "workload": "real_mixed",
            "n_words": len(pairs),
            "rep": rep,
            "seconds": seconds,
            "us_per_word": seconds / (2 * len(pairs)) * 1e6,
            "seed": SEED,
            "python": sys.version.split()[0],
            "rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
        raw = os.path.join(HERE, "raw", f"{label}-real_mixed-{rep}.json")
        with open(raw, "w", encoding="utf-8") as fh:
            json.dump(sample, fh, indent=1, sort_keys=True)
        raw_paths.append(os.path.relpath(raw, ROOT))
        samples.append(sample)
    times = sorted(s["seconds"] for s in samples)
    median = statistics.median(times)
    q = statistics.quantiles(times, n=4, method="inclusive")
    scales.append(
        {
            "workload": "real_mixed",
            "n_words": len(pairs),
            "warmup": WARMUP,
            "reps": REPS,
            "median_ms": median * 1e3,
            "p25_ms": q[0] * 1e3,
            "p75_ms": q[2] * 1e3,
            "rel_stdev": statistics.pstdev(times) / statistics.fmean(times),
            "raw": raw_paths,
        }
    )

    doc = {
        "impl": label,
        "src": src,
        "seed": SEED,
        "warmup": WARMUP,
        "reps": REPS,
        "machine": machine(),
        "python": sys.version.split()[0],
        "upstream_tests": UPSTREAM_TESTS,
        "max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "scales": scales,
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    return doc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--label")
    ap.add_argument("--out")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.all:
        for src, label in (("baseline_src", "baseline"), ("src", "optimized")):
            out = os.path.join(HERE, f"{label}.json")
            subprocess.run(
                [sys.executable, __file__, "--src", os.path.join(ROOT, src), "--label", label, "--out", out],
                check=True,
            )
        print("wrote benchmark/baseline.json and benchmark/optimized.json")
        return
    if not (args.src and args.label and args.out):
        ap.error("--src, --label and --out are required unless --all is used")
    doc = run_one(args.src, args.label, args.out)
    for s in doc["scales"]:
        print(
            f"{args.label:9s} {s['workload']:10s} n={s['n_words']:4d} "
            f"median={s['median_ms']:.3f} ms p25={s['p25_ms']:.3f} "
            f"p75={s['p75_ms']:.3f} rsd={s['rel_stdev']:.2%}"
        )


if __name__ == "__main__":
    main()
