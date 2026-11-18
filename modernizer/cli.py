from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, pipeline
from .bench import run_bench
from .llm import OpenAICompatLLM
from .models import status
from .scanner import build_map, detect_languages, java_version, migration_order, python2_suspects


def _llm(args):
    return OpenAICompatLLM(args.llm_url, args.model) if args.llm else None


def cmd_scan(args) -> int:
    root = Path(args.path)
    counts = detect_languages(root)
    print(f"Project: {root.resolve().name}")
    print(f"Files: {counts['python']} Python, {counts['java']} Java")
    if counts["python"]:
        total, bad = python2_suspects(root)
        print(f"Python: {bad}/{total} files do not parse as Python 3 (likely Python 2)")
        print("  migrate leaf-first:", ", ".join(migration_order(build_map(root, 'python'))[:8]))
    if counts["java"]:
        print(f"Java: current target = {java_version(root) or 'unknown'}")
        print("  migrate leaf-first:", ", ".join(migration_order(build_map(root, 'java'))[:8]))
    return 0


def cmd_migrate(args) -> int:
    src = Path(args.path)
    out = Path(args.out) if args.out else src.resolve().parent / f"{src.resolve().name}_migrated"
    try:
        results = pipeline.run(src, out, args.lang, args.target, _llm(args), args.max_repair,
                               args.run_tests, args.force, log=print)
    except (FileExistsError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not results:
        print("No supported source files found.")
        return 1
    for r in results:
        a = sum(f.kind == "auto" for f in r.findings)
        m = sum(f.kind == "manual" for f in r.findings)
        st = {"pass": "PASSED", "fail": "FAILED", "skipped": "SKIPPED (no build tool found)"}.get(
            status(r.verify_after), "n/a")
        print(f"\n{r.language}: {r.files_changed} files changed, {a} auto rewrites, {m} need review, "
              f"verification {st}")
    print(f"\nMigrated copy + report: {out}\n  {out / 'MODERNIZER_REPORT.md'}")
    return 0


def cmd_bench(args) -> int:
    rows = run_bench(Path(args.repos), Path(args.out), args.lang, args.target, args.run_tests,
                     _llm(args), args.max_repair)
    print(f"\nWrote {len(rows)} rows to {Path(args.out) / 'results.csv'} and RESULTS.md")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="modernizer", description="Migrate legacy code: Python 2->3 and Java 8->17/21")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--lang", choices=["auto", "python", "java"], default="auto")
        sp.add_argument("--target", type=int, default=21, help="target JDK (default 21)")
        sp.add_argument("--run-tests", action="store_true", help="execute the project's tests (run inside a sandbox/Docker!)")
        sp.add_argument("--llm", action="store_true", help="enable LLM repair (default: Ollama at localhost:11434)")
        sp.add_argument("--llm-url", help="OpenAI-compatible base URL")
        sp.add_argument("--model", help="model name")
        sp.add_argument("--max-repair", type=int, default=3)

    s = sub.add_parser("scan", help="inspect a project without changing it")
    s.add_argument("path")
    s.set_defaults(fn=cmd_scan)
    m = sub.add_parser("migrate", help="migrate a COPY of the project and write a report")
    m.add_argument("path")
    m.add_argument("--out")
    m.add_argument("--force", action="store_true", help="overwrite the output directory")
    common(m)
    m.set_defaults(fn=cmd_migrate)
    b = sub.add_parser("bench", help="run on every sub-directory of REPOS and write results.csv")
    b.add_argument("repos")
    b.add_argument("--out", default="bench_out")
    common(b)
    b.set_defaults(fn=cmd_bench)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
