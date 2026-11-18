import shutil
import tempfile
from pathlib import Path

import pytest

from modernizer import pipeline
from modernizer.llm import StaticLLM
from modernizer.models import status
from modernizer.verify import javac_command
from modernizer.scanner import build_map, java_version, migration_order, python2_suspects

EX = Path(__file__).resolve().parent.parent / "examples"


def copy(name, tmp_path):
    dst = tmp_path / name
    shutil.copytree(EX / name, dst)
    return dst


# ---------------- scanner ----------------
def test_python_dependency_order(tmp_path):
    src = copy("legacy_py", tmp_path)
    order = migration_order(build_map(src, "python"))
    assert order.index("app/util.py") < order.index("app/core.py")


def test_detects_python2_and_java_version(tmp_path):
    total, bad = python2_suspects(copy("legacy_py", tmp_path))
    assert bad >= 2 and total >= 3
    assert java_version(copy("legacy_java", tmp_path)) == "8"


def test_java_import_graph(tmp_path):
    pm = build_map(copy("legacy_java", tmp_path), "java")
    assert pm.deps["src/main/java/com/acme/App.java"] == {"src/main/java/com/acme/Util.java"}


# ---------------- python ----------------
def test_python_end_to_end(tmp_path):
    src = copy("legacy_py", tmp_path)
    out = tmp_path / "out"
    (r,) = pipeline.run(src, out, lang="python", run_tests=True)
    assert status(r.verify_before, ("compile",)) == "fail"      # py2 code does not compile under py3
    assert status(r.verify_after) == "pass"                      # compiles and tests pass after
    core = (out / "app/core.py").read_text()
    assert "print(fmt(key, count))" in core and "range(" in core and ".items()" in core
    assert any(f.rule == "py3-string-module" for f in r.findings)  # string.upper needs a human
    assert "print fmt" in (src / "app/core.py").read_text()     # original untouched
    assert (out / "MODERNIZER_REPORT.md").exists() and (out / "modernizer.diff").read_text()


def test_llm_repair_only_touches_files_it_was_shown(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "bad.py").write_text("def f(x:\n    return x\n")
    (src / "good.py").write_text("X = 1\n")
    llm = StaticLLM(lambda s, u: "### FILE: good.py\n```python\nX = 2\n```\n"
                                 "### FILE: bad.py\n```python\ndef f(x):\n    return x\n```")
    (r,) = pipeline.run(src, tmp_path / "out", lang="python", llm=llm)
    assert r.repair_rounds == 1 and status(r.verify_after, ("compile",)) == "pass"
    assert (tmp_path / "out/good.py").read_text() == "X = 1\n"   # not shown to the model -> not writable


def test_llm_invalid_code_is_rejected(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "bad.py").write_text("def f(x:\n    return x\n")
    llm = StaticLLM(lambda s, u: "### FILE: bad.py\n```python\ndef f(x:\n```")
    (r,) = pipeline.run(src, tmp_path / "out", lang="python", llm=llm)
    assert status(r.verify_after, ("compile",)) == "fail" and llm.calls == 1
    assert (tmp_path / "out/bad.py").read_text() == (src / "bad.py").read_text()


def test_llm_failure_is_reported_not_raised(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "bad.py").write_text("def f(x:\n")

    def boom(s, u):
        raise ConnectionError("no model running")

    (r,) = pipeline.run(src, tmp_path / "out", lang="python", llm=StaticLLM(boom))
    assert any("ConnectionError" in n for n in r.notes)


# ---------------- java ----------------
def test_java_rules_and_build_bump(tmp_path):
    out = tmp_path / "out"
    (r,) = pipeline.run(copy("legacy_java", tmp_path), out, lang="java", target=21)
    util = (out / "src/main/java/com/acme/Util.java").read_text()
    assert "Integer.valueOf(s)" in util
    assert "java.util.Base64.getEncoder().encodeToString(b)" in util
    assert "import sun.misc.BASE64Encoder" not in util
    assert "// new Integer(5) in a comment" in util              # comments untouched
    assert "<maven.compiler.source>21<" in (out / "pom.xml").read_text()
    rules = {f.rule for f in r.findings}
    assert {"jaxb-removed", "finalize", "thread-stop", "dep-check", "build-version"} <= rules


def test_java_rules_are_target_aware(tmp_path):
    (r,) = pipeline.run(copy("legacy_java", tmp_path), tmp_path / "out", lang="java", target=11)
    rules = {f.rule for f in r.findings}
    assert "jaxb-removed" in rules
    assert "finalize" not in rules and "thread-stop" not in rules   # only matter on 18+/20+


def test_refuses_output_inside_source(tmp_path):
    src = copy("legacy_py", tmp_path)
    try:
        pipeline.run(src, src / "out", lang="python")
        assert False, "should have refused"
    except ValueError:
        pass


# ---------------- java: real compilation (needs a JDK compiler) ----------------
def _have_compiler():
    with tempfile.TemporaryDirectory() as d:
        return javac_command(Path(d)) is not None


@pytest.mark.skipif(not _have_compiler(), reason="no JDK compiler available")
def test_java_rewrites_really_compile(tmp_path):
    src = tmp_path / "proj"
    (src / "src").mkdir(parents=True)
    (src / "src/Demo.java").write_text(
        "import sun.misc.BASE64Encoder;\n"
        "public class Demo {\n"
        "  public static void main(String[] a) {\n"
        "    Integer i = new Integer(5);\n"
        "    System.out.println(new BASE64Encoder().encode(new byte[]{1, 2, 3}) + i);\n"
        "  }\n}\n")
    (r,) = pipeline.run(src, tmp_path / "out", lang="java", target=21)
    assert status(r.verify_before) == "fail"   # removed JDK API: does not compile on a modern JDK
    assert status(r.verify_after) == "pass"    # compiles after the automatic rewrites


# ---------------- mixed tabs (found by the real-world benchmark on Nscan) ----------------
def test_mixed_tabs_and_spaces_are_fixed_without_touching_strings(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    # Python 2: the tab and the 8 spaces are the same indentation level. Python 3 rejects it.
    (src / "m.py").write_text('def f():\n\tx = 1\n        return x\n\n\nDOC = """\n\tkeep this tab\n"""\n')
    (r,) = pipeline.run(src, tmp_path / "out", lang="python")
    assert status(r.verify_before, ("compile",)) == "fail"
    assert status(r.verify_after, ("compile",)) == "pass"
    text = (tmp_path / "out/m.py").read_text()
    assert "\tkeep this tab" in text            # string content untouched
    assert "\tx = 1" not in text                # code indentation converted
    assert any(f.rule == "tabs-to-spaces" for f in r.findings)
