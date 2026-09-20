from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReactionNotice:
    group_id: str
    message_id: str
    user_id: str
    emoji_id: str
    is_add: bool


def parse_reaction_notice(
    raw: Any,
    target_emoji_id: str | None = None,
) -> ReactionNotice | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("post_type") != "notice":
        return None
    notice_type = str(raw.get("notice_type", ""))
    if notice_type not in {"group_msg_emoji_like", "group_msg_emoji_like_event"}:
        return None
    group_id = _text(raw.get("group_id"))
    message_id = _text(raw.get("message_id"))
    user_id = _text(raw.get("user_id"))
    if not group_id or not message_id or not user_id:
        return None

    emoji_id = _text(raw.get("emoji_id") or raw.get("emojiId"))
    likes = raw.get("likes") or raw.get("emoji_likes") or raw.get("emoji_likes_list") or []
    if isinstance(likes, dict):
        likes = [likes]
    for like in likes:
        if not isinstance(like, dict):
            continue
        candidate = _text(like.get("emoji_id") or like.get("emojiId"))
        if target_emoji_id and candidate == str(target_emoji_id):
            emoji_id = candidate
            break
        if not emoji_id:
            emoji_id = candidate
    if not emoji_id:
        return None
    if target_emoji_id and emoji_id != str(target_emoji_id):
        return None

    is_add = _bool_value(raw.get("is_add"))
    if is_add is None:
        is_add = _bool_value(raw.get("isAdd"))
    if is_add is None:
        is_add = _bool_value(raw.get("set"))
    if is_add is None:
        subtype = str(raw.get("sub_type", "")).lower()
        if subtype in {"add", "like", "liked"}:
            is_add = True
        elif subtype in {"remove", "cancel", "unlike", "unliked"}:
            is_add = False
    if is_add is None:
        return None
    return ReactionNotice(group_id, message_id, user_id, emoji_id, is_add)


async def set_message_reaction(event, message_id: str, emoji_id: str, emoji_type: int | None = None) -> bool:
    bot = getattr(event, "bot", None)
    call_action = getattr(bot, "call_action", None)
    if not callable(call_action):
        return False
    params = {
        "message_id": int(message_id) if str(message_id).isdigit() else message_id,
        "emoji_id": str(emoji_id),
        "set": True,
    }
    attempts = [params]
    if emoji_type is not None:
        params_with_type = dict(params)
        params_with_type["emoji_type"] = emoji_type
        attempts.insert(0, params_with_type)
    for attempt in attempts:
        try:
            await call_action("set_msg_emoji_like", **attempt)
            return True
        except Exception:
            continue
    return False


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"1", "true", "yes", "add", "like", "liked"}:
            return True
        if value in {"0", "false", "no", "remove", "cancel", "unlike", "unliked"}:
            return False
    return None
