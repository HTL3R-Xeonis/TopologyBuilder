"""The component code names are spelled exactly as the project wrote them (Igdrasyl, Mjonyr, Mimyr, Hugyn, Munyn,
Idynoun, Haymdal); tools and people tend to "correct" them to the standard mythological spellings, which this test
refuses in everything this repository owns.

Allowed: vendored third-party files, the third-party notices and this file itself (it has to name the spellings).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THIS_FILE = Path(__file__).resolve()
STANDARD_SPELLINGS = re.compile(
    r"yggdrasill?|mjolnir|mjölnir|m[ií]mir|huginn|muninn|i[dð]unn|heimdallr?",
    re.IGNORECASE,
)
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".json",
    ".html",
    ".js",
    ".css",
    ".service",
    ".sh",
    ".example",
}
SKIPPED_PARTS = {
    "vendor",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "handoff",
}
# Repository names that no longer exist. TopologyBuilder is not one of them: this repository keeps that name,
# only the component is called Mjonyr.
OLD_NAMES = (
    "TopologyOperator",
    "TopologyGenerator",
    "Docker-Server-Files",
)


def _tracked_files() -> list[Path]:
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=False
        )
        names = [name for name in listing.stdout.decode("utf-8").split("\0") if name]
    except OSError:
        names = []
    if not names:
        names = [
            str(path.relative_to(ROOT))
            for path in ROOT.rglob("*")
            if path.is_file() and not (SKIPPED_PARTS & set(path.parts))
        ]
    files = []
    for name in names:
        path = ROOT / name
        if not path.is_file() or SKIPPED_PARTS & set(Path(name).parts):
            continue
        if path.resolve() == THIS_FILE or path.name == "THIRD_PARTY_NOTICES.md":
            continue
        if path.suffix in TEXT_SUFFIXES or path.name.startswith("."):
            files.append(path)
    return files


def test_the_scan_sees_the_project_files():
    names = {path.name for path in _tracked_files()}
    assert {"README.md", "main.py", "cli.py"} <= names


def test_no_standard_mythological_spelling_of_a_code_name():
    offenders = []
    for path in _tracked_files():
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if STANDARD_SPELLINGS.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == [], (
        "the code names keep their own spelling (Igdrasyl, Mjonyr, Mimyr, Hugyn, Munyn, Idynoun, Haymdal): "
        f"{offenders}"
    )


def test_the_readme_title_carries_the_new_name_and_the_old_one_in_brackets():
    title = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
    assert title == "# Mjonyr (repository TopologyBuilder)"


def test_documents_link_to_the_old_repositories_only_in_a_formerly_note():
    offenders = []
    for name in ("README.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md"):
        for number, line in enumerate(
            (ROOT / name).read_text(encoding="utf-8").splitlines(), 1
        ):
            if re.search(
                r"github\.com/HTL3R-Xeonis/(" + "|".join(OLD_NAMES) + ")", line
            ):
                offenders.append(f"{name}:{number}")
    assert offenders == []
