"""The parts talk to each other only through contracts/ (CLAUDE.md, "Kontrakten först").

Every Python file in a part is read, and its imports are checked against the table below.
A part that does not exist yet is skipped, so the rule is in place before the code is.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Which other parts each part may import. Drift, Planering, Synk and Integrationer are the
# Hub's four parts; they share the domain model in core/ but never import each other.
# ID, TKL and CAD only see the contracts. hub/ is the start program that brings the Hub's
# parts together.
HUB_PARTS = {"drift", "planering", "synk", "integrationer"}
ALLOWED: dict[str, set[str]] = {
    "contracts": set(),
    "core": {"contracts"},
    **{part: {"contracts", "core"} for part in HUB_PARTS},
    "id": {"contracts"},
    "tkl": {"contracts"},
    "cad": {"contracts"},
    "hub": {"contracts", "core", *HUB_PARTS},
}
PARTS = set(ALLOWED)


def imported_parts(source: str) -> set[str]:
    """The parts a Python file imports, by the first name of each absolute import."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names & PARTS


def violations(root: Path) -> list[str]:
    found: list[str] = []
    for part, allowed in sorted(ALLOWED.items()):
        folder = root / part
        if not folder.is_dir():
            continue
        for file in sorted(folder.rglob("*.py")):
            for other in sorted(imported_parts(file.read_text(encoding="utf-8")) - {part}):
                if other not in allowed:
                    found.append(f"{file.relative_to(root)} importerar {other}")
    return found


def test_no_part_imports_another_parts_inner_code() -> None:
    assert violations(ROOT) == []


def test_the_rule_catches_a_violation(tmp_path: Path) -> None:
    (tmp_path / "drift").mkdir()
    (tmp_path / "drift" / "ok.py").write_text("import contracts\nfrom core import model\n")
    (tmp_path / "drift" / "bad.py").write_text("from planering.drafts import Draft\n")
    (tmp_path / "tkl").mkdir()
    (tmp_path / "tkl" / "bad.py").write_text("import drift.engine\n")
    assert violations(tmp_path) == [
        "drift/bad.py importerar planering",
        "tkl/bad.py importerar drift",
    ]


def test_relative_imports_stay_inside_the_part() -> None:
    assert imported_parts("from . import model\nfrom .engine import run\n") == set()
