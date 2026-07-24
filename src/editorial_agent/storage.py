"""Safe, versioned filesystem storage for editorial projects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DRAFT_FILENAME_PATTERN = re.compile(
    r"^(?P<version>[0-9]+)-"
    r"(?P<stage>first_draft|revision|final)\.md$"
)
ALLOWED_DRAFT_STAGES = (
    "first_draft",
    "revision",
    "final",
)


class StorageError(Exception):
    """Base exception for editorial storage failures."""


class InvalidProjectIdError(StorageError):
    """Raised when a project ID is empty, unsafe, or malformed."""


class PressReleaseNotFoundError(StorageError):
    """Raised when a project has no readable press release."""


class InvalidDraftError(StorageError):
    """Raised when draft content or stage is invalid."""


class InvalidVersionError(StorageError):
    """Raised when a draft version number is invalid."""


class DraftNotFoundError(StorageError):
    """Raised when a requested LinkedIn draft version does not exist."""


@dataclass(frozen=True)
class DraftVersion:
    """One stored version of a LinkedIn post."""

    project_id: str
    version: int
    stage: str
    path: Path
    content: str


class ProjectStore:
    """Store editorial projects under one controlled root directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=False)

    def read_press_release(self, project_id: str) -> str:
        """Read one project's stored press release as UTF-8 text."""

        project_dir = self._project_dir(project_id)
        source_path = project_dir / "source" / "press_release.md"

        try:
            content = source_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PressReleaseNotFoundError(
                f"Project {project_id} has no stored press release."
            ) from exc

        if not content.strip():
            raise PressReleaseNotFoundError(
                f"Project {project_id} has an empty press release."
            )

        return content

    def save_linkedin_draft(
        self,
        project_id: str,
        content: str,
        stage: str,
    ) -> DraftVersion:
        """Save a new LinkedIn draft version without overwriting old versions."""

        project_dir = self._project_dir(project_id)

        if not content.strip():
            raise InvalidDraftError("Draft content must not be empty.")

        if stage not in ALLOWED_DRAFT_STAGES:
            allowed = ", ".join(ALLOWED_DRAFT_STAGES)
            raise InvalidDraftError(
                f"Unsupported draft stage {stage!r}. "
                f"Expected one of: {allowed}."
            )

        linkedin_dir = project_dir / "linkedin"
        linkedin_dir.mkdir(parents=True, exist_ok=True)

        version = self._next_version(linkedin_dir)
        filename = f"{version:03d}-{stage}.md"
        path = linkedin_dir / filename

        if path.exists():
            raise StorageError(
                f"Refusing to overwrite existing draft version {version}."
            )

        path.write_text(content, encoding="utf-8")

        return DraftVersion(
            project_id=project_id,
            version=version,
            stage=stage,
            path=path,
            content=content,
        )

    def read_linkedin_draft(
        self,
        project_id: str,
        version: int,
    ) -> DraftVersion:
        """Read a specific saved LinkedIn draft version."""

        project_dir = self._project_dir(project_id)

        if isinstance(version, bool) or not isinstance(version, int):
            raise InvalidVersionError(
                "Draft version must be a positive integer."
            )

        if version < 1:
            raise InvalidVersionError(
                "Draft version must be a positive integer."
            )

        linkedin_dir = project_dir / "linkedin"

        for path in self._draft_paths(linkedin_dir):
            match = DRAFT_FILENAME_PATTERN.fullmatch(path.name)

            if match is None:
                continue

            stored_version = int(match.group("version"))

            if stored_version != version:
                continue

            content = path.read_text(encoding="utf-8")

            return DraftVersion(
                project_id=project_id,
                version=stored_version,
                stage=match.group("stage"),
                path=path,
                content=content,
            )

        raise DraftNotFoundError(
            f"Project {project_id} has no LinkedIn draft version {version}."
        )

    def _project_dir(self, project_id: str) -> Path:
        """Validate a project ID and resolve its safe workspace path."""

        if not PROJECT_ID_PATTERN.fullmatch(project_id):
            raise InvalidProjectIdError(
                "Project ID must contain only lowercase letters, numbers, "
                "hyphens, or underscores and be 1-64 characters long."
            )

        project_dir = (self.root / project_id).resolve(strict=False)

        if not project_dir.is_relative_to(self.root):
            raise InvalidProjectIdError(
                "Project path must remain inside the workspace."
            )

        return project_dir

    @staticmethod
    def _draft_paths(linkedin_dir: Path) -> list[Path]:
        """Return recognized draft files sorted by version."""

        if not linkedin_dir.exists():
            return []

        recognized: list[tuple[int, Path]] = []

        for path in linkedin_dir.iterdir():
            if not path.is_file():
                continue

            match = DRAFT_FILENAME_PATTERN.fullmatch(path.name)

            if match is None:
                continue

            recognized.append(
                (
                    int(match.group("version")),
                    path,
                )
            )

        recognized.sort(key=lambda item: item[0])

        return [path for _, path in recognized]

    def _next_version(self, linkedin_dir: Path) -> int:
        """Return the next available draft version number."""

        versions: list[int] = []

        for path in self._draft_paths(linkedin_dir):
            match = DRAFT_FILENAME_PATTERN.fullmatch(path.name)

            if match is not None:
                versions.append(int(match.group("version")))

        return max(versions, default=0) + 1
