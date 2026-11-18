# inflect-opt-lab

`inflect` is a pure-Python library for English pluralisation, singularisation and
number-to-words. This repo removes the runtime type-check wrapper from one
internal helper, `engine.ud_match`, which `plural()` calls **three times per
word**: every call re-ran typeguard's generic `Sequence[str | None]` /
`Annotated` machinery for **18.1 µs**, while the matching work itself is
0.24 µs (empty user wordlist, which is the case for the fixture corpus). The check is inlined as an `isinstance` loop over the same `inflect.Word`
domain, so the accepted/rejected argument domain and the `TypeCheckError` class
are unchanged; only typeguard's per-call resolution is gone.

Upstream: https://github.com/jaraco/inflect

- Upstream commit: `2084a52769175d8159474779f7cfa71f08f2f911` (2026-10-29)
- Runtime: CPython 3.12.3, typeguard 4.6.0
- Patch: `patch.diff` — 1 file, **+19 / −2 lines**, `git apply --check` verified on
  a clean clone of the upstream commit.
- Scope: only `engine.ud_match`. Public methods keep their `@typechecked`
  decorators; `plural("")` still raises `TypeCheckError` (covered by the
  upstream test `test_pwd.py::Test::test__pl_special_verb`).

## Measured result

`benchmark/bench.py`, undiluted real fixture words
(`benchmark/corpus/words.txt`, 766 unique head words extracted from upstream
`tests/inflections.txt`), 3 warmups + 7 timed reps per workload, fresh engine
per sample, medians in ms:

| workload | words | baseline | optimized | speedup |
|---|---:|---:|---:|---:|
| small | 100 | 9.148 | 3.042 | **3.007x** |
| medium | 300 | 29.570 | 9.913 | **2.983x** |
| large | 766 | 74.897 | 26.819 | **2.793x** |
| real corpus, mixed plural+singular | 766 pairs | 134.823 | 69.774 | **1.932x** |

Median of the three scale speedups: **2.983x**. Largest scale: **2.793x**
(G4, no regression). The fourth row is the G3b real-corpus measurement: it is a
different workload (pluralise every fixture word, then singularise the result
back) and is **not** a repeat of the large slice; its smaller 1.93x reflects the
share of `ud_match` on the singularisation path.

Relative standard deviation per workload is 1.07 %–3.08 %, except `small`
optimized at 9.89 % — that workload runs in ~3 ms, so scheduler noise and the
first-touch page faults of a fresh engine are visible. It is below the 10 %
reporting threshold but is stated here rather than hidden.

## Differential test

`tests/test_diff.py` builds cases from the fixture words plus edge cases (empty
string, whitespace, 200-char word, non-ASCII, phrases, counts `0/1/2/zero/one`,
negative/large numbers), de-duplicates by sha256 of the canonical JSON case, and
runs each build in its own process:

```
cases generated        : 14456
independent samples    : 14456 (sha256 de-dup over canonical JSON)
mismatches             : 0
cases raising in both  : 53 (exception class compared, not message)
baseline sha256        : 7b02e0325fcf7b0e880fbb1a93557d0ba2a4e9bbdca86b62b52b5d9d56296fec
optimized sha256       : 7b02e0325fcf7b0e880fbb1a93557d0ba2a4e9bbdca86b62b52b5d9d56296fec
byte-identical         : True
```

## Gates

| gate | result | reproduce |
|---|---|---|
| G1 upstream tests | **273 passed, 16 xfailed** on the patched tree (baseline: same) | see the G1 command block below |
| G2 differential | 14 456 independent samples, 0 mismatch, sha256 equal | `python tests/test_diff.py` |
| G3 median speedup | 3.007x / 2.983x / 2.793x → median **2.983x** | `python benchmark/bench.py --all` |
| G3b real corpus | **1.932x** on the 766-pair mixed workload | `python benchmark/bench.py --all` (row `real_mixed`) |
| G4 largest scale | **2.793x** ≥ 0.95x | same table |
| G5 peak RSS | 40 356 KB → 40 484 KB = **1.003x** ≤ 1.10x | `max_rss_kb` in `benchmark/*.json` |

G1 note: the upstream suite is not vendored in this repo; it lives in the
upstream checkout. The exact command used was

```bash
git clone --depth=1 https://github.com/jaraco/inflect /tmp/inflect-upstream
cd /tmp/inflect-upstream && git checkout 2084a52769175d8159474779f7cfa71f08f2f911
cp -r <this-repo>/src/inflect ./inflect
pip install -e . && python -m pytest tests -q
# 273 passed, 16 xfailed in 2.79s
```

The same suite on the unmodified tree gives `273 passed, 16 xfailed` as well,
so the patch adds no failures.

## Reproduce

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -q "typeguard>=4.0.1" jaraco.functools more-itertools pytest
python benchmark/bench.py --all && python tests/test_diff.py
```

## Environment

- CPU: AMD EPYC 7K62 48-Core Processor (from `/proc/cpuinfo`), 4 cores visible, 3,812,564 KB RAM (`benchmark/*.json` → `machine`)
- CPython 3.12.3 (`/usr/bin/python3.12`); no 3.10/3.11 on this machine, so no
  cross-interpreter table is claimed.
- typeguard 4.6.0, pytest 9.x
- Seed: `20261118`; warmup 3; reps 7; raw per-sample files in `benchmark/raw/`.

## 本轮创新

首次把「运行时注解校验（typeguard `@typechecked`）在真实库热路径上的成本」
当成独立性能轴来测量：用同一份上游 fixture 词表证明 `ud_match` 每次调用
**18.1 µs 中 17.9 µs 是 typeguard 的泛型解析**（不是匹配逻辑），并且这个
helper 被 `plural()` 每词调用 3 次；改法是「边界检查保留、循环内重复检查
内联为 `isinstance`」，从而把 2.98x 的中位加速与 14 456 组逐字节一致同时拿到。
台账里已有的优化轴是异常控制流、每调用重建、O(n²)、缓存/harness 有效性，
没有「运行时类型校验税」这一项；本仓库也没有把「删掉校验」当卖点——公共
入口的 `@typechecked` 和 `TypeCheckError` 契约都保留，测试覆盖了空字符串
仍然抛错。
