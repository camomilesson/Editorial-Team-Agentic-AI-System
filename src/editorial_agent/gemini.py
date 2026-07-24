"""Gemini implementation of the model client boundary."""

from __future__ import annotations

import json
import os
from typing import Any

from google import genai

from editorial_agent.models import (
    ModelClientError,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResult,
)

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"


class GeminiModelClient:
    """Model client backed by the Gemini Interactions API."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_GEMINI_MODEL,
        api_key: str | None = None,
        sdk_client: Any | None = None,
    ) -> None:
        self.model = model

        if sdk_client is not None:
            self._client = sdk_client
            return

        if not api_key:
            raise ValueError("A Gemini API key is required")

        self._client = genai.Client(api_key=api_key)

    def respond(self, request: ModelRequest) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": self._convert_input(request.input),
        }

        if request.tools:
            kwargs["tools"] = list(request.tools)

        if request.continuation_token:
            kwargs["previous_interaction_id"] = request.continuation_token

        try:
            interaction = self._client.interactions.create(**kwargs)
        except Exception as exc:
            raise ModelClientError("Gemini model call failed") from exc

        tool_calls: list[ToolCall] = []

        for step in interaction.steps:
            if step.type != "function_call":
                continue

            tool_calls.append(
                ToolCall(
                    call_id=step.id,
                    name=step.name,
                    arguments=dict(step.arguments or {}),
                )
            )

        return ModelResponse(
            text=interaction.output_text or "",
            tool_calls=tuple(tool_calls),
            continuation_token=interaction.id,
        )

    @staticmethod
    def _convert_input(
        model_input: str | tuple[ToolResult, ...],
    ) -> str | list[dict[str, Any]]:
        if isinstance(model_input, str):
            return model_input

        return [
            {
                "type": "function_result",
                "name": result.name,
                "call_id": result.call_id,
                "result": [
                    {
                        "type": "text",
                        "text": json.dumps(result.result),
                    }
                ],
            }
            for result in model_input
        ]


def create_gemini_client_from_env() -> GeminiModelClient:
    """Create a Gemini client using project environment variables."""

    provider = os.getenv("MODEL_PROVIDER", "gemini").strip().lower()

    if provider != "gemini":
        raise ValueError(
            f"Unsupported MODEL_PROVIDER {provider!r}; expected 'gemini'"
        )

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured")

    model = os.getenv("AGENT_MODEL", "").strip() or DEFAULT_GEMINI_MODEL

    return GeminiModelClient(
        model=model,
        api_key=api_key,
    )
