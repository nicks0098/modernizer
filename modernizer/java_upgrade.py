"""Java 8 -> 17/21 upgrade: target-aware rules.

Each rule is only applied when the target JDK is >= the version where the problem appears,
so upgrading to 11 does not produce noise about things that only break in 18+.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import Finding
from .scanner import read_text, write_text


@dataclass(frozen=True)
class Rule:
    id: str
    since: int  # first JDK where this matters
    pattern: re.Pattern
    message: str
    replacement: str | None = None  # set => auto-fix
    kind: str = "manual"
    needs: re.Pattern | None = None  # file must also match this (cheap context check)


def _r(id, since, pat, msg, repl=None, kind="manual", needs=None):
    return Rule(id, since, re.compile(pat), msg, repl, "auto" if repl is not None else kind,
                re.compile(needs) if needs else None)


RULES = [
    # ---- safe automatic rewrites ----
    _r("boxed-constructor", 9, r"\bnew\s+(Integer|Long|Short|Byte|Double|Float|Boolean|Character)\s*\(",
       "Boxed-type constructors are deprecated for removal; replaced with valueOf()", r"\1.valueOf("),
    _r("sun-base64-encode", 9, r"new\s+(?:sun\.misc\.)?BASE64Encoder\(\)\s*\.encode\(",
       "sun.misc.BASE64Encoder is gone; replaced with java.util.Base64", "java.util.Base64.getEncoder().encodeToString("),
    _r("sun-base64-decode", 9, r"new\s+(?:sun\.misc\.)?BASE64Decoder\(\)\s*\.decodeBuffer\(",
       "sun.misc.BASE64Decoder is gone; replaced with java.util.Base64 (no longer throws IOException)",
       "java.util.Base64.getDecoder().decode("),
    # ---- removed from the JDK ----
    _r("jaxb-removed", 11, r"\bjavax\.xml\.bind\b",
       "JAXB was removed from the JDK in 11: add jakarta.xml.bind-api plus a runtime such as org.glassfish.jaxb:jaxb-runtime"),
    _r("javax-annotation-removed", 11, r"\bjavax\.annotation\.(?:PostConstruct|PreDestroy|Resource|Generated)\b",
       "javax.annotation was removed in 11: add jakarta.annotation-api (1.3.x keeps the javax namespace)"),
    _r("javax-activation-removed", 11, r"\bjavax\.activation\b", "JAF was removed in 11: add jakarta.activation"),
    _r("jaxws-removed", 11, r"\bjavax\.(?:xml\.ws|jws|xml\.soap)\b",
       "JAX-WS/SAAJ were removed in 11: add the jakarta.xml.ws / jakarta.xml.soap dependencies"),
    _r("corba-removed", 11, r"\borg\.omg\.CORBA\b|\bjavax\.rmi\.CORBA\b", "CORBA was removed in 11; no JDK replacement"),
    _r("nashorn-removed", 15, r"""getEngineByName\(\s*"(?:nashorn|javascript|js)"\s*\)|\bjdk\.nashorn\b""",
       "Nashorn was removed in 15: use GraalJS or Rhino"),
    _r("pack200-removed", 14, r"\bjava\.util\.jar\.Pack200\b", "Pack200 was removed in 14"),
    # ---- encapsulation / deprecation-for-removal ----
    _r("internal-api", 16,
       r"\bimport\s+(?:static\s+)?(?:sun\.(?!misc\.BASE64)|com\.sun\.(?!net\.httpserver|source|tools))",
       "JDK-internal API is strongly encapsulated since 16/17: use a supported API or --add-exports as a stopgap"),
    _r("applet", 17, r"\bjava\.applet\b|\bextends\s+J?Applet\b", "Applet API is deprecated for removal"),
    _r("security-manager", 17,
       r"\bSystem\.(?:get|set)SecurityManager\b|\bnew\s+SecurityManager\b|\bextends\s+SecurityManager\b",
       "SecurityManager is deprecated for removal; setSecurityManager throws by default from 18"),
    _r("finalize", 18, r"\bvoid\s+finalize\s*\(\s*\)",
       "finalize() is deprecated for removal: use try-with-resources or java.lang.ref.Cleaner"),
    _r("thread-stop", 20, r"\.(?:stop|suspend|resume)\(\s*\)",
       "If this is a Thread: stop/suspend/resume throw UnsupportedOperationException from 20; use interruption flags",
       needs=r"\bThread\b"),
    _r("run-finalizers", 11, r"runFinalizersOnExit", "runFinalizersOnExit was removed"),
    # ---- advice only ----
    _r("reflective-access", 16, r"\.setAccessible\(\s*true\s*\)",
       "May throw InaccessibleObjectException on JDK internals (16+): add --add-opens if it targets JDK classes", kind="info"),
    _r("class-newinstance", 9, r"\.newInstance\(\)",
       "If this is Class.newInstance(): deprecated, use getDeclaredConstructor().newInstance()", kind="info"),
]

DEP_HINTS = [
    ("lombok", "Lombok needs >= 1.18.22 for JDK 17 and >= 1.18.30 for JDK 21"),
    ("jacoco", "JaCoCo needs >= 0.8.7 for JDK 17 and >= 0.8.11 for JDK 21"),
    ("maven-compiler-plugin", "maven-compiler-plugin should be >= 3.8.1 (3.11+ recommended)"),
    ("maven-surefire", "Surefire should be >= 2.22.2 (3.x recommended)"),
    ("cglib", "cglib fails on JDK 17+ (reflective access); move to ByteBuddy or a maintained fork"),
    ("powermock", "PowerMock has poor JDK 17+ support; migrate to Mockito inline mocking"),
    ("javassist", "Javassist should be >= 3.29 for newer class file versions"),
    ("mockito", "Mockito >= 4.x for JDK 17 and >= 5.x for JDK 21"),
    ("spring-boot", "Spring Boot >= 2.5 runs on 17; Boot 3 requires 17 and moves to jakarta.*"),
    ("hibernate", "Hibernate 5.6+ / 6.x are recommended for JDK 17+"),
]


def _newer(value: str, target: int) -> str | None:
    m = re.fullmatch(r"(?:1\.)?(\d{1,2})", value.strip())
    if m and int(m.group(1)) < target:
        return str(target)
    return None


def bump_build_files(root: Path, target: int) -> list[Finding]:
    findings: list[Finding] = []

    def sub(rel: str, text: str, pat: str, fn) -> str:
        def cb(m):
            new = fn(m)
            if new is not None and new != m.group(0):
                findings.append(Finding(rel, text.count("\n", 0, m.start()) + 1, "build-version",
                                        f"{m.group(0).strip()[:60]} -> {new.strip()[:60]}", "auto"))
                return new
            return m.group(0)
        return re.sub(pat, cb, text)

    pom = root / "pom.xml"
    if pom.is_file():
        text, enc = read_text(pom)
        orig = text
        text = sub("pom.xml", text,
                   r"(<(?:maven\.compiler\.(?:source|target|release)|java\.version|release|source|target)>\s*)([\d.]+)(\s*</)",
                   lambda m: (m.group(1) + v + m.group(3)) if (v := _newer(m.group(2), target)) else None)
        if text != orig:
            write_text(pom, text, enc)
    for name in ("build.gradle", "build.gradle.kts"):
        gf = root / name
        if not gf.is_file():
            continue
        text, enc = read_text(gf)
        orig = text
        text = sub(name, text, r"JavaVersion\.VERSION_(\d+(?:_\d+)?)",
                   lambda m: f"JavaVersion.VERSION_{target}" if _newer(m.group(1).replace("_", "."), target) else None)
        text = sub(name, text, r"((?:source|target)Compatibility\s*=?\s*)(['\"]?)(\d+(?:\.\d+)?)(['\"]?)",
                   lambda m: (m.group(1) + m.group(2) + v + m.group(4)) if (v := _newer(m.group(3), target)) else None)
        text = sub(name, text, r"(JavaLanguageVersion\.of\(\s*)(\d+)(\s*\))",
                   lambda m: (m.group(1) + v + m.group(3)) if (v := _newer(m.group(2), target)) else None)
        text = sub(name, text, r"(jvmTarget\s*=\s*['\"])(\d+(?:\.\d+)?)(['\"])",
                   lambda m: (m.group(1) + v + m.group(3)) if (v := _newer(m.group(2), target)) else None)
        if text != orig:
            write_text(gf, text, enc)
    return findings


def dependency_hints(root: Path) -> list[Finding]:
    out = []
    for name in ("pom.xml", "build.gradle", "build.gradle.kts"):
        f = root / name
        if f.is_file():
            text = read_text(f)[0].lower()
            out += [Finding(name, 0, "dep-check", advice, "info") for key, advice in DEP_HINTS if key in text]
    wrapper = root / "gradle/wrapper/gradle-wrapper.properties"
    if wrapper.is_file():
        m = re.search(r"gradle-(\d+)\.(\d+)", read_text(wrapper)[0])
        if m and (int(m.group(1)), int(m.group(2))) < (8, 5):
            out.append(Finding("gradle/wrapper/gradle-wrapper.properties", 0, "dep-check",
                               "Gradle 8.5+ is needed to run on JDK 21 (7.3+ for 17)", "info"))
    return out


def _drop_unused_imports(text: str) -> str:
    for name in ("BASE64Encoder", "BASE64Decoder"):
        imp = re.compile(rf"^import\s+sun\.misc\.{name}\s*;[ \t]*\r?\n", re.M)
        if imp.search(text):
            rest = imp.sub("", text)
            if name not in rest:
                text = rest
    return text


def migrate(root: Path, order: list[str], target: int) -> list[Finding]:
    findings = bump_build_files(root, target) + dependency_hints(root)
    rules = [r for r in RULES if target >= r.since]
    for rel in order:
        path = root / rel
        text, enc = read_text(path)
        out_lines = []
        file_rules = [r for r in rules if r.needs is None or r.needs.search(text)]
        for i, line in enumerate(text.splitlines(keepends=True), 1):
            if line.lstrip().startswith(("//", "*", "/*")):
                out_lines.append(line)
                continue
            for rule in file_rules:
                if not rule.pattern.search(line):
                    continue
                if rule.replacement is not None:
                    new_line = rule.pattern.sub(rule.replacement, line)
                    if new_line != line:
                        findings.append(Finding(rel, i, rule.id, rule.message, "auto"))
                        line = new_line
                else:
                    findings.append(Finding(rel, i, rule.id, rule.message, rule.kind))
            out_lines.append(line)
        new = _drop_unused_imports("".join(out_lines))
        if new != text:
            write_text(path, new, enc)
    return findings
