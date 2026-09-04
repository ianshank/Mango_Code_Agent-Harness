"""Typed wire models for the conversation history ``/api/orchestrate`` returns.

2026 standards audit, finding B3. ``TaskResponse.history`` was declared as
``list[dict[str, str]]``, which only describes the first two messages of any
run. The orchestrator appends the provider's assistant message verbatim
(``orchestrator/loop.py``), so a tool-using turn carries ``content: None`` and a
``tool_calls`` list; the dispatcher then appends ``{"role": "tool",
"tool_call_id": ..., "name": ..., "content": ...}`` for each call. Pydantic
rejected all three, the endpoint's blanket ``except`` turned the
``ValidationError`` into "Internal orchestration error", and every run that
used a tool -- which is every real run -- came back as HTTP 500 with the
verdict it had earned discarded.

These models mirror the OpenAI chat shape the orchestrator produces, one per
role, discriminated on ``role``. Two properties are load-bearing:

* **The wire shape of a string-only history is unchanged.** A message that was
  ``{"role": "user", "content": "..."}`` on the way in is exactly that on the
  way out: optional fields that were never set are omitted, not emitted as
  ``null``. A field the orchestrator *did* set to ``None`` (an assistant turn's
  ``content`` alongside ``tool_calls``, a ``tool_call_id`` for a call the
  provider sent without an ``id``) is kept, because that is the history.
* **Unknown keys pass through; unknown roles do not.** Providers decorate
  assistant messages with fields outside the four this module names
  (``refusal``, ``reasoning_content``, ...). Rejecting them would reintroduce
  this defect one provider at a time, so extras are allowed and serialised. A
  message whose ``role`` is not one of the four is malformed, and the endpoint
  reports it as an internal error rather than inventing a shape for it.

Redaction is unaffected: ``debug_dump.redact_history`` runs over the raw dicts
before validation and scrubs every string at every depth, including the
``arguments`` of a tool call and the ``content`` of a tool result.
"""

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    model_serializer,
)


class _WireModel(BaseModel):
    """Base for every model on the history wire.

    ``extra="allow"`` keeps provider-added keys; the serializer below drops
    only the optional fields *this module* declares when the input never set
    them, so a declared-but-unset ``name`` does not appear as ``"name": null``
    on a message that never had one.
    """

    model_config = ConfigDict(extra="allow")

    @model_serializer(mode="wrap")
    def _omit_unset_optionals(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        explicit = self.model_fields_set | set(self.model_extra or {})
        return {key: value for key, value in data.items() if value is not None or key in explicit}


class ToolCallFunction(_WireModel):
    """``tool_calls[n].function``. ``arguments`` is conventionally a JSON
    string but is model-generated; ``tool_dispatch._normalize_tool_arguments``
    degrades *every* other JSON shape (``null``, a list, a number, an object)
    to "no arguments" rather than failing, so the wire model accepts the same
    set. Rejecting a shape the dispatcher accepted would recreate the 500 this
    model exists to remove (Copilot review on PR #86)."""

    name: str
    arguments: Optional[Any] = None


class ToolCall(_WireModel):
    """One entry of an assistant message's ``tool_calls``."""

    id: Optional[str] = None
    type: Optional[str] = None
    function: ToolCallFunction


class SystemMessage(_WireModel):
    role: Literal["system"]
    content: str


class UserMessage(_WireModel):
    role: Literal["user"]
    content: str


class AssistantMessage(_WireModel):
    """``content`` is ``None`` on a turn that only requests tools; the loop
    rewrites the *final* assistant turn to a string in ``_finalize_response``
    but leaves every earlier one as the provider sent it."""

    role: Literal["assistant"]
    content: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None


class ToolMessage(_WireModel):
    """Appended by ``ToolDispatcher.dispatch`` for every requested call.
    ``tool_call_id`` is whatever the provider put in ``tool_calls[n].id``,
    which can be absent."""

    role: Literal["tool"]
    content: str
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


HistoryMessage = Annotated[
    Union[SystemMessage, UserMessage, AssistantMessage, ToolMessage],
    Field(discriminator="role"),
]

_HISTORY_ADAPTER: TypeAdapter[list[HistoryMessage]] = TypeAdapter(list[HistoryMessage])


def parse_history(raw: Sequence[Mapping[str, Any]]) -> list[HistoryMessage]:
    """Validate the orchestrator's raw history into wire models.

    Raises ``pydantic.ValidationError`` on a message the models do not
    describe; the endpoint maps that to the same opaque 500 as any other
    internal failure, so the error text (which names fields and echoes
    values) never reaches a client.
    """
    return _HISTORY_ADAPTER.validate_python(list(raw))
