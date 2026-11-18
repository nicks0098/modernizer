"""scan -> map -> baseline check -> deterministic migration -> verify -> (optional) LLM repair -> report.

The original project is never modified: work happens in a copy.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import java_upgrade, python2to3, repair
from .llm import LLM
from .models import Result, Verify
from .report import write_reports
from .scanner import build_map, detect_languages, iter_files, migration_order, read_text
from .verify import verify

_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".venv", "venv", "target", "build")
_BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts")


def prepare_out(src: Path, out: Path, force: bool) -> None:
    src, out = src.resolve(), out.resolve()
    if src == out or src.is_relative_to(out) or out.is_relative_to(src):
        raise ValueError("output directory must be separate from (and not inside) the source project")
    if out.exists():
        if any(out.iterdir()) and not force:
            raise FileExistsError(f"{out} already exists; use --force to overwrite")
        shutil.rmtree(out)
    shutil.copytree(src, out, ignore=_IGNORE)


def _changed_files(src: Path, out: Path, lang: str) -> int:
    rels = [p.relative_to(out).as_posix() for p in iter_files(out, lang)] + \
           [b for b in _BUILD_FILES if (out / b).is_file()]
    n = 0
    for rel in rels:
        a, b = src / rel, out / rel
        if not a.is_file() or a.read_bytes() != b.read_bytes():
            n += 1
    return n


def migrate_language(src: Path, out: Path, lang: str, target: int, llm: LLM | None,
                     max_repair: int, run_tests: bool, log) -> Result:
    t0 = time.time()
    res = Result(project=src.name, language=lang, out_dir=str(out))
    pm = build_map(out, lang)
    res.files_scanned = len(pm.loc)
    order = migration_order(pm)
    log(f"[{lang}] {res.files_scanned} files; baseline check...")
    res.verify_before = verify(lang, out, run_tests)  # `out` is still an untouched copy here

    log(f"[{lang}] migrating...")
    res.findings = python2to3.migrate(out, order) if lang == "python" else java_upgrade.migrate(out, order, target)
    res.verify_after = verify(lang, out, run_tests)

    while llm and res.repair_rounds < max_repair and not all(v.ok for v in res.verify_after):
        log(f"[{lang}] repair round {res.repair_rounds + 1}...")
        try:
            changed = repair.repair_round(llm, lang, target, out, res.verify_after, res.findings)
        except Exception as e:  # network down, model not running, bad reply...
            res.notes.append(f"LLM repair stopped: {type(e).__name__}: {e}")
            break
        res.repair_rounds += 1
        if not changed:
            res.notes.append("LLM produced no valid change; stopping repair")
            break
        res.verify_after = verify(lang, out, run_tests)

    res.files_changed = _changed_files(src, out, lang)
    res.seconds = round(time.time() - t0, 2)
    return res


def run(src: Path, out: Path, lang: str = "auto", target: int = 21, llm: LLM | None = None,
        max_repair: int = 3, run_tests: bool = False, force: bool = False, log=lambda *_: None,
        write_report: bool = True) -> list[Result]:
    src, out = Path(src), Path(out)
    counts = detect_languages(src)
    langs = [l for l, n in counts.items() if n] if lang == "auto" else [lang]
    if not langs:
        return []
    prepare_out(src, out, force)
    results = [migrate_language(src, out, l, target, llm, max_repair, run_tests, log) for l in langs]
    if write_report:
        write_reports(results, src, out)
    return results
