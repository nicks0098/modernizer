"""Run the pipeline over many repos and produce the table you put in your README / pitch deck."""
from __future__ import annotations

import csv
from pathlib import Path

from . import pipeline
from .report import summary_row

COLS = ["repo", "language", "files", "changed", "auto_rewrites", "needs_review", "compile_before",
        "compile_after", "tests_before", "tests_after", "repair_rounds", "seconds", "error"]


def run_bench(repos_dir: Path, out_dir: Path, lang="auto", target=21, run_tests=False, llm=None,
              max_repair=3, log=print) -> list[dict]:
    rows = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for repo in sorted(p for p in Path(repos_dir).iterdir() if p.is_dir() and not p.name.startswith(".")):
        log(f"== {repo.name}")
        try:
            results = pipeline.run(repo, out_dir / repo.name, lang=lang, target=target, llm=llm,
                                   max_repair=max_repair, run_tests=run_tests, force=True, log=log)
            rows += [summary_row(r) for r in results] or [{"repo": repo.name, "error": "no supported files"}]
        except Exception as e:
            rows.append({"repo": repo.name, "error": f"{type(e).__name__}: {e}"[:200]})
    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, restval="")
        w.writeheader()
        w.writerows(rows)
    (out_dir / "RESULTS.md").write_text(_markdown(rows), encoding="utf-8")
    return rows


def _markdown(rows: list[dict]) -> str:
    ok = [r for r in rows if r.get("compile_after") == "pass" and r.get("tests_after") in ("pass", "skipped")]
    lines = ["# Benchmark results", "",
             f"{len(ok)} of {len(rows)} projects ended with a passing build"
             " (tests counted only if they were run).", "",
             "| " + " | ".join(COLS) + " |", "|" + "---|" * len(COLS)]
    lines += ["| " + " | ".join(str(r.get(c, "")) for c in COLS) + " |" for r in rows]
    return "\n".join(lines) + "\n"
