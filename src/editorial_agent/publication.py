"""Append-only local publication outbox."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from editorial_agent.storage import DraftVersion, ProjectStore

ALLOWED_VISIBILITIES = (
    "public",
    "connections",
)


class PublicationError(Exception):
    """Base exception for publication failures."""


class InvalidVisibilityError(PublicationError):
    """Raised when an unsupported visibility is requested."""


class DraftNotFinalError(PublicationError):
    """Raised when publication is attempted with a non-final draft."""


class AlreadyPublishedError(PublicationError):
    """Raised when a draft version has already been published."""


@dataclass(frozen=True)
class PublishedPost:
    """One post placed into the publication outbox."""

    project_id: str
    version: int
    visibility: str
    path: Path
    content: str


class PublicationOutbox:
    """Publish final LinkedIn drafts into an append-only directory."""

    def __init__(
        self,
        *,
        root: Path,
        store: ProjectStore,
    ) -> None:
        self.root = root.resolve(strict=False)
        self.store = store

    def publish(
        self,
        *,
        project_id: str,
        version: int,
        visibility: str,
    ) -> PublishedPost:
        """Publish one final saved draft without allowing overwrite."""

        if visibility not in ALLOWED_VISIBILITIES:
            allowed = ", ".join(ALLOWED_VISIBILITIES)
            raise InvalidVisibilityError(
                f"Unsupported visibility {visibility!r}. "
                f"Expected one of: {allowed}."
            )

        draft = self.store.read_linkedin_draft(
            project_id=project_id,
            version=version,
        )

        self._require_final(draft)

        project_outbox = (
            self.root / project_id
        ).resolve(strict=False)

        if not project_outbox.is_relative_to(self.root):
            raise PublicationError(
                "Publication path must remain inside the outbox."
            )

        project_outbox.mkdir(
            parents=True,
            exist_ok=True,
        )

        existing_versions = tuple(
            project_outbox.glob(f"{version:03d}-*.md")
        )

        if existing_versions:
            raise AlreadyPublishedError(
                f"Project {project_id} version {version} "
                "has already been published."
            )

        path = project_outbox / (
            f"{version:03d}-{visibility}.md"
        )

        try:
            with path.open(
                mode="x",
                encoding="utf-8",
            ) as file:
                file.write(draft.content)
        except FileExistsError as exc:
            raise AlreadyPublishedError(
                f"Project {project_id} version {version} "
                "has already been published."
            ) from exc

        return PublishedPost(
            project_id=project_id,
            version=version,
            visibility=visibility,
            path=path,
            content=draft.content,
        )

    @staticmethod
    def _require_final(
        draft: DraftVersion,
    ) -> None:
        if draft.stage != "final":
            raise DraftNotFinalError(
                f"Draft version {draft.version} has stage "
                f"{draft.stage!r}; only final drafts can be published."
            )