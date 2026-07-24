from pathlib import Path

from editorial_agent.storage import ProjectStore
from editorial_agent.tools import (
    READ_LINKEDIN_DRAFT_SCHEMA,
    READ_PRESS_RELEASE_SCHEMA,
    SAVE_LINKEDIN_DRAFT_SCHEMA,
    read_linkedin_draft,
    read_press_release,
    save_linkedin_draft,
)


def create_press_release(
    root: Path,
    project_id: str,
    content: str,
) -> None:
    source_dir = root / project_id / "source"
    source_dir.mkdir(parents=True)

    (source_dir / "press_release.md").write_text(
        content,
        encoding="utf-8",
    )


def test_read_press_release_returns_success(
    tmp_path: Path,
) -> None:
    create_press_release(
        tmp_path,
        "demo",
        "Public press release.",
    )
    store = ProjectStore(tmp_path)

    result = read_press_release(
        store,
        project_id="demo",
    )

    assert result == {
        "ok": True,
        "data": {
            "project_id": "demo",
            "content": "Public press release.",
        },
    }


def test_missing_press_release_returns_error(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    result = read_press_release(
        store,
        project_id="demo",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "press_release_not_found"


def test_unsafe_project_id_returns_error(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    result = read_press_release(
        store,
        project_id="../secret",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_project_id"


def test_save_linkedin_draft_writes_real_file(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    result = save_linkedin_draft(
        store,
        project_id="demo",
        content="LinkedIn post.",
        stage="first_draft",
    )

    assert result == {
        "ok": True,
        "data": {
            "project_id": "demo",
            "version": 1,
            "stage": "first_draft",
            "content": "LinkedIn post.",
        },
    }

    saved_path = (
        tmp_path
        / "demo"
        / "linkedin"
        / "001-first_draft.md"
    )

    assert saved_path.read_text(encoding="utf-8") == "LinkedIn post."


def test_two_tool_saves_create_two_versions(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    first = save_linkedin_draft(
        store,
        project_id="demo",
        content="First.",
        stage="first_draft",
    )
    second = save_linkedin_draft(
        store,
        project_id="demo",
        content="Second.",
        stage="revision",
    )

    assert first["data"]["version"] == 1
    assert second["data"]["version"] == 2


def test_invalid_stage_returns_explicit_error(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    result = save_linkedin_draft(
        store,
        project_id="demo",
        content="Draft.",
        stage="almost_final",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_draft"


def test_empty_draft_returns_explicit_error(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    result = save_linkedin_draft(
        store,
        project_id="demo",
        content="   ",
        stage="first_draft",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_draft"


def test_read_linkedin_draft_returns_requested_version(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    save_linkedin_draft(
        store,
        project_id="demo",
        content="First.",
        stage="first_draft",
    )
    save_linkedin_draft(
        store,
        project_id="demo",
        content="Second.",
        stage="revision",
    )

    result = read_linkedin_draft(
        store,
        project_id="demo",
        version=2,
    )

    assert result == {
        "ok": True,
        "data": {
            "project_id": "demo",
            "version": 2,
            "stage": "revision",
            "content": "Second.",
        },
    }


def test_missing_draft_returns_explicit_error(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    result = read_linkedin_draft(
        store,
        project_id="demo",
        version=99,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "draft_not_found"


def test_invalid_version_returns_explicit_error(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)

    result = read_linkedin_draft(
        store,
        project_id="demo",
        version=0,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "invalid_version"


def test_read_press_release_schema_is_constrained() -> None:
    parameters = READ_PRESS_RELEASE_SCHEMA["parameters"]

    assert READ_PRESS_RELEASE_SCHEMA["name"] == "read_press_release"
    assert parameters["required"] == ["project_id"]
    assert parameters["additionalProperties"] is False
    assert "Use when" in READ_PRESS_RELEASE_SCHEMA["description"]
    assert "Do not use" in READ_PRESS_RELEASE_SCHEMA["description"]


def test_save_linkedin_draft_schema_is_constrained() -> None:
    parameters = SAVE_LINKEDIN_DRAFT_SCHEMA["parameters"]
    stage = parameters["properties"]["stage"]

    assert SAVE_LINKEDIN_DRAFT_SCHEMA["name"] == (
        "save_linkedin_draft"
    )
    assert set(parameters["required"]) == {
        "project_id",
        "content",
        "stage",
    }
    assert stage["enum"] == [
        "first_draft",
        "revision",
        "final",
    ]
    assert parameters["properties"]["content"]["minLength"] == 1
    assert parameters["additionalProperties"] is False
    assert "Use after" in SAVE_LINKEDIN_DRAFT_SCHEMA["description"]
    assert "Do not use" in SAVE_LINKEDIN_DRAFT_SCHEMA["description"]


def test_read_linkedin_draft_schema_is_constrained() -> None:
    parameters = READ_LINKEDIN_DRAFT_SCHEMA["parameters"]
    version = parameters["properties"]["version"]

    assert READ_LINKEDIN_DRAFT_SCHEMA["name"] == (
        "read_linkedin_draft"
    )
    assert set(parameters["required"]) == {
        "project_id",
        "version",
    }
    assert version["type"] == "integer"
    assert version["minimum"] == 1
    assert parameters["additionalProperties"] is False
    assert "Use when" in READ_LINKEDIN_DRAFT_SCHEMA["description"]
    assert "Do not use" in READ_LINKEDIN_DRAFT_SCHEMA["description"]
