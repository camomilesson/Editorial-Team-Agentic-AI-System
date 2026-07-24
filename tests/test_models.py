import pytest

from editorial_agent.models import (
    FakeModelClient,
    ModelClientError,
    ModelRequest,
    ModelResponse,
    ToolCall,
)


def test_fake_model_returns_scripted_response() -> None:
    expected = ModelResponse(
        text="Done.",
        tool_calls=(),
        continuation_token="interaction-1",
    )
    client = FakeModelClient([expected])

    request = ModelRequest(input="Hello")
    actual = client.respond(request)

    assert actual == expected
    assert client.requests == [request]


def test_fake_model_can_return_tool_call() -> None:
    expected = ModelResponse(
        text="",
        tool_calls=(
            ToolCall(
                call_id="call-1",
                name="read_press_release",
                arguments={"project_id": "demo"},
            ),
        ),
        continuation_token="interaction-1",
    )
    client = FakeModelClient([expected])

    actual = client.respond(ModelRequest(input="Read the release"))

    assert actual.tool_calls[0].name == "read_press_release"
    assert actual.tool_calls[0].arguments == {"project_id": "demo"}


def test_fake_model_fails_when_exhausted() -> None:
    client = FakeModelClient([])

    with pytest.raises(
        ModelClientError,
        match="no scripted responses",
    ):
        client.respond(ModelRequest(input="Hello"))