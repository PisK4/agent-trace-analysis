from __future__ import annotations

import json
from collections import Counter
from typing import Any


API_FAMILY = "anthropic-messages"


def is_anthropic_messages_path(path: str) -> bool:
    return path.split("?", 1)[0].rstrip("/") == "/v1/messages"


def parse_anthropic_request(
    path: str, headers: dict[str, str], body: bytes
) -> dict[str, Any]:
    payload, json_valid = _loads_object(body)
    if not json_valid or payload is None:
        return {"api_family": API_FAMILY, "json_valid": False}

    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []
    system_prompt_items = _system_prompt_items(payload.get("system"))
    message_summary = _message_items(messages)
    tool_items = _tool_items(tools)

    return {
        "api_family": API_FAMILY,
        "json_valid": True,
        "model": payload.get("model"),
        "stream": bool(payload.get("stream", False)),
        "system_prompts": [item["text"] for item in system_prompt_items if item.get("text")],
        "system_prompt_items": system_prompt_items,
        "message_count": len(messages),
        "messages": messages,
        "message_items": message_summary["message_items"],
        "tools": tools,
        "tool_items": tool_items,
        "tool_names": _unique_strings([item.get("name") for item in tool_items]),
        "tool_choice": payload.get("tool_choice"),
        "response_format": None,
        "request_previous_response_id": None,
        "request_metadata_ids": _metadata_ids(headers, payload.get("metadata")),
        "request_tool_call_names": message_summary["tool_call_names"],
        # Request-side ids name the tool calls this context carries, so the same id
        # arriving from both the tool_use block and its tool_result must count once.
        "request_tool_call_ids": _unique_strings(message_summary["tool_call_ids"]),
        "request_item_ids": message_summary["item_ids"],
        "tool_result_count": message_summary["tool_result_count"],
        "content_block_counts": message_summary["content_block_counts"],
    }


def parse_anthropic_response(content_type: str, body: bytes) -> dict[str, Any]:
    if "text/event-stream" in content_type.lower():
        return _parse_anthropic_sse_response(body)

    payload, json_valid = _loads_object(body)
    if not json_valid or payload is None:
        return {"api_family": API_FAMILY, "json_valid": False, "response_text": ""}
    return _summarize_anthropic_message(payload)


def _loads_object(body: bytes) -> tuple[dict[str, Any] | None, bool]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, False
    if not isinstance(value, dict):
        return None, False
    return value, True


def _header_value(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower() and isinstance(value, str):
            return value
    return None


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _content_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict)]
    if isinstance(content, dict):
        return [content]
    return []


def _text_from_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        texts: list[str] = []
        for item in value:
            texts.extend(_text_from_value(item))
        return texts
    if isinstance(value, dict):
        texts = []
        if isinstance(value.get("text"), str):
            texts.append(value["text"])
        if "content" in value:
            texts.extend(_text_from_value(value["content"]))
        return texts
    return []


def _system_prompt_items(system: Any) -> list[dict[str, str]]:
    if system is None:
        return []
    if isinstance(system, list):
        items: list[dict[str, str]] = []
        for index, block in enumerate(system):
            text = "\n".join(_text_from_value(block)).strip()
            if text:
                items.append({"path": f"system[{index}]", "text": text})
        return items
    text = "\n".join(_text_from_value(system)).strip()
    return [{"path": "system", "text": text}] if text else []


def _tool_items(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    items: list[dict[str, Any]] = []
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            continue
        function_def = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = tool.get("name") or function_def.get("name") or f"tool_{index}"
        items.append(
            {
                "index": index,
                "name": name,
                "type": tool.get("type") or "tool",
                "description": tool.get("description") or function_def.get("description"),
                "parameters": tool.get("input_schema")
                or tool.get("parameters")
                or function_def.get("parameters"),
            }
        )
    return items


def _metadata_ids(headers: dict[str, str], metadata: Any) -> dict[str, str]:
    ids: dict[str, str] = {}
    if isinstance(metadata, dict):
        for key in ("conversation_id", "session_id", "thread_id", "user_id"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                ids[key] = value
    session_id = _header_value(headers, "X-Claude-Code-Session-Id")
    if session_id:
        ids["session_id"] = session_id
    return ids


def _message_items(messages: Any) -> dict[str, Any]:
    if not isinstance(messages, list):
        return _empty_message_summary()

    message_items: list[dict[str, Any]] = []
    tool_call_names: list[str] = []
    tool_call_ids: list[str] = []
    item_ids: list[str] = []
    tool_result_count = 0
    counts: Counter[str] = Counter()

    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        blocks = _content_blocks(message.get("content"))
        content_types: list[str] = []
        message_texts: list[str] = []
        message_tool_names: list[str] = []
        message_tool_ids: list[str] = []
        if isinstance(message.get("id"), str):
            item_ids.append(message["id"])

        for block in blocks:
            block_type = _block_type(block)
            content_types.append(block_type)
            counts[block_type] += 1
            message_texts.extend(_block_texts(block))
            if block_type == "tool_use":
                name = block.get("name")
                tool_id = block.get("id")
                if isinstance(name, str):
                    tool_call_names.append(name)
                    message_tool_names.append(name)
                if isinstance(tool_id, str):
                    tool_call_ids.append(tool_id)
                    item_ids.append(tool_id)
                    message_tool_ids.append(tool_id)
            elif block_type == "tool_result":
                tool_result_count += 1
                tool_use_id = block.get("tool_use_id")
                if isinstance(tool_use_id, str):
                    tool_call_ids.append(tool_use_id)
                    item_ids.append(tool_use_id)
                    message_tool_ids.append(tool_use_id)

        message_items.append(
            {
                "index": index,
                "role": role,
                "content_types": content_types,
                "text": "\n".join(message_texts),
                # Keep position order: parallel same-name tool_use must not collapse.
                "tool_call_names": list(message_tool_names),
                "tool_call_ids": list(message_tool_ids),
            }
        )

    return {
        "message_items": message_items,
        # Paired arrays stay order-aligned for zip consumers; do not unique.
        "tool_call_names": list(tool_call_names),
        "tool_call_ids": list(tool_call_ids),
        "item_ids": _unique_strings(item_ids),
        "tool_result_count": tool_result_count,
        "content_block_counts": dict(counts),
    }


def _empty_message_summary() -> dict[str, Any]:
    return {
        "message_items": [],
        "tool_call_names": [],
        "tool_call_ids": [],
        "item_ids": [],
        "tool_result_count": 0,
        "content_block_counts": {},
    }


def _block_type(block: dict[str, Any]) -> str:
    block_type = block.get("type")
    if isinstance(block_type, str) and block_type:
        return block_type
    if isinstance(block.get("text"), str):
        return "text"
    return "unknown"


def _block_texts(block: dict[str, Any]) -> list[str]:
    block_type = _block_type(block)
    if block_type in {"text", "thinking"}:
        return _text_from_value(block)
    return []


def _summarize_anthropic_message(payload: dict[str, Any]) -> dict[str, Any]:
    response_id = payload.get("id") if isinstance(payload.get("id"), str) else None
    blocks = _content_blocks(payload.get("content"))
    block_summary = _response_block_summary(blocks)
    finish_reasons = [payload["stop_reason"]] if isinstance(payload.get("stop_reason"), str) else []
    item_ids = _unique_strings(([response_id] if response_id else []) + block_summary["item_ids"])
    response_text = "\n\n".join(block_summary["texts"])
    return {
        "api_family": API_FAMILY,
        "json_valid": True,
        "response_id": response_id,
        "response_text": response_text,
        "response_output_texts": block_summary["texts"],
        "response_tool_call_names": block_summary["tool_call_names"],
        "response_tool_call_ids": block_summary["tool_call_ids"],
        "response_tool_calls": block_summary["tool_calls"],
        "response_blocks": blocks,
        "response_item_ids": item_ids,
        "finish_reasons": finish_reasons,
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
        "content_block_counts": block_summary["content_block_counts"],
    }


def _response_block_summary(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    texts: list[str] = []
    tool_call_names: list[str] = []
    tool_call_ids: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    item_ids: list[str] = []
    counts: Counter[str] = Counter()
    for block in blocks:
        block_type = _block_type(block)
        counts[block_type] += 1
        texts.extend(_block_texts(block))
        if block_type == "tool_use":
            name = block.get("name")
            tool_id = block.get("id")
            if isinstance(name, str):
                tool_call_names.append(name)
            if isinstance(tool_id, str):
                tool_call_ids.append(tool_id)
                item_ids.append(tool_id)
            tool_call: dict[str, Any] = {}
            if isinstance(name, str):
                tool_call["name"] = name
            if isinstance(tool_id, str):
                tool_call["id"] = tool_id
            if isinstance(block.get("input"), dict):
                tool_call["input"] = block["input"]
            if tool_call:
                tool_calls.append(tool_call)
    return {
        "texts": [text for text in texts if text],
        # Paired with tool_call_ids by content-block order; never unique-collapse
        # (parallel same-name tool_use e.g. 4× Agent must stay equal-length).
        "tool_call_names": list(tool_call_names),
        "tool_call_ids": list(tool_call_ids),
        "tool_calls": tool_calls,
        "item_ids": _unique_strings(item_ids),
        "content_block_counts": dict(counts),
    }


def _parse_anthropic_sse_response(body: bytes) -> dict[str, Any]:
    message_id: str | None = None
    usage: dict[str, Any] = {}
    finish_reasons: list[str] = []
    blocks: dict[int, dict[str, Any]] = {}

    for event in _iter_sse_data_events(body):
        event_type = event.get("type")
        if event_type == "message_start" and isinstance(event.get("message"), dict):
            message = event["message"]
            if isinstance(message.get("id"), str):
                message_id = message["id"]
            if isinstance(message.get("usage"), dict):
                usage.update(message["usage"])
        elif event_type == "content_block_start":
            index = event.get("index")
            block = event.get("content_block")
            if isinstance(index, int) and isinstance(block, dict):
                copied = dict(block)
                copied["_text_parts"] = []
                copied["_partial_json_parts"] = []
                blocks[index] = copied
        elif event_type == "content_block_delta":
            index = event.get("index")
            delta = event.get("delta")
            if isinstance(index, int) and isinstance(delta, dict):
                block = blocks.setdefault(index, {"_text_parts": [], "_partial_json_parts": []})
                if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                    block.setdefault("_text_parts", []).append(delta["text"])
                elif delta.get("type") == "thinking_delta" and isinstance(
                    delta.get("thinking"), str
                ):
                    block.setdefault("_text_parts", []).append(delta["thinking"])
                elif delta.get("type") == "input_json_delta" and isinstance(
                    delta.get("partial_json"), str
                ):
                    block.setdefault("_partial_json_parts", []).append(delta["partial_json"])
        elif event_type == "message_delta":
            delta = event.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("stop_reason"), str):
                finish_reasons.append(delta["stop_reason"])
            if isinstance(event.get("usage"), dict):
                usage.update(event["usage"])

    ordered_blocks = [_finalize_sse_block(blocks[index]) for index in sorted(blocks)]
    block_summary = _response_block_summary(ordered_blocks)
    item_ids = _unique_strings(([message_id] if message_id else []) + block_summary["item_ids"])
    response_text = "\n\n".join(block_summary["texts"])
    return {
        "api_family": API_FAMILY,
        "json_valid": True,
        "response_id": message_id,
        "response_text": response_text,
        "response_output_texts": block_summary["texts"],
        "response_tool_call_names": block_summary["tool_call_names"],
        "response_tool_call_ids": block_summary["tool_call_ids"],
        "response_tool_calls": block_summary["tool_calls"],
        "response_blocks": ordered_blocks,
        "response_item_ids": item_ids,
        "finish_reasons": _unique_strings(finish_reasons),
        "usage": usage,
        "content_block_counts": block_summary["content_block_counts"],
    }


def _iter_sse_data_events(body: bytes) -> list[dict[str, Any]]:
    text = body.decode("utf-8", errors="replace").replace("\r\n", "\n")
    events: list[dict[str, Any]] = []
    for raw_event in text.split("\n\n"):
        data_lines: list[str] = []
        for line in raw_event.split("\n"):
            if line.startswith("data:"):
                data = line[5:]
                if data.startswith(" "):
                    data = data[1:]
                data_lines.append(data)
        if not data_lines:
            continue
        data_text = "\n".join(data_lines).strip()
        if not data_text or data_text == "[DONE]":
            continue
        try:
            event = json.loads(data_text)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _finalize_sse_block(block: dict[str, Any]) -> dict[str, Any]:
    finalized = {
        key: value for key, value in block.items() if not key.startswith("_")
    }
    text_parts = block.get("_text_parts")
    if isinstance(text_parts, list) and text_parts:
        finalized["text"] = "".join(part for part in text_parts if isinstance(part, str))

    partial_json_parts = block.get("_partial_json_parts")
    if isinstance(partial_json_parts, list) and partial_json_parts:
        partial_json = "".join(part for part in partial_json_parts if isinstance(part, str))
        finalized["partial_json"] = partial_json
        try:
            parsed = json.loads(partial_json)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            finalized["input"] = parsed
    return finalized
