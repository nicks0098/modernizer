"""Verification: the step that turns 'the AI changed code' into 'we know whether it works'."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .models import Verify
from .scanner import iter_files, read_text

MAX_OUT = 6000


def _run(cmd: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout + p.stderr)[-MAX_OUT:]
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as e:
        return 127, str(e)


# ---------- Python ----------
def compile_errors(root: Path) -> list[tuple[str, int, str]]:
    errors = []
    for p in iter_files(root, "python"):
        rel = p.relative_to(root).as_posix()
        text, _ = read_text(p)
        try:
            compile(text, rel, "exec", dont_inherit=True)
        except SyntaxError as e:
            errors.append((rel, e.lineno or 0, e.msg or "syntax error"))
        except ValueError as e:
            errors.append((rel, 0, str(e)))
    return errors


def _has_python_tests(root: Path) -> bool:
    for p in iter_files(root, "python"):
        n = p.name
        if n.startswith("test") or n.endswith("_test.py") or n.endswith("tests.py") or \
                {"test", "tests"} & set(p.relative_to(root).parts[:-1]):
            return True
    return False


def verify_python(root: Path, run_tests: bool) -> list[Verify]:
    errs = compile_errors(root)
    out = [Verify("compile", not errs, output="\n".join(f"{f}:{l}: {m}" for f, l, m in errs)[:MAX_OUT])]
    if not run_tests:
        out.append(Verify("tests", True, skipped=True, output="tests not run (use --run-tests)"))
    elif not _has_python_tests(root):
        out.append(Verify("tests", True, skipped=True, output="no tests found"))
    elif errs:
        out.append(Verify("tests", False, skipped=True, output="skipped: fix compile errors first"))
    else:
        if importlib.util.find_spec("pytest"):
            cmd = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
                   "-o", "python_files=test_*.py *_test.py tests.py"]
        else:
            cmd = [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test*.py"]
        rc, text = _run(cmd, root)
        if rc == 5:  # pytest: no tests were collected
            out.append(Verify("tests", True, skipped=True, command=" ".join(cmd), output="no tests collected"))
        else:
            out.append(Verify("tests", rc == 0, command=" ".join(cmd), output=text))
    return out


# ---------- Java ----------
_COMPILE_JAVA = """import javax.tools.*;
import java.nio.file.*;
import java.util.*;

public class Compile {
    public static void main(String[] a) throws Exception {
        JavaCompiler c = ToolProvider.getSystemJavaCompiler();
        if (c == null) { System.err.println("no system java compiler"); System.exit(127); }
        List<String> opts = new ArrayList<>(List.of("-proc:none", "-d", Files.createTempDirectory("mod").toString()));
        opts.addAll(Arrays.asList(a));
        System.exit(c.run(null, null, null, opts.toArray(new String[0])));
    }
}
"""


def javac_command(workdir: Path) -> list[str] | None:
    """`javac` if installed; otherwise drive the JDK compiler module through the `java` launcher."""
    if shutil.which("javac"):
        return ["javac", "-proc:none", "-d", str(workdir / "classes")]
    if shutil.which("java"):
        src = workdir / "Compile.java"
        src.write_text(_COMPILE_JAVA)
        rc, _ = _run(["java", str(src)], workdir, timeout=60)
        if rc != 127 and "no system java compiler" not in _:
            return ["java", str(src)]
    return None


def _tool(root: Path, wrapper: str, system_name: str) -> str | None:
    w = root / wrapper
    if w.is_file() and os.access(w, os.X_OK):
        return str(w)
    return shutil.which(system_name)


def verify_java(root: Path, run_tests: bool) -> list[Verify]:
    name = "build+tests" if run_tests else "build"
    cmd = None
    if (root / "pom.xml").is_file() and (mvn := _tool(root, "mvnw", "mvn")):
        cmd = [mvn, "-q", "-B"] + (["test"] if run_tests else ["-DskipTests", "test-compile"])
    elif ((root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file()) and (
            gr := _tool(root, "gradlew", "gradle")):
        cmd = [gr, "-q", "--console=plain"] + (["test"] if run_tests else ["compileJava", "compileTestJava"])
    if cmd:
        rc, text = _run(cmd, root, timeout=1800)
        return [Verify(name, rc == 0, command=" ".join(cmd), output=text)]

    files = [str(p) for p in iter_files(root, "java")]
    if not files:
        return [Verify(name, True, skipped=True, output="no java files")]
    with tempfile.TemporaryDirectory() as tmp:
        base = javac_command(Path(tmp))
        if base is None:
            return [Verify(name, True, skipped=True, output="no maven, gradle, javac or JDK compiler module found")]
        rc, text = _run(base + files, root)
    note = "\n(compiler only: no dependency classpath, so missing-library errors can be false alarms)"
    return [Verify("build", rc == 0, command="javac (no classpath)", output=text + (note if rc else ""))]


def verify(lang: str, root: Path, run_tests: bool) -> list[Verify]:
    return verify_python(root, run_tests) if lang == "python" else verify_java(root, run_tests)
