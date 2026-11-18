"""LLM repair step. The model only ever sees the files named in the errors, and every
suggestion is validated before it is written to disk."""
from __future__ import annotations

import re
from pathlib import Path

from .llm import LLM
from .models import Finding, Verify

SYSTEM = (
    "You are a meticulous senior engineer finishing a {task}. You get build/test errors, review notes "
    "and the current file(s). Fix ONLY what is needed so the project builds and its tests pass, preserving "
    "behaviour. Reply with the complete corrected content of every file you change, in exactly this format "
    "and nothing else:\n### FILE: <path exactly as given>\n```{lang}\n<full file content>\n```"
)
TASK = {"python": "Python 2 to Python 3 migration", "java": "Java upgrade to JDK {target}"}
_BLOCK = re.compile(r"###\s*FILE:\s*(\S+)\s*\n```[\w+-]*\n(.*?)\n```", re.S)
_PATH = re.compile(r"([^\s:\"'()]+\.(?:py|java))")
MAX_FILES, MAX_CHARS = 3, 24000


def pick_files(out: Path, verifies: list[Verify], limit: int = MAX_FILES) -> list[str]:
    picked: list[str] = []
    root = str(out.resolve())
    for v in verifies:
        if v.ok:
            continue
        for m in _PATH.finditer(v.output):
            p = m.group(1).replace("\\", "/")
            rel = p[len(root):].lstrip("/") if p.startswith(root) else p.lstrip("./")
            if rel not in picked and (out / rel).is_file():
                picked.append(rel)
    return picked[:limit]


def _valid(lang: str, rel: str, content: str) -> bool:
    if lang == "python":
        try:
            compile(content, rel, "exec", dont_inherit=True)
            return True
        except (SyntaxError, ValueError):
            return False
    return content.count("{") == content.count("}") and bool(content.strip())


def repair_round(llm: LLM, lang: str, target: int, out: Path, verifies: list[Verify],
                 findings: list[Finding]) -> list[str]:
    from .scanner import read_text, write_text

    files = pick_files(out, verifies)
    if not files:
        return []
    errors = "\n\n".join(f"[{v.name}]\n{v.output}" for v in verifies if not v.ok)[:4000]
    notes = "\n".join(f"{f.file}:{f.line} {f.rule}: {f.message}" for f in findings
                      if f.file in files and f.kind != "auto")[:2000]
    bodies, used = [], 0
    for rel in files:
        text, _ = read_text(out / rel)
        used += len(text)
        if used > MAX_CHARS:
            break
        bodies.append(f"### FILE: {rel}\n```{lang}\n{text}\n```")
    user = f"ERRORS:\n{errors}\n\nREVIEW NOTES:\n{notes or '(none)'}\n\nFILES:\n" + "\n\n".join(bodies)
    system = SYSTEM.format(task=TASK[lang].format(target=target), lang=lang)
    reply = llm.complete(system, user)

    changed = []
    for rel, content in _BLOCK.findall(reply):
        if rel not in files:  # never let the model write outside the files we showed it
            continue
        content = content.rstrip("\n") + "\n"
        if _valid(lang, rel, content):
            write_text(out / rel, content, read_text(out / rel)[1])
            changed.append(rel)
    return changed
