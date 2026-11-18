from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Finding:
    file: str
    line: int
    rule: str
    message: str
    kind: str = "manual"  # "auto" = rewritten by a rule, "manual" = needs human/LLM, "info" = advice


@dataclass
class Verify:
    name: str  # compile | tests | build | build+tests
    ok: bool
    skipped: bool = False
    command: str = ""
    output: str = ""


@dataclass
class Result:
    project: str
    language: str
    out_dir: str
    files_scanned: int = 0
    files_changed: int = 0
    findings: list[Finding] = field(default_factory=list)
    verify_before: list[Verify] = field(default_factory=list)
    verify_after: list[Verify] = field(default_factory=list)
    repair_rounds: int = 0
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def status(verifies: list[Verify], names: tuple[str, ...] | None = None) -> str:
    vs = [v for v in verifies if names is None or v.name in names]
    if not vs:
        return "n/a"
    if not [v for v in vs if not v.skipped]:
        return "skipped"
    return "pass" if all(v.ok for v in vs) else "fail"
