"""Python 2 -> 3: deterministic fixers first (fissix, a maintained fork of lib2to3),
then rule-based flags for the things automatic fixers cannot decide."""
from __future__ import annotations

import difflib
import io
import re
import tokenize
from pathlib import Path

from fissix.refactor import RefactoringTool, get_fixers_from_package

from .models import Finding
from .scanner import read_text, write_text

REVIEW_RULES = [
    ("py3-cmp", re.compile(r"(?<![\w.])cmp\s*\("),
     "cmp() was removed; use (a > b) - (a < b) or functools.cmp_to_key"),
    ("py3-__cmp__", re.compile(r"def\s+__cmp__\b"),
     "__cmp__ is ignored in Python 3; define __eq__/__lt__ (functools.total_ordering)"),
    ("py3-sort-cmp", re.compile(r"\b(?:sort|sorted)\(.*\bcmp\s*="),
     "sort(cmp=...) was removed; use key=functools.cmp_to_key(...)"),
    ("py3-hex-codec", re.compile(r"""\.(?:en|de)code\(\s*['"](?:hex|base64|rot13)['"]\s*\)"""),
     "str/bytes codecs changed; use bytes.hex()/bytes.fromhex() or the base64 module"),
    ("py3-base64-string", re.compile(r"base64\.(?:en|de)codestring"),
     "base64.encodestring/decodestring were removed; use encodebytes/decodebytes"),
    ("py3-string-module", re.compile(r"\bstring\.(?:letters|lowercase|uppercase|maketrans|join|split|replace|atoi|strip|lower|upper)\b"),
     "these string-module functions/constants were removed; use str methods or string.ascii_letters"),
    ("py3-bytes-vs-str", re.compile(r"\.(?:send|sendall)\(\s*['\"]"),
     "sockets need bytes in Python 3; encode the string (b'...' or .encode())"),
    ("py3-int-division", re.compile(r"\bint\(.*\s/\s.*\)|\bxrange\b.*\s/\s"),
     "check '/' here: it is now true division; use // if integer division was intended"),
]


def scan_rules(rel: str, text: str) -> list[Finding]:
    found = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for rule_id, pat, msg in REVIEW_RULES:
            if pat.search(line):
                found.append(Finding(rel, i, rule_id, msg, "manual"))
    return found


_LEADING_WS = re.compile(r"^[ \t]+")


def _expand_line(line: str) -> str:
    m = _LEADING_WS.match(line)
    if m and "\t" in m.group(0):
        return m.group(0).expandtabs(8) + line[m.end():]
    return line


def _expand_tabs(text: str) -> str | None:
    """Python 2 treated a tab as 'advance to the next multiple of 8 columns'. Reproduce that with
    spaces. Continuation lines of multi-line strings are left alone. None = cannot do it safely."""
    lines = text.splitlines(keepends=True)
    # The tokenizer rejects the original (that is the bug), so find the strings on an expanded copy.
    # Line numbers do not change when only leading whitespace changes.
    try:
        skip: set[int] = set()
        expanded = "".join(_expand_line(l) for l in lines)
        for tok in tokenize.generate_tokens(io.StringIO(expanded).readline):
            if tok.type == tokenize.STRING and tok.start[0] != tok.end[0]:
                skip.update(range(tok.start[0] + 1, tok.end[0] + 1))
    except (tokenize.TokenError, SyntaxError):
        return None
    return "".join(l if i in skip else _expand_line(l) for i, l in enumerate(lines, 1))


def fix_mixed_tabs(rel: str, text: str, findings: list[Finding]) -> str:
    """Only acts when the file fails to compile with a TabError, and only keeps the result if it compiles."""
    try:
        compile(text, rel, "exec", dont_inherit=True)
        return text
    except TabError:
        fixed = _expand_tabs(text)
        if fixed and fixed != text:
            try:
                compile(fixed, rel, "exec", dont_inherit=True)
            except (SyntaxError, ValueError):
                return text
            findings.append(Finding(rel, 0, "tabs-to-spaces",
                                    "Mixed tabs/spaces (legal in Python 2) expanded to 8-column tab stops", "auto"))
            return fixed
    except (SyntaxError, ValueError):
        pass
    return text


def migrate(root: Path, order: list[str]) -> list[Finding]:
    tool = RefactoringTool(get_fixers_from_package("fissix.fixes"))
    findings: list[Finding] = []
    for rel in order:
        path = root / rel
        text, enc = read_text(path)
        had_newline = text.endswith("\n") or not text
        try:
            new = str(tool.refactor_string(text if had_newline else text + "\n", str(path)))
            if not had_newline and new.endswith("\n"):
                new = new[:-1]
        except Exception as e:  # fissix raises ParseError and friends
            findings.append(Finding(rel, 0, "parse-error",
                                    f"automatic fixers could not parse this file: {type(e).__name__}", "manual"))
            continue
        if new != text:
            n = sum(1 for d in difflib.ndiff(text.splitlines(), new.splitlines()) if d.startswith("+ "))
            findings.append(Finding(rel, 0, "2to3", f"{n} line(s) rewritten by automatic fixers", "auto"))
        final = fix_mixed_tabs(rel, new, findings)
        if final != text:
            write_text(path, final, enc)
        findings += scan_rules(rel, final)
    return findings
