from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import Member, Room


@dataclass(frozen=True)
class MessageSendResult:
    sent: bool
    message_id: str | None = None


def room_summary(room: Room) -> str:
    status_icon = {
        "waiting": "🟡",
        "started": "🟢",
        "ended": "⚪",
    }.get(room.status.value, "⚪")
    return (
        f"🎴 {room.title}\n"
        "━━━━━━━━━━━━\n"
        f"{status_icon} 状态：{room.status.label}\n"
        f"👥 进度：{room.member_count}/{room.capacity}"
    )


def room_creation_text(room: Room) -> str:
    return (
        f"{room_summary(room)}\n\n"
        "点击本消息下方表情按钮即可上车，取消点击即可下车。\n"
        "也可以回复本消息发送“上车/下车”。\n"
        "房主可使用 /发车，或使用 /结束 解散房间。"
    )


def notification_text(action: str, room: Room, detail: str) -> str:
    return f"{detail}\n\n{room_summary(room)}"


def message_chain(
    text: str,
    members: Iterable[Member] = (),
    reply_id: str | None = None,
    include_members: bool = True,
    actor_id: str | None = None,
):
    import astrbot.api.message_components as components

    member_list = tuple(members)
    chain = []
    if reply_id:
        chain.append(components.Reply(id=str(reply_id)))
    if actor_id:
        chain.append(components.At(qq=str(actor_id)))
        text = " " + text
    if not include_members:
        chain.append(components.Plain(text))
        return chain
    chain.append(components.Plain(text + "\n\n👥 房间成员："))
    if member_list:
        for member in member_list:
            chain.append(components.At(qq=str(member.user_id)))
        chain.append(components.Plain("\n"))
    else:
        chain.append(components.Plain("暂无成员\n"))
    return chain


def room_list_chain(rooms: Iterable[Room]):
    import astrbot.api.message_components as components

    room_list = list(rooms)
    chain = [components.Plain("🎴 当前排卡房间\n\n")]
    for index, room in enumerate(room_list):
        chain.extend(message_chain(room_summary(room), room.members))
        if index != len(room_list) - 1:
            chain.append(components.Plain("\n"))
    return chain


async def send_group_message(
    event,
    group_id: str,
    components: list[Any],
) -> MessageSendResult:
    payload = [_component_to_dict(component) for component in components]
    bot = getattr(event, "bot", None)
    if bot is not None:
        call_action = getattr(bot, "call_action", None)
        if callable(call_action):
            try:
                result = await call_action(
                    "send_group_msg",
                    group_id=int(group_id) if str(group_id).isdigit() else group_id,
                    message=payload,
                )
                if not response_was_successful(result):
                    raise RuntimeError("send_group_msg returned failure")
                return MessageSendResult(True, message_id_from_response(result))
            except Exception:
                pass
        send_group_msg = getattr(bot, "send_group_msg", None)
        if callable(send_group_msg):
            try:
                result = await send_group_msg(
                    group_id=int(group_id) if str(group_id).isdigit() else group_id,
                    message=payload,
                )
                if not response_was_successful(result):
                    raise RuntimeError("send_group_msg returned failure")
                return MessageSendResult(True, message_id_from_response(result))
            except Exception:
                pass

    send = getattr(event, "send", None)
    if callable(send):
        try:
            from astrbot.api.event import MessageChain

            result = await send(MessageChain(components))
            return MessageSendResult(True, message_id_from_response(result))
        except Exception:
            return MessageSendResult(False)
    return MessageSendResult(False)


async def send_context_message(context, origin: str | None, components: list[Any]) -> bool:
    if not origin:
        return False
    try:
        from astrbot.api.event import MessageChain

        result = await context.send_message(origin, MessageChain(components))
        return bool(result)
    except Exception:
        return False


def response_was_successful(response: Any) -> bool:
    if not isinstance(response, dict):
        return True
    status = str(response.get("status", "")).lower()
    if status in {"failed", "failure", "error"}:
        return False
    retcode = response.get("retcode")
    return retcode in {None, 0, "0"}


def message_id_from_response(response: Any) -> str | None:
    if response is None:
        return None
    if isinstance(response, dict):
        data = response.get("data")
        if isinstance(data, dict):
            value = data.get("message_id") or data.get("messageId") or data.get("id")
            if value is not None:
                return str(value)
        elif data is not None:
            value = _message_id_attribute(data)
            if value is not None:
                return value
        value = response.get("message_id") or response.get("messageId") or response.get("id")
        if value is not None:
            return str(value)
    return _message_id_attribute(response)


def _message_id_attribute(value: Any) -> str | None:
    for name in ("message_id", "messageId", "id"):
        candidate = getattr(value, name, None)
        if candidate is not None:
            return str(candidate)
    return None


def _component_to_dict(component: Any) -> dict[str, Any]:
    converter = getattr(component, "toDict", None)
    if callable(converter):
        value = converter()
        if isinstance(value, dict):
            return value
    converter = getattr(component, "to_dict", None)
    if callable(converter):
        value = converter()
        if isinstance(value, dict):
            return value
    if isinstance(component, dict):
        return component
    if hasattr(component, "text"):
        return {"type": "text", "data": {"text": str(component.text)}}
    return {"type": "text", "data": {"text": str(component)}}
