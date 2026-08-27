"""OpenAI Chat Completions + Responses API 解析内核（移植自 ava）。

源: agent_visualization_analysis/agent_visualization_analysis/openai_parser.py
移植日期: 2026-08-27
差异: 1:1 移植,行数 ~1095;未来 ava 上游改动需手动同步。
公开函数: parse_openai_request(path, body) -> dict
         parse_openai_response(content_type, body) -> dict
两者**不**吃 headers——ata seam 多给的 headers 在 protocol_facts._OpenAI wrapper 吞掉,
ava 的 metadata 提取走 payload["metadata"],不读 request header。
"""

import json
from typing import Any, Iterable, Optional


METADATA_ID_KEYS = {
    "session_id",
    "thread_id",
    "conversation_id",
    "correlation_id",
    "trace_id",
    "run_id",
    "request_id",
    "parent_id",
}


def parse_openai_request(path: str, body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return {"api_family": "unknown", "api_family_source": "none", "json_valid": False}

    if not isinstance(payload, dict):
        payload = {}

    messages = payload.get("messages")
    if not isinstance(messages, list):
        messages = []

    tools = payload.get("tools")
    if not isinstance(tools, list):
        tools = []
    declared_tools = _declared_tools(payload)

    api_family = _request_api_family(path)
    api_family_source = "path" if api_family != "unknown" else "none"
    if api_family == "unknown":
        inferred = _body_api_family(payload)
        if inferred != "unknown":
            api_family = inferred
            api_family_source = "body"
    responses_input = (
        _summarize_responses_input(payload.get("input"))
        if api_family == "openai-responses"
        else {
            "system_prompts": [],
            "system_prompt_items": [],
            "message_count": 0,
            "message_items": [],
            "request_tool_call_names": [],
            "request_tool_call_ids": [],
            "request_item_ids": [],
            "tool_result_count": 0,
        }
    )

    system_prompts = _content_to_texts(payload.get("instructions"))
    system_prompt_items = [
        _system_prompt_item("instructions", "system", None, text)
        for text in system_prompts
    ]
    message_items = [_message_item("messages", index, message) for index, message in enumerate(messages)]

    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        if message.get("role") in {"system", "developer"}:
            texts = _content_to_texts(message.get("content"))
            system_prompts.extend(texts)
            system_prompt_items.extend(
                _system_prompt_item("messages", message.get("role"), index, text)
                for text in texts
            )
    system_prompts.extend(responses_input["system_prompts"])
    system_prompt_items.extend(responses_input["system_prompt_items"])
    message_items.extend(responses_input["message_items"])

    return {
        "api_family": api_family,
        "api_family_source": api_family_source,
        "json_valid": True,
        "model": payload.get("model"),
        "stream": bool(payload.get("stream", False)),
        "system_prompts": system_prompts,
        "system_prompt_items": system_prompt_items,
        "message_count": len(messages) + responses_input["message_count"],
        "messages": messages,
        "message_items": message_items,
        "tools": tools,
        "tool_items": _tool_items(declared_tools),
        "tool_names": _tool_names(declared_tools),
        "tool_choice": payload.get("tool_choice"),
        "response_format": payload.get("response_format"),
        "request_previous_response_id": _string_value(payload.get("previous_response_id")),
        "request_metadata_ids": _metadata_ids(payload.get("metadata")),
        "request_tool_call_names": _message_tool_call_names(messages)
        + responses_input["request_tool_call_names"],
        "request_tool_call_ids": _unique_strings(
            _message_tool_call_ids(messages)
            + responses_input["request_tool_call_ids"]
        ),
        "request_item_ids": _unique_strings(
            _message_item_ids(messages)
            + responses_input["request_item_ids"]
        ),
        "tool_result_count": sum(
            1
            for message in messages
            if isinstance(message, dict) and message.get("role") == "tool"
        )
        + responses_input["tool_result_count"],
    }


def parse_openai_response(content_type: str, body: bytes) -> dict[str, Any]:
    if "text/event-stream" in content_type.lower():
        return _parse_sse_response(body)

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return {
            "json_valid": False,
            "response_text": "",
            "assistant_text": "",
            "response_tool_call_names": [],
        }

    if not isinstance(payload, dict):
        payload = {}

    assistant_text_parts: list[str] = []
    response_tool_call_names: list[str] = []
    response_tool_call_ids: list[str] = []
    response_tool_calls: list[dict[str, Any]] = []
    finish_reasons: list[Any] = []

    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict):
                assistant_text_parts.extend(_content_to_texts(message.get("content")))
                response_tool_call_names.extend(
                    _tool_names(message.get("tool_calls", []))
                )
                response_tool_call_ids.extend(
                    _tool_call_ids(message.get("tool_calls", []))
                )
                response_tool_calls.extend(
                    _structured_tool_calls(message.get("tool_calls", []))
                )
            if choice.get("finish_reason") is not None:
                finish_reasons.append(choice.get("finish_reason"))

    if not finish_reasons:
        finish_reasons.extend(_responses_finish_reasons(payload))

    _append_responses_output(payload, assistant_text_parts, response_tool_call_names)
    response_tool_call_ids.extend(_response_output_tool_call_ids(payload.get("output")))
    response_tool_calls.extend(_structured_tool_calls(payload.get("output")))

    assistant_text = "".join(assistant_text_parts)
    return {
        "json_valid": True,
        "response_id": _string_value(payload.get("id")),
        "response_previous_response_id": _string_value(payload.get("previous_response_id")),
        "response_metadata_ids": _metadata_ids(payload.get("metadata")),
        "response_conversation_id": _conversation_id(payload.get("conversation")),
        "response_item_ids": _response_output_item_ids(payload.get("output")),
        "response_text": assistant_text,
        "assistant_text": assistant_text,
        "response_tool_call_names": response_tool_call_names,
        "response_tool_call_ids": _unique_strings(response_tool_call_ids),
        "response_tool_calls": response_tool_calls,
        "finish_reasons": finish_reasons,
        "usage": payload.get("usage"),
    }


def _parse_sse_response(body: bytes) -> dict[str, Any]:
    assistant_text_parts: list[str] = []
    response_tool_call_names: list[str] = []
    response_tool_call_ids: list[str] = []
    response_item_ids: list[str] = []
    response_id: Optional[str] = None
    response_previous_response_id: Optional[str] = None
    response_metadata_ids: dict[str, str] = {}
    response_conversation_id: Optional[str] = None
    finish_reasons: list[Any] = []
    responses_finish_reasons: list[str] = []
    usage: Any = None
    event_count = 0
    # Chat Completions streams tool_calls as partial deltas keyed by index.
    chat_tool_acc: dict[int, dict[str, Any]] = {}
    responses_tool_acc: dict[str, dict[str, Any]] = {}

    for line in body.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue

        data = line.removeprefix("data:").strip()
        if data == "[DONE]":
            continue

        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue

        if not isinstance(event, dict):
            continue

        event_count += 1

        # Chat Completions stream chunks expose completion id at the event top level.
        # Responses API stream events may also set top-level ids; prefer the first seen.
        response_id = response_id or _string_value(event.get("id"))

        choices = event.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    assistant_text_parts.extend(_content_to_texts(delta.get("content")))
                    response_tool_call_names.extend(
                        _tool_names(delta.get("tool_calls", []))
                    )
                    response_tool_call_ids.extend(
                        _tool_call_ids(delta.get("tool_calls", []))
                    )
                    _accumulate_chat_tool_call_deltas(
                        chat_tool_acc, delta.get("tool_calls")
                    )
                if choice.get("finish_reason") is not None:
                    finish_reasons.append(choice.get("finish_reason"))

        response = event.get("response")
        if isinstance(response, dict):
            response_id = response_id or _string_value(response.get("id"))
            response_previous_response_id = response_previous_response_id or _string_value(
                response.get("previous_response_id")
            )
            response_metadata_ids.update(_metadata_ids(response.get("metadata")))
            response_conversation_id = response_conversation_id or _conversation_id(
                response.get("conversation")
            )
            # Only the terminal event carries a terminal status; in_progress is skipped.
            terminal = _responses_finish_reasons(response)
            if terminal:
                responses_finish_reasons = terminal

        for candidate in (event.get("item"), event.get("output_item")):
            if isinstance(candidate, dict):
                item_id = _string_value(candidate.get("id"))
                if item_id is not None:
                    response_item_ids.append(item_id)
                response_tool_call_ids.extend(_tool_call_ids(candidate))

        if event.get("usage") is not None:
            usage = event.get("usage")
        elif isinstance(event.get("response"), dict) and event["response"].get("usage") is not None:
            usage = event["response"].get("usage")

        _append_responses_stream_event(event, assistant_text_parts, response_tool_call_names)
        _append_responses_tool_call_stream(event, responses_tool_acc)

    if not finish_reasons:
        finish_reasons.extend(responses_finish_reasons)

    response_tool_calls = _finalize_chat_tool_call_acc(chat_tool_acc)
    response_tool_calls.extend(_finalize_responses_tool_call_acc(responses_tool_acc))
    assistant_text = "".join(assistant_text_parts)
    return {
        "json_valid": True,
        "response_id": response_id,
        "response_previous_response_id": response_previous_response_id,
        "response_metadata_ids": response_metadata_ids,
        "response_conversation_id": response_conversation_id,
        "response_item_ids": _unique_strings(response_item_ids),
        "response_text": assistant_text,
        "assistant_text": assistant_text,
        "response_tool_call_names": response_tool_call_names,
        "response_tool_call_ids": _unique_strings(response_tool_call_ids),
        "response_tool_calls": response_tool_calls,
        "finish_reasons": finish_reasons,
        "usage": usage,
        "sse_event_count": event_count,
    }


_RESPONSES_TERMINAL_STATUSES = frozenset({"completed", "incomplete", "failed", "cancelled"})


def _responses_finish_reasons(response: Any) -> list[str]:
    """Termination tokens the Responses API itself reports, verbatim.

    Responses has no ``finish_reason``. It reports a lifecycle ``status`` and, when a
    run stopped early, ``incomplete_details.reason``. Both are emitted as-is, the same
    way the anthropic parser emits ``stop_reason``: translating ``completed`` into the
    chat-completions word ``stop`` would report a value the provider never sent, and
    would erase the distinction between a finished run and a truncated one.
    """
    if not isinstance(response, dict):
        return []
    status = _string_value(response.get("status"))
    if status is None or status not in _RESPONSES_TERMINAL_STATUSES:
        return []
    reasons = [status]
    details = response.get("incomplete_details")
    if isinstance(details, dict):
        reason = _string_value(details.get("reason"))
        if reason is not None:
            reasons.append(reason)
    return reasons


#: Codex reaches the Responses API under more than one prefix: `/v1/responses`
#: with API-key auth and `/backend-api/codex/responses` with ChatGPT auth. An
#: exact-equality test on the first form routes the second to `unknown`, and
#: `unknown` skips the entire `input[]` parse without raising, so the request
#: lands with `message_count: 0` and no error. Match on the endpoint segment
#: instead of the full path so a new prefix cannot silently zero a parse.
#: The remote-compaction endpoint `<prefix>/responses/compact` does not match
#: here, since the suffix test is anchored at the end of the path. It may still
#: be classified by body shape, which is left as-is: that endpoint has no
#: samples yet, and guessing at a distinct family for it would be speculation.
_API_FAMILY_PATH_SUFFIXES = (
    ("/chat/completions", "openai-chat-completions"),
    ("/responses", "openai-responses"),
)

#: Every `api_family` this parser can write, apart from `unknown`, which means it
#: placed nothing and belongs to no provider. Derived from the suffix table above so
#: the two cannot drift; `protocol_facts` republishes it as the adapter's claim.
API_FAMILIES = tuple(family for _suffix, family in _API_FAMILY_PATH_SUFFIXES)


def _request_api_family(path: str) -> str:
    normalized = path.split("?", 1)[0].rstrip("/")
    for suffix, family in _API_FAMILY_PATH_SUFFIXES:
        if normalized.endswith(suffix):
            return family
    return "unknown"


def _body_api_family(payload: Any) -> str:
    """Recognise a Responses request from its body when the path is unfamiliar.

    Only the Responses direction is inferred. Chat Completions is not, because
    `messages` is not distinctive enough to separate it from other providers
    that this parser may be handed. A bare list of strings under `input` is an
    embeddings request, so at least one item must be a Responses-shaped object.
    """
    if not isinstance(payload, dict):
        return "unknown"
    if isinstance(payload.get("messages"), list):
        return "unknown"
    items = payload.get("input")
    if not isinstance(items, list):
        return "unknown"
    for item in items:
        if isinstance(item, dict) and ("type" in item or "role" in item):
            return "openai-responses"
    return "unknown"


def _string_value(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _string_values(values: Iterable[Any]) -> list[str]:
    return [value for value in (_string_value(value) for value in values) if value is not None]


def _unique_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _string_value(value)
        if text is None or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _metadata_ids(metadata: Any) -> dict[str, str]:
    if not isinstance(metadata, dict):
        return {}

    ids: dict[str, str] = {}
    for key in METADATA_ID_KEYS:
        value = _string_value(metadata.get(key))
        if value is not None:
            ids[key] = value
    return ids


def _conversation_id(conversation: Any) -> Optional[str]:
    if isinstance(conversation, str):
        return conversation or None
    if isinstance(conversation, dict):
        return _string_value(conversation.get("id"))
    return None


def _tool_call_ids(value: Any) -> list[str]:
    if isinstance(value, list):
        ids: list[str] = []
        for item in value:
            ids.extend(_tool_call_ids(item))
        return ids
    if not isinstance(value, dict):
        return []

    ids = _string_values([value.get("call_id"), value.get("tool_call_id")])
    if isinstance(value.get("tool_calls"), list):
        ids.extend(_tool_call_ids(value.get("tool_calls")))
    # Chat Completions tool calls use `id`; Responses items often use `call_id`.
    if isinstance(value.get("function"), dict):
        ids.extend(_string_values([value.get("id")]))
    elif _is_responses_tool_call_item(value) and not ids:
        ids.extend(_string_values([value.get("id")]))
    return _unique_strings(ids)


def _response_output_item_ids(output: Any) -> list[str]:
    if not isinstance(output, list):
        return []

    ids: list[str] = []
    for item in output:
        if isinstance(item, dict):
            ids.extend(_string_values([item.get("id")]))
    return _unique_strings(ids)


def _response_output_tool_call_ids(output: Any) -> list[str]:
    if not isinstance(output, list):
        return []

    ids: list[str] = []
    for item in output:
        ids.extend(_tool_call_ids(item))
    return _unique_strings(ids)


def _content_to_texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            texts.extend(_content_to_texts(block))
        return texts
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return [text]
    return []


def _structured_tool_calls(value: Any) -> list[dict[str, Any]]:
    """Best-effort structured tool call list for Viewer Response Summary.

    Accepts Chat Completions `tool_calls[]`, Responses `output[]` items, or nested
    containers. Unknown shapes are skipped rather than forcing a source-specific schema.
    """
    if not isinstance(value, list):
        return []

    calls: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").lower()
        function = item.get("function") if isinstance(item.get("function"), dict) else {}

        name = _string_value(item.get("name")) or _string_value(function.get("name"))
        call_id = _string_value(
            item.get("call_id")
            or item.get("tool_call_id")
            or item.get("id")
            or function.get("id")
        )

        raw_input: Any = None
        if isinstance(item.get("input"), (dict, list, str)):
            raw_input = item.get("input")
        elif isinstance(item.get("arguments"), (dict, list, str)):
            raw_input = item.get("arguments")
        elif isinstance(function.get("arguments"), (dict, list, str)):
            raw_input = function.get("arguments")

        parsed_input: Any = raw_input
        if isinstance(raw_input, str):
            text = raw_input.strip()
            if text:
                try:
                    parsed_input = json.loads(text)
                except (json.JSONDecodeError, TypeError, ValueError):
                    parsed_input = raw_input

        looks_like_tool = bool(name) or item_type in {
            "function",
            "function_call",
            "custom_tool_call",
            "tool_use",
            "tool_call",
        }
        if not looks_like_tool:
            # Nested content arrays (rare) — recurse lightly.
            for nested_key in ("content", "tool_calls", "output"):
                nested = item.get(nested_key)
                if isinstance(nested, list):
                    calls.extend(_structured_tool_calls(nested))
            continue

        entry: dict[str, Any] = {}
        if name:
            entry["name"] = name
        if call_id:
            entry["id"] = call_id
        if parsed_input is not None and parsed_input != "":
            entry["input"] = parsed_input
        if entry:
            calls.append(entry)
    return calls


def _accumulate_chat_tool_call_deltas(
    acc: dict[int, dict[str, Any]], tool_calls: Any
) -> None:
    if not isinstance(tool_calls, list):
        return
    for item in tool_calls:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int):
            index = len(acc)
        slot = acc.setdefault(index, {"id": "", "name": "", "arguments": ""})
        call_id = _string_value(item.get("id"))
        if call_id:
            slot["id"] = call_id
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = _string_value(function.get("name")) or _string_value(item.get("name"))
        if name:
            slot["name"] = name
        arguments = function.get("arguments")
        if isinstance(arguments, str) and arguments:
            slot["arguments"] = str(slot.get("arguments") or "") + arguments


def _finalize_chat_tool_call_acc(acc: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for index in sorted(acc):
        slot = acc[index]
        entry: dict[str, Any] = {}
        name = _string_value(slot.get("name"))
        call_id = _string_value(slot.get("id"))
        if name:
            entry["name"] = name
        if call_id:
            entry["id"] = call_id
        arguments = slot.get("arguments")
        if isinstance(arguments, str) and arguments.strip():
            try:
                entry["input"] = json.loads(arguments)
            except (json.JSONDecodeError, TypeError, ValueError):
                entry["input"] = arguments
        if entry:
            calls.append(entry)
    return calls


def _tool_names(tools: Any) -> list[str]:
    if not isinstance(tools, list):
        return []

    names: list[str] = []
    for entry in tools:
        tool = entry.get("tool") if isinstance(entry, dict) and "tool" in entry else entry
        name = _tool_call_name(tool)
        if name is not None:
            names.append(name)
    return names


#: A declared tool, plus where it was found. Codex sends no top-level `tools`
#: on most requests: the declarations arrive as an `additional_tools` item
#: inside `input[]`, and the collaboration tools sit inside a `namespace`
#: wrapper whose members carry the real names. Reading only the top-level field
#: reports "no tools available" for those requests, which is 183 of the 193
#: Codex request bodies in the capture library.
#: Group names are not identifying: the same six collaboration members have been
#: observed under `collaboration`, `agents` and `mcp__fastctx`. Match members.
_MAX_TOOL_GROUP_DEPTH = 4


def _collect_declared_tools(
    tools: Any, source: str, group: Optional[str], out: list[dict[str, Any]], depth: int
) -> None:
    if not isinstance(tools, list) or depth > _MAX_TOOL_GROUP_DEPTH:
        return
    for tool in tools:
        if isinstance(tool, dict) and tool.get("type") == "namespace":
            name = tool.get("name")
            _collect_declared_tools(
                tool.get("tools"),
                source,
                name if isinstance(name, str) else group,
                out,
                depth + 1,
            )
            continue
        out.append({"tool": tool, "source": source, "group": group})


def _declared_tools(payload: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return entries
    _collect_declared_tools(payload.get("tools"), "tools", None, entries, 0)
    items = payload.get("input")
    if isinstance(items, list):
        for index, item in enumerate(items):
            if isinstance(item, dict) and item.get("type") == "additional_tools":
                _collect_declared_tools(
                    item.get("tools"), f"input[{index}].additional_tools", None, entries, 0
                )
    return entries


def _tool_items(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        return []

    items: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        tool = entry.get("tool") if isinstance(entry, dict) else None
        source = entry.get("source") if isinstance(entry, dict) else "tools"
        group = entry.get("group") if isinstance(entry, dict) else None
        if not isinstance(tool, dict):
            items.append(
                {
                    "source": source,
                    "group": group,
                    "index": index,
                    "name": "unknown_tool",
                    "type": "unknown",
                    "description": "",
                    "parameters": tool,
                }
            )
            continue

        function = tool.get("function")
        if isinstance(function, dict):
            name = function.get("name") or tool.get("name") or tool.get("type")
            description = function.get("description") or tool.get("description") or ""
            parameters = function.get("parameters") or tool.get("parameters")
            tool_type = tool.get("type") or "function"
        else:
            name = tool.get("name") or tool.get("type") or "unknown_tool"
            description = tool.get("description") or ""
            parameters = tool.get("parameters") or tool.get("input_schema")
            tool_type = tool.get("type") or "unknown"

        items.append(
            {
                "source": source,
                "group": group,
                "index": index,
                "name": name,
                "type": tool_type,
                "description": description,
                "parameters": parameters,
            }
        )
    return items


def _tool_call_name(tool_call: Any) -> Optional[str]:
    if not isinstance(tool_call, dict):
        return None

    function = tool_call.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]

    name = tool_call.get("name")
    if isinstance(name, str):
        return name
    return None


def _message_tool_call_names(messages: list[Any]) -> list[str]:
    names: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        names.extend(_tool_names(message.get("tool_calls", [])))
    return names


def _message_tool_call_ids(messages: list[Any]) -> list[str]:
    ids: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        ids.extend(_tool_call_ids(message.get("tool_calls", [])))
        ids.extend(_string_values([message.get("tool_call_id"), message.get("call_id")]))
    return _unique_strings(ids)


def _message_item_ids(messages: list[Any]) -> list[str]:
    ids: list[str] = []
    for message in messages:
        if isinstance(message, dict):
            ids.extend(_string_values([message.get("id")]))
    return _unique_strings(ids)


def _summarize_responses_input(input_value: Any) -> dict[str, Any]:
    system_prompts: list[str] = []
    system_prompt_items: list[dict[str, Any]] = []
    message_items: list[dict[str, Any]] = []
    request_tool_call_names: list[str] = []
    request_tool_call_ids: list[str] = []
    request_item_ids: list[str] = []
    message_count = 0
    tool_result_count = 0

    if isinstance(input_value, str):
        message_count += 1
        message_items.append(_message_item("responses.input", None, input_value))
    elif isinstance(input_value, list):
        for index, item in enumerate(input_value):
            if isinstance(item, str):
                message_count += 1
                message_items.append(_message_item("responses.input", index, item))
                continue
            if not isinstance(item, dict):
                continue

            item_id = _string_value(item.get("id"))
            if item_id is not None:
                request_item_ids.append(item_id)
            request_tool_call_ids.extend(_tool_call_ids(item))
            message_items.append(_message_item("responses.input", index, item))
            if item.get("role") in {"system", "developer"}:
                texts = _content_to_texts(item.get("content"))
                system_prompts.extend(texts)
                system_prompt_items.extend(
                    _system_prompt_item("responses.input", item.get("role"), index, text)
                    for text in texts
                )
            if _is_responses_tool_result_item(item):
                tool_result_count += 1
            if _is_responses_tool_call_item(item):
                name = _tool_call_name(item)
                if name is not None:
                    request_tool_call_names.append(name)
            request_tool_call_names.extend(_tool_names(item.get("tool_calls", [])))
            request_tool_call_ids.extend(_tool_call_ids(item.get("tool_calls", [])))
            if _is_responses_message_like_item(item):
                message_count += 1

    return {
        "system_prompts": system_prompts,
        "system_prompt_items": system_prompt_items,
        "message_count": message_count,
        "message_items": message_items,
        "request_tool_call_names": request_tool_call_names,
        "request_tool_call_ids": _unique_strings(request_tool_call_ids),
        "request_item_ids": _unique_strings(request_item_ids),
        "tool_result_count": tool_result_count,
    }


def _system_prompt_item(
    source: str, role: Any, index: Optional[int], text: str
) -> dict[str, Any]:
    return {
        "source": source,
        "role": role if isinstance(role, str) else "system",
        "index": index,
        "text": text,
        "char_count": len(text),
        "line_count": _line_count(text),
    }


def _message_item(source: str, index: Optional[int], item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return {
            "source": source,
            "index": index,
            "id": None,
            "role": "user",
            "type": "message",
            "text": item,
            "call_id": None,
            "tool_call_id": None,
            "tool_calls": [],
            "tool_call_names": [],
        }

    if not isinstance(item, dict):
        text = _content_preview(item)
        return {
            "source": source,
            "index": index,
            "id": None,
            "role": "unknown",
            "type": "unknown",
            "text": text,
            "call_id": None,
            "tool_call_id": None,
            "tool_calls": [],
            "tool_call_names": [],
        }

    item_type = item.get("type") if isinstance(item.get("type"), str) else "message"
    role = item.get("role") if isinstance(item.get("role"), str) else _inferred_role(item)
    tool_calls = item.get("tool_calls") if isinstance(item.get("tool_calls"), list) else []
    if _is_responses_tool_call_item(item):
        tool_calls = [item]

    projected = {
        "source": source,
        "index": index,
        "id": item.get("id") if isinstance(item.get("id"), str) else None,
        "role": role,
        "type": item_type,
        "name": item.get("name"),
        "text": _message_text(item),
        "call_id": item.get("call_id") if isinstance(item.get("call_id"), str) else None,
        "tool_call_id": item.get("tool_call_id") or item.get("call_id"),
        "tool_calls": tool_calls,
        "tool_call_names": _tool_names(tool_calls),
    }
    # A call's namespace says which surface offered the tool. It is the only
    # field that separates a collaboration call from a same-named ordinary one,
    # and it is dropped by the arguments-only view of a tool call.
    namespace = item.get("namespace")
    if isinstance(namespace, str) and namespace:
        projected["namespace"] = namespace
    return projected


def _message_text(item: dict[str, Any]) -> str:
    """The readable text of one Responses item, whichever key carries it.

    A tool output arrives either as a bare string or as content blocks, and the
    Responses API uses both for the same entry types: `function_call_output` is
    usually a string while `custom_tool_call_output` carries
    `[{"type": "input_text", "text": ...}]`. Accepting only the string form reported
    empty text for every entry of the second kind, which silently emptied everything
    downstream that reads text rather than ids -- error detection among them.

    The string branch stays first because `arguments` is a JSON document, not prose:
    it must survive as written rather than be walked for `text` keys.
    """
    texts = _content_to_texts(item.get("content"))
    if texts:
        return "\n\n".join(texts)
    for key in ("output", "text", "arguments"):
        value = item.get(key)
        if isinstance(value, str):
            return value
        blocks = _content_to_texts(value)
        if blocks:
            return "\n\n".join(blocks)
    return ""


def _inferred_role(item: dict[str, Any]) -> str:
    if _is_responses_tool_result_item(item):
        return "tool"
    if _is_responses_tool_call_item(item):
        return "assistant"
    if item.get("type") == AGENT_MESSAGE_ITEM_TYPE:
        return "agent"
    return "unknown"


def _content_preview(item: Any) -> str:
    if item is None:
        return ""
    return json.dumps(item, ensure_ascii=False)


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + 1


#: A Responses `input[]` item can be typed `agent_message`, and such an item
#: carries no `role`. Both halves are wire facts and both are load-bearing here:
#: counting only roled items reported zero messages for a turn that exchanged
#: several of these. What the type *means* to the client that emits it is not
#: this layer's business and lives in `codex_signals.agent_message_envelope`.
AGENT_MESSAGE_ITEM_TYPE = "agent_message"


def _is_responses_message_like_item(item: dict[str, Any]) -> bool:
    if _is_responses_tool_result_item(item) or _is_responses_tool_call_item(item):
        return False
    if isinstance(item.get("role"), str):
        return True
    return item.get("type") in {"message", AGENT_MESSAGE_ITEM_TYPE}


#: The Responses tool item vocabularies. Held as constants rather than restated inline at
#: each predicate because ``message_items`` keeps the same vocabulary for its own
#: registry, and the two drifting apart is what left every freeform tool output typed as
#: ``unknown``. ``tests/test_tool_item_vocabulary.py`` asserts the two stay equal, so a
#: sixth kind cannot be added to one side alone.
RESPONSES_TOOL_CALL_ITEM_TYPES = frozenset(
    {
        "function_call",
        "custom_tool_call",
        "local_shell_call",
        "tool_call",
    }
)

RESPONSES_TOOL_RESULT_ITEM_TYPES = frozenset(
    {
        "function_call_output",
        "custom_tool_call_output",
        "local_shell_call_output",
        "tool_result",
    }
)


def _normalized_item_type(item: dict[str, Any]) -> Optional[str]:
    """The item's type with the wire's dotted form folded to the underscored one.

    Applied to both predicates. It used to be applied only to the call side, and one half
    of a naming convention being normalised is the same asymmetry that left the result
    side missing two of its names.
    """
    item_type = item.get("type")
    if not isinstance(item_type, str):
        return None
    return item_type.replace(".", "_")


def _is_responses_tool_call_item(item: dict[str, Any]) -> bool:
    return _normalized_item_type(item) in RESPONSES_TOOL_CALL_ITEM_TYPES


def _is_responses_tool_result_item(item: dict[str, Any]) -> bool:
    return (
        _normalized_item_type(item) in RESPONSES_TOOL_RESULT_ITEM_TYPES
        or item.get("role") == "tool"
    )


#: Streaming argument events for the two Responses tool-call shapes. The
#: function form streams `delta` then `done`; the freeform form has only been
#: observed emitting `done`, carrying the whole input at once.
_RESPONSES_ARGUMENT_EVENTS = {
    "response.function_call_arguments.delta": ("delta", False),
    "response.function_call_arguments.done": ("arguments", True),
    "response.custom_tool_call_input.delta": ("delta", False),
    "response.custom_tool_call_input.done": ("input", True),
}

#: The arguments were closed by a `.done` event.
ARGUMENTS_FINAL = "final"
#: Fragments arrived but no `.done` did. The value is what was seen, which may
#: be truncated and may not parse. Reporting it as final would claim a
#: completeness the stream never gave.
ARGUMENTS_PARTIAL = "partial"


def _append_responses_tool_call_stream(event: dict[str, Any], acc: dict[str, dict[str, Any]]) -> None:
    """Accumulate the tool-call arguments that only exist as stream events.

    Codex always streams, so a Responses tool call arrives as an
    `output_item.added` naming it, then argument fragments, then a `done`. The
    fragments are addressed by `item_id`, which is the item's own identifier
    (`fc_*` / `ctc_*`), while everything downstream pairs on `call_id`. The two
    are joined here through the item event, never by rewriting the string: the
    `fc_<call_id>` spelling is a server convention, not a documented contract.
    """
    for candidate in (event.get("item"), event.get("output_item")):
        if not isinstance(candidate, dict) or not _is_responses_tool_call_item(candidate):
            continue
        item_id = _string_value(candidate.get("id"))
        if item_id is None:
            continue
        slot = acc.setdefault(item_id, {"parts": [], "state": None})
        slot["call_id"] = _string_value(candidate.get("call_id")) or slot.get("call_id")
        slot["name"] = _tool_call_name(candidate) or slot.get("name")

    handler = _RESPONSES_ARGUMENT_EVENTS.get(event.get("type"))
    if handler is None:
        return
    field, is_done = handler
    item_id = _string_value(event.get("item_id"))
    if item_id is None:
        return
    value = event.get(field)
    if not isinstance(value, str):
        return
    slot = acc.setdefault(item_id, {"parts": [], "state": None})
    if is_done:
        # The terminal event repeats the whole value, so it replaces the
        # fragments rather than extending them.
        slot["final"] = value
        slot["state"] = ARGUMENTS_FINAL
    else:
        slot["parts"].append(value)
        if slot.get("state") is None:
            slot["state"] = ARGUMENTS_PARTIAL


def _finalize_responses_tool_call_acc(acc: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item_id in acc:
        slot = acc[item_id]
        raw = slot.get("final") if slot.get("state") == ARGUMENTS_FINAL else "".join(slot["parts"])
        entry: dict[str, Any] = {"id": slot.get("call_id") or item_id, "item_id": item_id}
        name = slot.get("name")
        if name:
            entry["name"] = name
        if raw:
            try:
                entry["input"] = json.loads(raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                # Freeform tool input is not JSON, and a truncated fragment
                # cannot be. Keep the text rather than dropping the argument.
                entry["input"] = raw
            entry["arguments_state"] = slot.get("state") or ARGUMENTS_PARTIAL
        calls.append(entry)
    return calls


def _append_responses_stream_event(
    event: dict[str, Any], text_parts: list[str], tool_call_names: list[str]
) -> None:
    if event.get("type") == "response.output_text.delta":
        delta = event.get("delta")
        if isinstance(delta, str):
            text_parts.append(delta)
    elif event.get("type") == "response.output_text.done" and not text_parts:
        text = event.get("text")
        if isinstance(text, str):
            text_parts.append(text)

    for candidate in (event, event.get("item"), event.get("output_item")):
        if not isinstance(candidate, dict):
            continue
        if not _is_responses_tool_call_item(candidate):
            continue
        name = _tool_call_name(candidate)
        if name is not None and name not in tool_call_names:
            tool_call_names.append(name)


def _append_responses_output(
    payload: dict[str, Any], text_parts: list[str], tool_call_names: list[str]
) -> None:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        text_parts.append(output_text)

    output = payload.get("output")
    if not isinstance(output, list):
        return

    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call":
            name = _tool_call_name(item)
            if name is not None:
                tool_call_names.append(name)
        else:
            text_parts.extend(_content_to_texts(item.get("content")))
