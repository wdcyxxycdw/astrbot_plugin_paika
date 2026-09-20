from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedAction:
    action: str
    room_id: int | None = None
    room_title: str | None = None
    capacity: int | None = None
    content: str = ""
    reply_message_id: str | None = None


_ACTIONS = {
    "排卡": "create",
    "开房": "create",
    "查房": "list",
    "房间": "list",
    "上车": "join",
    "下车": "leave",
    "发车": "start",
    "结束": "end",
}


def extract_reply_message_id(event) -> str | None:
    getter = getattr(event, "get_messages", None)
    messages = getter() if callable(getter) else getattr(event, "message", [])
    if messages is None:
        return None
    for component in messages:
        name = getattr(component, "type", "")
        value = getattr(component, "id", None)
        if isinstance(component, dict):
            name = component.get("type", "")
            data = component.get("data")
            if isinstance(data, dict):
                value = data.get("id") or data.get("message_id") or data.get("messageId")
            else:
                value = None
        if str(name).lower() == "reply" and value is not None:
            return str(value)
    return None


def extract_text(event) -> str:
    getter = getattr(event, "get_message_str", None)
    value = getter() if callable(getter) else getattr(event, "message_str", "")
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def parse_text(text: str, reply_message_id: str | None = None) -> ParsedAction | None:
    text = unicodedata.normalize("NFKC", text or "").strip()
    text = _strip_leading_mentions(text)
    text = re.sub(r"^/", "", text).strip()
    if not text:
        return None
    parts = text.split(maxsplit=2)
    action = _ACTIONS.get(parts[0])
    if action is None:
        return None
    if action == "list":
        room_id, room_title = _room_selector(parts[1:])
        return ParsedAction(
            action,
            room_id=room_id,
            room_title=room_title,
            reply_message_id=reply_message_id,
        )
    if action == "create":
        capacity = None
        content = ""
        if len(parts) > 1 and parts[1].isdigit():
            capacity = int(parts[1])
            content = parts[2] if len(parts) > 2 else ""
        else:
            content = " ".join(parts[1:])
        return ParsedAction(action, capacity=capacity, content=content)
    room_id, room_title = _room_selector(parts[1:])
    return ParsedAction(
        action,
        room_id=room_id,
        room_title=room_title,
        reply_message_id=reply_message_id,
    )


def parse_event(event) -> ParsedAction | None:
    return parse_text(extract_text(event), extract_reply_message_id(event))


def _strip_leading_mentions(text: str) -> str:
    while True:
        stripped = re.sub(
            r"^(?:\[(?:At|at):[^\]]+\]|@[^\s]+)\s*",
            "",
            text,
        )
        if stripped == text:
            return text
        text = stripped


def _room_selector(values: list[str]) -> tuple[int | None, str | None]:
    if not values:
        return None, None
    value = " ".join(values).strip()
    if value.isdigit():
        return int(value), None
    return None, value or None


def _room_id(value: str) -> int | None:
    return int(value) if value.isdigit() else None
