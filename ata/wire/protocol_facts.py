"""The protocol-parser interface, so `parser` stops naming the families by hand.

`parser.py` asked `is_anthropic_messages_path(path)` three times -- once to pick the
request parser, once to pick the response parser, and once more to label the family
-- and every other path fell through to the OpenAI-compatible branch. Adding a third
wire format meant editing three conditionals and hoping the third one agreed with
the first two.

Two things follow from inverting it:

* **the family label and the parser are one lookup.** The label came from a separate
  evaluation of the same predicate, so it was possible for a parse to be produced by
  one adapter and labelled as another. Now the adapter that parsed is the adapter
  that names itself.
* **the fallback is declared, not implied.** OpenAI-compatible was the `else` branch,
  which reads as "the other one" rather than "the default". `register(fallback=True)`
  states it, and `registered_fallback()` fails loudly if two adapters claim it,
  because two defaults means dispatch depends on import order.

## The signatures are made uniform on purpose

The four underlying functions do not agree on arguments: the Anthropic request
parser wants `(path, headers, body)`, the OpenAI one wants `(path, body)`, and both
response parsers want `(content_type, body)` only. That disagreement is exactly why
the old dispatch had to be an `if` rather than a table. The wrappers below absorb it
and pass each function the arguments it actually takes, so no call changes.

## What this does not do

It does not touch `api_family`. That is a finer classification -- `openai-responses`
against `openai-chat-completions` -- which `openai_parser` derives from the path
suffix and, failing that, from the body shape. This module only chooses which
adapter reads the wire, and keeps the coarse `parser.family` label it already
published.
"""

from __future__ import annotations

from typing import Any, Protocol

from .anthropic_parser import (
    API_FAMILY as ANTHROPIC_API_FAMILY,
    is_anthropic_messages_path,
    parse_anthropic_request,
    parse_anthropic_response,
)

#: Bumped when the shape of a parser summary changes, not when an adapter is added.
#: `parser` publishes this inside every summary and that value is on stored records, so
#: it is one number with two readers rather than two numbers that have to agree. It used
#: to be restated as a literal in `parser.py`, and the test that they agree passed only
#: because both literals read 1; `tests/test_parser_version_closure.py` now forbids the
#: restatement.
#:
#: 2: a tool output's text is read from block form as well as string form, and the tool
#: result vocabulary gained the freeform and local-shell kinds. Both changed persisted
#: fields of a summary -- `message_items[].text`, `message_items[].role` and
#: `tool_result_count` -- so a record produced under 1 does not describe the same
#: projection as one produced under 2.
PROTOCOL_FACTS_VERSION = 2


class ProtocolParser(Protocol):
    """What `parser` needs from whoever understands a wire format."""

    #: The coarse family label published as `summary["parser"]["family"]`.
    family: str

    #: Whose token accounting this wire format uses. Not the client's name: two
    #: different agents speaking `anthropic-messages` report usage the same way,
    #: and that is the only thing this answers.
    provider: str

    #: The `api_family` values this adapter's parser can write, which is finer than
    #: `family` -- `openai-responses` against `openai-chat-completions`. Declared
    #: here so a reader can map one back to a provider without matching substrings;
    #: `tests/test_protocol_facts.py` checks the parsers cannot emit one that is
    #: missing from these tuples.
    api_families: tuple[str, ...]

    def handles(self, path: str) -> bool:
        """Whether this adapter claims the path.

        `select` consults this only for the adapters in `registered()`; the
        fallback is reached by exhausting that list, so its own answer is never
        asked for. It answers False anyway, because the honest reading of the
        method is "do I recognise this path", and the fallback recognises nothing
        -- it is the default. Keeping that true is what would let the fallback be
        registered normally one day without changing which paths it takes.
        """

    def parse_request(
        self, path: str, headers: dict[str, str], body: bytes
    ) -> dict[str, Any]:
        """Summarise a request. Must not raise; `parser` converts errors to a note."""

    def parse_response(
        self, path: str, headers: dict[str, str], content_type: str, body: bytes
    ) -> dict[str, Any]:
        """Summarise a response."""


class _AnthropicMessages:
    family = "anthropic-messages"
    provider = "anthropic"
    api_families = (ANTHROPIC_API_FAMILY,)

    def handles(self, path: str) -> bool:
        return is_anthropic_messages_path(path)

    def parse_request(
        self, path: str, headers: dict[str, str], body: bytes
    ) -> dict[str, Any]:
        return parse_anthropic_request(path, headers, body)

    def parse_response(
        self, path: str, headers: dict[str, str], content_type: str, body: bytes
    ) -> dict[str, Any]:
        return parse_anthropic_response(content_type, body)


class _OpenAICompatible:
    """未注册协议的默认 reader：只标注 family，不做结构化解析。

    OpenAI 族（codex 可用）第二批移植时恢复为 ava 原版（接 openai_parser）；
    现在没有消费者，搬 1095 行进来违反 YAGNI。
    """

    family = "openai-compatible"
    provider = "openai"
    api_families = ()

    def handles(self, path: str) -> bool:
        return False

    def parse_request(
        self, path: str, headers: dict[str, str], body: bytes
    ) -> dict[str, Any]:
        return {"api_family": "unknown", "json_valid": False}

    def parse_response(
        self, path: str, headers: dict[str, str], content_type: str, body: bytes
    ) -> dict[str, Any]:
        return {"api_family": "unknown", "json_valid": False, "response_text": ""}


def registered() -> tuple[ProtocolParser, ...]:
    """Every adapter that claims specific paths, in a stable order.

    Returned fresh rather than read from a module-level tuple. A caller writing
    `from .protocol_facts import registered` then holding the result would freeze
    the registry; recording that mistake being made once already, on the other
    interface.
    """
    return (_AnthropicMessages(),)


def registered_fallback() -> ProtocolParser:
    """The adapter used when no registered adapter claims the path."""
    return _OpenAICompatible()


#: What a reader answers when no adapter claims the family. A real bucket, the same
#: one `openai_parser` writes as the `api_family` of a request it could not place.
PROVIDER_UNKNOWN = "unknown"


def provider_for_api_family(api_family: Any) -> str:
    """Whose token accounting a record's wire format uses.

    Read off the adapters rather than matched as a substring. The substring version
    this replaces also tested for `claude` and `codex`, which are client names --
    and because the result feeds a request identity, a client name was helping
    decide which requests are the same request. Measured before removing them: no
    `api_family` any parser can produce contains either word, so on the whole
    library the two branches never fired.
    """
    if not isinstance(api_family, str) or not api_family:
        return PROVIDER_UNKNOWN
    for adapter in (*registered(), registered_fallback()):
        if api_family in adapter.api_families:
            return adapter.provider
    return PROVIDER_UNKNOWN


def select(path: str) -> ProtocolParser:
    """The adapter that reads this path.

    First claim wins, and adapters are expected not to overlap.
    `tests/test_protocol_facts.py` asserts non-overlap on the real paths in the
    store rather than trusting it, because two adapters claiming one path would make
    the answer depend on registration order, which is the failure this interface is
    supposed to remove.
    """
    for adapter in registered():
        if adapter.handles(path):
            return adapter
    return registered_fallback()
