from pathlib import Path

import pytest

from editorial_agent.storage import (
    DraftNotFoundError,
    InvalidDraftError,
    InvalidProjectIdError,
    InvalidVersionError,
    PressReleaseNotFoundError,
    ProjectStore,
)


def create_press_release(
    root: Path,
    project_id: str,
    content: str,
) -> Path:
    source_dir = root / project_id / "source"
    source_dir.mkdir(parents=True)

    path = source_dir / "press_release.md"
    path.write_text(content, encoding="utf-8")

    return path


@pytest.mark.parametrize(
    "project_id",
    [
        "demo",
        "project-001",
        "yandex_maps",
        "a1",
    ],
)
def test_valid_project_ids_are_accepted(
    tmp_path: Path,
    project_id: str,
) -> None:
    create_press_release(
        tmp_path,
        project_id,
        "A public press release.",
    )
    store = ProjectStore(tmp_path)

    assert (
        store.read_press_release(project_id)
        == "A public press release."
    )


@pytest.mark.parametrize(
    "project_id",
    [
        "",
        "../secret",
        "../../etc",
        "project/name",
        "/absolute/path",
        "Uppercase",
        "contains space",
    ],
)
def test_unsafe_project_ids_are_rejected(
    tmp_path: Path,
    project_id: str,
) -> None:
    store = ProjectStore(tmp_path)

    with pytest.raises(InvalidProjectIdError):
        store.read_press_release(project_id)


def test_reads_existing_press_release(tmp_path: Path) -> None:
    create_press_release(
        tmp_path,
        "demo",
        "Full press release text.\nSecond paragraph.",
    )
    store = ProjectStore(tmp_path)

    content = store.read_press_release("demo")

    assert content == "Full press release text.\nSecond paragraph."


def test_missing_press_release_raises_domain_error(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    with pytest.raises(
        PressReleaseNotFoundError,
        match="no stored press release",
    ):
        store.read_press_release("demo")


def test_empty_press_release_is_rejected(tmp_path: Path) -> None:
    create_press_release(
        tmp_path,
        "demo",
        "   \n",
    )
    store = ProjectStore(tmp_path)

    with pytest.raises(
        PressReleaseNotFoundError,
        match="empty press release",
    ):
        store.read_press_release("demo")


def test_first_saved_draft_gets_version_one(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    draft = store.save_linkedin_draft(
        project_id="demo",
        content="First LinkedIn post.",
        stage="first_draft",
    )

    assert draft.version == 1
    assert draft.stage == "first_draft"
    assert draft.path.name == "001-first_draft.md"
    assert draft.path.read_text(encoding="utf-8") == (
        "First LinkedIn post."
    )


def test_saving_twice_creates_two_versions(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    first = store.save_linkedin_draft(
        project_id="demo",
        content="First version.",
        stage="first_draft",
    )
    second = store.save_linkedin_draft(
        project_id="demo",
        content="Second version.",
        stage="revision",
    )

    assert first.version == 1
    assert second.version == 2
    assert first.path != second.path
    assert first.path.read_text(encoding="utf-8") == "First version."
    assert second.path.read_text(encoding="utf-8") == "Second version."


def test_versioning_continues_across_stages(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    first = store.save_linkedin_draft(
        project_id="demo",
        content="First.",
        stage="first_draft",
    )
    second = store.save_linkedin_draft(
        project_id="demo",
        content="Second.",
        stage="revision",
    )
    third = store.save_linkedin_draft(
        project_id="demo",
        content="Third.",
        stage="final",
    )

    assert first.path.name == "001-first_draft.md"
    assert second.path.name == "002-revision.md"
    assert third.path.name == "003-final.md"


def test_empty_draft_content_is_rejected(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    with pytest.raises(
        InvalidDraftError,
        match="must not be empty",
    ):
        store.save_linkedin_draft(
            project_id="demo",
            content="   ",
            stage="first_draft",
        )


def test_unsupported_stage_is_rejected(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    with pytest.raises(
        InvalidDraftError,
        match="Unsupported draft stage",
    ):
        store.save_linkedin_draft(
            project_id="demo",
            content="Draft.",
            stage="almost_final",
        )


def test_reads_requested_draft_version(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    store.save_linkedin_draft(
        project_id="demo",
        content="First.",
        stage="first_draft",
    )
    store.save_linkedin_draft(
        project_id="demo",
        content="Second.",
        stage="revision",
    )

    draft = store.read_linkedin_draft(
        project_id="demo",
        version=2,
    )

    assert draft.project_id == "demo"
    assert draft.version == 2
    assert draft.stage == "revision"
    assert draft.content == "Second."


def test_missing_draft_version_raises_domain_error(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    with pytest.raises(
        DraftNotFoundError,
        match="version 12",
    ):
        store.read_linkedin_draft(
            project_id="demo",
            version=12,
        )


@pytest.mark.parametrize(
    "version",
    [
        0,
        -1,
        -50,
    ],
)
def test_non_positive_versions_are_rejected(
    tmp_path: Path,
    version: int,
) -> None:
    store = ProjectStore(tmp_path)

    with pytest.raises(InvalidVersionError):
        store.read_linkedin_draft(
            project_id="demo",
            version=version,
        )


def test_boolean_version_is_rejected(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)

    with pytest.raises(InvalidVersionError):
        store.read_linkedin_draft(
            project_id="demo",
            version=True,
        )

