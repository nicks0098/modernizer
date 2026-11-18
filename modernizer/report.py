from __future__ import annotations

import difflib
import json
from collections import Counter, defaultdict
from pathlib import Path

from .models import Result, status
from .scanner import iter_files, read_text

_BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts")


def _verify_lines(title: str, vs) -> list[str]:
    lines = [f"**{title}**", ""]
    for v in vs:
        mark = "skipped" if v.skipped else ("pass" if v.ok else "FAIL")
        lines.append(f"- `{v.name}`: {mark}" + (f" — {v.output.splitlines()[0][:100]}" if v.output and (v.skipped or not v.ok) else ""))
    return lines + [""]


def render_markdown(results: list[Result]) -> str:
    md = ["# Modernizer migration report", ""]
    for r in results:
        by_kind = defaultdict(list)
        for f in r.findings:
            by_kind[f.kind].append(f)
        md += [f"## {r.project} ({r.language})", "",
               "| files scanned | files changed | auto rewrites | needs review | repair rounds | seconds |",
               "|---|---|---|---|---|---|",
               f"| {r.files_scanned} | {r.files_changed} | {len(by_kind['auto'])} | {len(by_kind['manual'])} | {r.repair_rounds} | {r.seconds} |",
               ""]
        md += _verify_lines("Before (original code)", r.verify_before)
        md += _verify_lines("After migration", r.verify_after)
        if by_kind["auto"]:
            md += ["### Applied automatically", ""]
            md += [f"- `{rule}` x{n}" for rule, n in Counter(f.rule for f in by_kind["auto"]).most_common()]
            md.append("")
        if by_kind["manual"]:
            md += ["### Needs human review", ""]
            groups = defaultdict(list)
            for f in by_kind["manual"]:
                groups[f.rule].append(f)
            for rule, fs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
                md.append(f"- **{rule}** x{len(fs)} — {fs[0].message}")
                md += [f"    - `{f.file}:{f.line}`" for f in fs[:5]]
                if len(fs) > 5:
                    md.append(f"    - ... and {len(fs) - 5} more")
            md.append("")
        if by_kind["info"]:
            md += ["### Advice", ""]
            seen = set()
            for f in by_kind["info"]:
                if (f.rule, f.message) not in seen:
                    seen.add((f.rule, f.message))
                    md.append(f"- {f.message}")
            md.append("")
        if r.notes:
            md += ["### Notes", ""] + [f"- {n}" for n in r.notes] + [""]
    return "\n".join(md)


def _diff(src: Path, out: Path, results: list[Result]) -> str:
    chunks = []
    for r in results:
        rels = [p.relative_to(out).as_posix() for p in iter_files(out, r.language)]
        rels += [b for b in _BUILD_FILES if (out / b).is_file()] if r.language == "java" else []
        for rel in rels:
            a = (src / rel)
            before = read_text(a)[0] if a.is_file() else ""
            after = read_text(out / rel)[0]
            if before != after:
                chunks += difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                               f"a/{rel}", f"b/{rel}")
    return "".join(chunks)


def write_reports(results: list[Result], src: Path, out: Path) -> None:
    (out / "MODERNIZER_REPORT.md").write_text(render_markdown(results), encoding="utf-8")
    (out / "modernizer_report.json").write_text(
        json.dumps([r.to_dict() for r in results], indent=2), encoding="utf-8")
    (out / "modernizer.diff").write_text(_diff(src, out, results), encoding="utf-8")


def summary_row(r: Result) -> dict:
    return {
        "repo": r.project, "language": r.language, "files": r.files_scanned, "changed": r.files_changed,
        "auto_rewrites": sum(f.kind == "auto" for f in r.findings),
        "needs_review": sum(f.kind == "manual" for f in r.findings),
        "compile_before": status(r.verify_before, ("compile", "build", "build+tests")),
        "compile_after": status(r.verify_after, ("compile", "build", "build+tests")),
        "tests_before": status(r.verify_before, ("tests", "build+tests")),
        "tests_after": status(r.verify_after, ("tests", "build+tests")),
        "repair_rounds": r.repair_rounds, "seconds": r.seconds,
    }
