# Modernizer

Verified legacy-code migration for **Python 2 → 3** and **Java 8 → 17/21**.

Most AI coding tools change code and hope. Modernizer's rule is: **a migration only counts if the project builds and its tests pass afterwards**, and every run produces a report that says exactly what was changed, what was verified, and what still needs a human.

## How it works

```
scan → map dependencies → baseline check → deterministic migration → verify → (optional) LLM repair → report
```

1. **Map**: builds an import graph and migrates leaf files first.
2. **Baseline**: builds/tests the *original* code so "before vs after" is measured, not claimed.
3. **Deterministic migration first** (no AI, no cost, no hallucination):
   - Python: `fissix` (maintained fork of lib2to3) fixers + extra review rules (`cmp`, `string.*`, bytes/str, `/` division...).
   - Java: target-aware rules (a rule only fires if the target JDK is ≥ the version where it breaks), `pom.xml`/Gradle version bumps, removed-API rewrites (`new Integer(..)`, `sun.misc.BASE64*`), and flags for JAXB/CORBA/Nashorn/SecurityManager/`finalize`/`Thread.stop`, plus dependency version hints (Lombok, JaCoCo, Mockito...).
4. **Verify**: Python compile check (+ tests); Java via Maven/Gradle, or a JDK compiler fallback.
5. **LLM repair (opt-in, `--llm`)**: only for what still fails. The model sees only the failing files, and every answer is validated (must compile / balance braces, and may only touch files it was shown) before being written.
6. **Report**: `MODERNIZER_REPORT.md`, `modernizer_report.json`, `modernizer.diff` inside the output copy.

The original project is **never modified**; work happens in a copy.

## Quick start

```bash
pip install -e ".[dev]"
modernizer scan examples/legacy_py
modernizer migrate examples/legacy_py --out /tmp/py_out --run-tests
modernizer migrate examples/legacy_java --out /tmp/java_out --target 21
pytest
```

LLM repair works with any OpenAI-compatible server, including free local ones:

```bash
ollama pull qwen2.5-coder:7b
modernizer migrate ./my_project --llm                       # defaults to Ollama on localhost
modernizer migrate ./my_project --llm --llm-url https://api.groq.com/openai/v1 --model <model>   # key via MODERNIZER_LLM_KEY
```

## Safety

- Works on a copy, refuses output paths inside the source.
- `--run-tests` executes the project's own code. For untrusted repos use the Dockerfile.
- LLM output is validated and path-restricted before it touches disk.

## Benchmark (this is your proof)

```bash
mkdir repos && cd repos && git clone <repo1> <repo2> ...   # old Python 2 / Java 8 projects that have tests
cd .. && modernizer bench repos --out bench_out --run-tests
```

Produces `bench_out/results.csv` and `RESULTS.md` (compile/test status before vs after, per repo). Publish this table, including the failures.

## Real-world results

Run on 5 open-source Python 2 projects I did not write (`examples/sample_reports/benchmark_5_real_repos.md`):
**all 5 fail to compile on Python 3 before migration, and all 5 compile after** (261 files in total).
Running the benchmark found two real bugs, both now fixed and covered by tests:
mixed tabs/spaces in indentation (Nscan), and implicit relative imports (douban-client).

**Not yet proven:** that the migrated code *behaves* the same. Compiling is not the same as working.
Running the test suites was blocked by dependencies, not by the migration: salmon needs Django,
and douban-client depends on `pyoauth2`, which is itself stuck on Python 2. Handling dependencies
(install, or migrate them too) is the next big feature. A pure-Python project with its own tests is
the next benchmark target.

## Status: what is and isn't verified

| Area | Status |
|---|---|
| Scanner, dependency order, Python migration, reports, CLI | Tested (12 tests pass, on Linux and Windows/Python 3.14) |
| 5 real Python 2 repos: compile before vs after | 5 of 5 now compile (see above) |
| Java rewrites compiling on a real JDK 21 | Tested on a small example only |
| Maven / Gradle verification path | **Written, not yet run** |
| LLM repair with a real model | Tested with a stub model only |
| Migrated code passes the original tests | **Not yet shown on a real repo** |
| Dockerfile | Written, not built |

## Known limits / roadmap

- Java rules are line-based regexes: no parser yet (comments are skipped; strings are not). Next: tree-sitter / JavaParser.
- Dependency-type fixes (e.g. adding Jakarta JAXB to `pom.xml`) are reported, not applied yet. See `examples/sample_reports/java_report.md`.
- Same-package Java references are not in the dependency graph.
- Python semantic changes (integer division, bytes vs str) are flagged for review, not auto-resolved.
- Ideas: language-feature modernization (records, text blocks), COBOL, parallel per-file agents, a web UI.
