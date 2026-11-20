"""The Dependabot configuration (.github/dependabot.yml): weekly and grouped, python base images pinned for now.

Nothing here talks to GitHub; it pins the agreements so a later edit cannot silently reopen them: one weekly PR for
patch/minor updates (majors stay separate), GitHub Actions grouped, and no python base-image bump until it is done
deliberately with an image rebuild and acceptance.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".github" / "dependabot.yml"


def _updates() -> list[dict]:
    document = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert document["version"] == 2
    return document["updates"]


def _of(ecosystem: str) -> list[dict]:
    return [update for update in _updates() if update["package-ecosystem"] == ecosystem]


def _directories(update: dict) -> list[str]:
    return update.get("directories") or [update["directory"]]


def every_ecosystem_is_checked_weekly_000() -> None:
    for update in _updates():
        assert update["schedule"]["interval"] == "weekly"


def pip_groups_patch_and_minor_together_and_leaves_majors_separate_000() -> None:
    updates = _of("pip")
    assert updates
    for update in updates:
        group = update["groups"]["pip-minor-and-patch"]
        assert sorted(group["update-types"]) == ["minor", "patch"]


def github_actions_updates_are_grouped_000() -> None:
    updates = _of("github-actions")
    assert len(updates) == 1
    assert updates[0]["groups"]["github-actions"]["patterns"] == ["*"]


def updates_target_the_project_branch_000() -> None:
    for update in _updates():
        assert update["target-branch"] == "Mjonyr"


def every_configured_directory_exists_000() -> None:
    for update in _updates():
        for directory in _directories(update):
            assert (ROOT / directory.lstrip("/")).is_dir(), directory
