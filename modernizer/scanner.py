"""Builds a lightweight 'map' of a codebase: files, size, internal dependencies.

The map is used to migrate leaf files first and to give the repair step focused context.
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "target", "build", ".venv", "venv", "__pycache__",
             ".idea", ".gradle", ".tox", ".mypy_cache", ".pytest_cache"}
EXT = {"python": (".py",), "java": (".java",)}


def iter_files(root: Path, lang: str):
    exts = EXT[lang]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(exts):
                yield Path(dirpath) / name


def read_text(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


def write_text(path: Path, text: str, enc: str = "utf-8") -> None:
    path.write_bytes(text.encode(enc))


def detect_languages(root: Path) -> dict[str, int]:
    return {lang: sum(1 for _ in iter_files(root, lang)) for lang in EXT}


@dataclass
class ProjectMap:
    root: Path
    lang: str
    loc: dict[str, int] = field(default_factory=dict)
    deps: dict[str, set[str]] = field(default_factory=dict)


# ---------- Python ----------
_PY_IMPORT = re.compile(r"^\s*import\s+(.+)$", re.M)
_PY_FROM = re.compile(r"^\s*from\s+(\.*)([\w.]*)\s+import\s+(.+)$", re.M)


def _py_module(rel: str) -> str:
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _py_aliases(module: str) -> list[str]:
    parts = module.split(".")
    return [".".join(parts[i:]) for i in range(len(parts))] if module else []


def _build_python(pm: ProjectMap, texts: dict[str, str]) -> None:
    alias_to_file: dict[str, str] = {}
    for rel in texts:
        for a in _py_aliases(_py_module(rel)):
            alias_to_file.setdefault(a, rel)

    def resolve(name: str) -> str | None:
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            hit = alias_to_file.get(".".join(parts[:i]))
            if hit:
                return hit
        return None

    for rel, text in texts.items():
        found: set[str] = set()
        pkg = _py_module(rel) if rel.endswith("__init__.py") else _py_module(rel).rpartition(".")[0]
        for m in _PY_IMPORT.finditer(text):
            for item in m.group(1).split(","):
                name = item.strip().split(" as ")[0].strip().split("#")[0].strip()
                if name and (hit := resolve(name)):
                    found.add(hit)
        for m in _PY_FROM.finditer(text):
            dots, mod, names = m.groups()
            base = mod
            if dots:
                up = pkg.split(".") if pkg else []
                up = up[: max(len(up) - (len(dots) - 1), 0)]
                base = ".".join([p for p in up + ([mod] if mod else []) if p])
            candidates = [base] + [f"{base}.{n.strip().split(' as ')[0].strip('() ')}" for n in names.split(",")]
            for c in candidates:
                if c and (hit := resolve(c)):
                    found.add(hit)
        found.discard(rel)
        pm.deps[rel] = found


# ---------- Java ----------
_J_PKG = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
_J_IMP = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+?)(\.\*)?\s*;", re.M)


def _build_java(pm: ProjectMap, texts: dict[str, str]) -> None:
    fqn_to_file: dict[str, str] = {}
    for rel, text in texts.items():
        m = _J_PKG.search(text)
        pkg = m.group(1) if m else ""
        stem = rel.rsplit("/", 1)[-1][:-5]
        fqn_to_file[f"{pkg}.{stem}" if pkg else stem] = rel
    for rel, text in texts.items():
        found: set[str] = set()
        for m in _J_IMP.finditer(text):
            name, wildcard = m.group(1), m.group(2)
            if wildcard:
                found |= {f for q, f in fqn_to_file.items() if q.rpartition(".")[0] == name}
                continue
            parts = name.split(".")
            for i in range(len(parts), 0, -1):
                hit = fqn_to_file.get(".".join(parts[:i]))
                if hit:
                    found.add(hit)
                    break
        found.discard(rel)
        pm.deps[rel] = found


def build_map(root: Path, lang: str) -> ProjectMap:
    pm = ProjectMap(root=root, lang=lang)
    texts: dict[str, str] = {}
    for p in iter_files(root, lang):
        rel = p.relative_to(root).as_posix()
        text, _ = read_text(p)
        texts[rel] = text
        pm.loc[rel] = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    (_build_python if lang == "python" else _build_java)(pm, texts)
    return pm


def migration_order(pm: ProjectMap) -> list[str]:
    """Dependencies first (leaf files), so each file is migrated after what it imports."""
    deps = {f: {d for d in ds if d in pm.loc} for f, ds in pm.deps.items()}
    remaining, order = set(deps), []
    while remaining:
        ready = sorted(f for f in remaining if not (deps[f] & remaining))
        if not ready:  # import cycle: fall back to a stable order
            order.extend(sorted(remaining))
            break
        order.extend(ready)
        remaining -= set(ready)
    return order


# ---------- Detection helpers ----------
_JAVA_VERSION_PATTERNS = [
    r"<maven\.compiler\.(?:release|source|target)>\s*([\d.]+)",
    r"<java\.version>\s*([\d.]+)",
    r"<release>\s*([\d.]+)",
    r"<source>\s*(1\.\d|\d{1,2})\s*</source>",
    r"(?:source|target)Compatibility\s*=?\s*['\"]?(?:JavaVersion\.VERSION_)?([\d._]+)",
    r"JavaLanguageVersion\.of\(\s*(\d+)\s*\)",
]


def java_version(root: Path) -> str | None:
    for name in ("pom.xml", "build.gradle", "build.gradle.kts"):
        f = root / name
        if not f.is_file():
            continue
        text, _ = read_text(f)
        for pat in _JAVA_VERSION_PATTERNS:
            m = re.search(pat, text)
            if m:
                v = m.group(1).replace("_", ".")
                return v[2:] if v.startswith("1.") else v
    return None


def python2_suspects(root: Path) -> tuple[int, int]:
    """(total .py files, files that do not parse as Python 3)."""
    total = bad = 0
    for p in iter_files(root, "python"):
        total += 1
        text, _ = read_text(p)
        try:
            ast.parse(text)
        except (SyntaxError, ValueError):
            bad += 1
    return total, bad
