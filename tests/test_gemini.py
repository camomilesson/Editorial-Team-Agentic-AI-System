from types import SimpleNamespace

import pytest

from editorial_agent.gemini import GeminiModelClient
from editorial_agent.models import (
    ModelClientError,
    ModelRequest,
    ToolCall,
    ToolResult,
)


class FakeInteractions:
    def __init__(self, interaction) -> None:
        self.interaction = interaction
        self.last_kwargs = None
        self.error = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs

        if self.error is not None:
            raise self.error

        return self.interaction


class FakeGeminiSDK:
    def __init__(self, interaction) -> None:
        self.interactions = FakeInteractions(interaction)


def test_gemini_normalizes_text_response() -> None:
    raw_interaction = SimpleNamespace(
        id="interaction-1",
        output_text="Done.",
        steps=[],
    )
    sdk = FakeGeminiSDK(raw_interaction)
    client = GeminiModelClient(sdk_client=sdk)

    response = client.respond(ModelRequest(input="Hello"))

    assert response.text == "Done."
    assert response.tool_calls == ()
    assert response.continuation_token == "interaction-1"


def test_gemini_normalizes_function_call() -> None:
    function_call = SimpleNamespace(
        type="function_call",
        id="call-1",
        name="read_press_release",
        arguments={"project_id": "demo"},
    )
    raw_interaction = SimpleNamespace(
        id="interaction-1",
        output_text="",
        steps=[function_call],
    )
    sdk = FakeGeminiSDK(raw_interaction)
    client = GeminiModelClient(sdk_client=sdk)

    response = client.respond(ModelRequest(input="Read the release"))

    assert response.tool_calls == (
        ToolCall(
            call_id="call-1",
            name="read_press_release",
            arguments={"project_id": "demo"},
        ),
    )


def test_gemini_sends_tool_result_with_continuation() -> None:
    raw_interaction = SimpleNamespace(
        id="interaction-2",
        output_text="The release was read.",
        steps=[],
    )
    sdk = FakeGeminiSDK(raw_interaction)
    client = GeminiModelClient(sdk_client=sdk)

    client.respond(
        ModelRequest(
            input=(
                ToolResult(
                    call_id="call-1",
                    name="read_press_release",
                    result={"ok": True, "content": "Press release"},
                ),
            ),
            continuation_token="interaction-1",
        )
    )

    assert (
        sdk.interactions.last_kwargs["previous_interaction_id"]
        == "interaction-1"
    )

    tool_result = sdk.interactions.last_kwargs["input"][0]

    assert tool_result["type"] == "function_result"
    assert tool_result["call_id"] == "call-1"
    assert tool_result["name"] == "read_press_release"
    assert tool_result["result"] == [
        {
            "type": "text",
            "text": '{"ok": true, "content": "Press release"}',
        }
    ]


def test_gemini_wraps_provider_error() -> None:
    raw_interaction = SimpleNamespace(
        id="unused",
        output_text="",
        steps=[],
    )
    sdk = FakeGeminiSDK(raw_interaction)
    provider_error = ConnectionError("network unavailable")
    sdk.interactions.error = provider_error

    client = GeminiModelClient(sdk_client=sdk)

    with pytest.raises(
        ModelClientError,
        match="Gemini model call failed",
    ) as exc_info:
        client.respond(ModelRequest(input="Hello"))

    assert exc_info.value.__cause__ is provider_error
