"""The release version of TopologyBuilder: pyproject.toml is the one source and must be valid SemVer.

The release workflow compares the pushed tag vX.Y.Z with it, so a version that is not SemVer would block a release.
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(-(0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
)


def _version() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    return project["version"]


def version_file_is_semver_000() -> None:
    assert SEMVER.fullmatch(_version())


def version_is_not_the_unmaintained_start_value_001() -> None:
    assert _version() != "0.1.0"


def semver_pattern_takes_release_candidates_and_refuses_the_rest_002() -> None:
    assert SEMVER.fullmatch("1.3.0-rc.1")
    for bad in ("1.3", "v1.3.0", "01.3.0", "1.3.0-", "1.3.0-rc..1", "1.3.0 "):
        assert not SEMVER.fullmatch(bad), bad
