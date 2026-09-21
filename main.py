from __future__ import annotations

import asyncio
import sys
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from paika.models import RoomStatus
from paika.parser import (
    ParsedAction,
    extract_reply_message_id,
    extract_text,
    parse_event,
)
from paika.reactions import parse_reaction_notice, set_message_reaction
from paika.service import PaikaService
from paika.storage import Storage
from paika.transport import (
    message_chain,
    notification_text,
    room_creation_text,
    room_list_chain,
    room_summary,
    send_context_message,
    send_group_message,
)


_COMMAND_FILTER_AVAILABLE = callable(getattr(filter, "command", None))


def _group_message_filter():
    decorator = getattr(filter, "event_message_type", None)
    event_types = getattr(filter, "EventMessageType", None)
    message_type = getattr(event_types, "GROUP_MESSAGE", None)
    if message_type is None:
        message_type = getattr(event_types, "ALL", None)
    if callable(decorator) and message_type is not None:
        return decorator(message_type)
    return lambda function: function


def _aiocqhttp_filter():
    decorator = getattr(filter, "platform_adapter_type", None)
    platform_types = getattr(filter, "PlatformAdapterType", None)
    adapter_type = getattr(platform_types, "AIOCQHTTP", None)
    if callable(decorator) and adapter_type is not None:
        return decorator(adapter_type)
    return lambda function: function


def _command_filter(command_name: str, aliases: set[str] | None = None):
    decorator = getattr(filter, "command", None)
    if callable(decorator):
        return decorator(command_name, alias=aliases or set())
    return lambda function: function


def _llm_tool_filter(name: str):
    decorator = getattr(filter, "llm_tool", None)
    if callable(decorator):
        return decorator(name=name)
    return lambda function: function


@register("paika", "paika", "群聊排卡组队插件", "0.1.1")
class PaikaPlugin(Star):
    def __init__(self, context: Context, config: dict[str, Any] | None = None):
        super().__init__(context)
        config = config or {}
        self.max_capacity = _int_config(config, "max_capacity", 20, minimum=2, maximum=100)
        self.default_capacity = min(
            _int_config(config, "default_capacity", 5, minimum=2, maximum=100),
            self.max_capacity,
        )
        self.default_content = str(config.get("default_content", "未填写")).strip() or "未填写"
        self.reaction_enabled = _bool_config(config, "reaction_enabled", True)
        self.reaction_emoji_id = str(config.get("reaction_emoji_id", "76")).strip() or "76"
        self.reaction_emoji_type = _int_config(config, "reaction_emoji_type", 1, minimum=0)
        self.show_ended_in_list = _bool_config(config, "show_ended_in_list", False)
        self.auto_disband_minutes = _int_config(
            config, "auto_disband_minutes", 15, minimum=0, maximum=1440
        )
        self.reminder_minutes = _int_config(
            config, "reminder_minutes", 5, minimum=0, maximum=1440
        )
        self.storage = Storage(self._data_dir() / "paika.db")
        self.service = PaikaService(self.storage, self.max_capacity)
        self._timer_stop: asyncio.Event | None = None
        self._timer_task: asyncio.Task | None = None
        self._operation_lock: asyncio.Lock | None = None
        self._closing = False

    async def initialize(self):
        if self._closing:
            return
        if self._timer_task is not None and not self._timer_task.done():
            return
        self._timer_stop = asyncio.Event()
        self._timer_task = asyncio.create_task(self._room_timer_loop())

    @_group_message_filter()
    @_command_filter("排卡", {"开房"})
    async def command_create_room(self, event: AstrMessageEvent):
        await self._handle_command(event)

    @_group_message_filter()
    @_command_filter("查房", {"房间"})
    async def command_list_rooms(self, event: AstrMessageEvent):
        await self._handle_command(event)

    @_group_message_filter()
    @_command_filter("上车")
    async def command_join_room(self, event: AstrMessageEvent):
        await self._handle_command(event)

    @_group_message_filter()
    @_command_filter("下车")
    async def command_leave_room(self, event: AstrMessageEvent):
        await self._handle_command(event)

    @_group_message_filter()
    @_command_filter("发车")
    async def command_start_room(self, event: AstrMessageEvent):
        await self._handle_command(event)

    @_group_message_filter()
    @_command_filter("结束")
    async def command_end_room(self, event: AstrMessageEvent):
        await self._handle_command(event)

    @_llm_tool_filter("paika_create_room")
    async def llm_create_room(
        self,
        event: AstrMessageEvent,
        capacity: int = 0,
        content: str = "",
    ):
        """创建一个群聊排卡房间。

        Args:
            capacity(number): 房间总人数；不确定时传 0，使用插件默认人数。
            content(string): 房间标题，例如“周末开黑”；没有标题时传空字符串。
        """
        return await self._run_tool_action(
            event,
            ParsedAction(
                "create",
                capacity=capacity if capacity > 0 else self.default_capacity,
                content=content.strip() or self.default_content,
            ),
        )

    @_llm_tool_filter("paika_list_rooms")
    async def llm_list_rooms(self, event: AstrMessageEvent):
        """查看当前群聊中正在排卡的房间。"""
        return await self._run_tool_action(event, ParsedAction("list"))

    @_llm_tool_filter("paika_join_room")
    async def llm_join_room(self, event: AstrMessageEvent, room_title: str = ""):
        """加入当前群聊的排卡房间。

        Args:
            room_title(string): 房间标题；不确定时传空字符串，插件会使用回复消息或唯一候选房间。
        """
        return await self._run_tool_action(
            event,
            self._room_action("join", room_title, event),
        )

    @_llm_tool_filter("paika_leave_room")
    async def llm_leave_room(self, event: AstrMessageEvent, room_title: str = ""):
        """退出当前群聊的排卡房间。

        Args:
            room_title(string): 房间标题；不确定时传空字符串，插件会使用回复消息或唯一候选房间。
        """
        return await self._run_tool_action(
            event,
            self._room_action("leave", room_title, event),
        )

    @_llm_tool_filter("paika_start_room")
    async def llm_start_room(self, event: AstrMessageEvent, room_title: str = ""):
        """由房主发车当前群聊的排卡房间。

        Args:
            room_title(string): 房间标题；不确定时传空字符串，插件会使用回复消息或唯一候选房间。
        """
        return await self._run_tool_action(
            event,
            self._room_action("start", room_title, event),
        )

    @_llm_tool_filter("paika_end_room")
    async def llm_end_room(self, event: AstrMessageEvent, room_title: str = ""):
        """由房主结束当前群聊的排卡房间。

        Args:
            room_title(string): 房间标题；不确定时传空字符串，插件会使用回复消息或唯一候选房间。
        """
        return await self._run_tool_action(
            event,
            self._room_action("end", room_title, event),
        )

    @_group_message_filter()
    async def on_message(self, event: AstrMessageEvent):
        group_id = _group_id(event)
        if not group_id:
            return
        parsed = parse_event(event)
        if parsed is None:
            return
        if _COMMAND_FILTER_AVAILABLE:
            if not parsed.reply_message_id:
                return
            if _starts_with_slash(event) or _has_at_component(event):
                return
            if parsed.action not in {"join", "leave", "start", "end"}:
                return
        await self._handle_action(event, group_id, parsed)

    @_aiocqhttp_filter()
    @_group_message_filter()
    async def on_reaction(self, event: AstrMessageEvent):
        if self._closing or not self.reaction_enabled:
            return
        raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
        notice = parse_reaction_notice(raw, self.reaction_emoji_id)
        if notice is None:
            return
        self_id = _self_id(event)
        if self_id and notice.user_id == self_id:
            return
        async with self._operation_lock_for():
            room = self.storage.get_room_by_bot_message(notice.group_id, notice.message_id)
            if room is None:
                return
            actor_name = _sender_name(event, notice.user_id)
            if notice.is_add:
                result = self.service.join(room, notice.user_id, actor_name)
            else:
                result = self.service.leave(room, notice.user_id, actor_name)
            if result.room is None:
                return
            text = notification_text("reaction", result.room, result.message)
            await send_group_message(
                event,
                notice.group_id,
                message_chain(text, result.room.members, actor_id=notice.user_id),
            )
            _stop_event(event)

    async def _handle_command(self, event: AstrMessageEvent) -> None:
        group_id = _group_id(event)
        if not group_id:
            return
        parsed = parse_event(event)
        if parsed is not None:
            await self._handle_action(event, group_id, parsed)

    async def _run_tool_action(self, event, parsed: ParsedAction):
        group_id = _group_id(event)
        if not group_id:
            return "排卡操作只能在群聊中使用。"
        if parsed.reply_message_id is None and parsed.action != "create":
            parsed = ParsedAction(
                parsed.action,
                room_id=parsed.room_id,
                room_title=parsed.room_title,
                capacity=parsed.capacity,
                content=parsed.content,
                reply_message_id=extract_reply_message_id(event),
            )
        await self._handle_action(event, group_id, parsed)
        _stop_event(event)
        return None

    def _room_action(self, action: str, room_title: str, event) -> ParsedAction:
        return ParsedAction(
            action,
            room_title=room_title.strip() or None,
            reply_message_id=extract_reply_message_id(event),
        )

    async def _handle_action(self, event, group_id: str, parsed: ParsedAction) -> None:
        if self._closing:
            return
        async with self._operation_lock_for():
            await self._handle_action_locked(event, group_id, parsed)

    async def _handle_action_locked(self, event, group_id: str, parsed: ParsedAction) -> None:
        user_id = _sender_id(event)
        user_name = _sender_name(event, user_id)
        source_message_id = _message_id(event)

        if parsed.action == "create":
            result = self.service.create_room(
                group_id,
                user_id,
                user_name,
                parsed.capacity or self.default_capacity,
                parsed.content or self.default_content,
                source_message_id,
                _message_origin(event),
            )
            if not result.ok or result.room is None:
                await self._send_text(event, group_id, result.message)
                _stop_event(event)
                return
            room = result.room
            components = message_chain(
                room_creation_text(room),
                room.members,
                reply_id=source_message_id,
            )
            send_result = await send_group_message(event, group_id, components)
            if not send_result.sent:
                logger.error(f"排卡房间消息发送失败，结束房间 room_id={room.room_id}")
                self.storage.end_room(room.room_id, expected_status=RoomStatus.WAITING)
                _stop_event(event)
                return
            if send_result.message_id:
                self.storage.set_bot_message_id(room.room_id, send_result.message_id)
                if self.reaction_enabled:
                    await set_message_reaction(
                        event,
                        send_result.message_id,
                        self.reaction_emoji_id,
                        self.reaction_emoji_type,
                    )
            else:
                logger.warning(
                    f"排卡房间消息已发送但未取得消息 ID，Reply/reaction 无法绑定 room_id={room.room_id}"
                )
            _stop_event(event)
            return

        if parsed.action == "list":
            rooms = self.service.list_rooms(group_id, self.show_ended_in_list)
            await send_group_message(
                event,
                group_id,
                room_list_chain(rooms),
            )
            _stop_event(event)
            return

        selection = self.service.select_room(
            group_id,
            parsed.room_id,
            parsed.reply_message_id,
            parsed.action,
            parsed.room_title,
        )
        if selection.room is None:
            text = (
                "当前群有多个符合条件的房间，请回复对应的开房消息、点击该消息按钮或填写房间名称。"
                if selection.code == "ambiguous"
                else "找不到符合条件的房间。"
            )
            await self._send_text(event, group_id, text, reply_id=source_message_id)
            _stop_event(event)
            return

        if parsed.action == "join":
            result = self.service.join(selection.room, user_id, user_name)
        elif parsed.action == "leave":
            result = self.service.leave(selection.room, user_id, user_name)
        elif parsed.action == "start":
            result = self.service.start(selection.room, user_id)
        else:
            result = self.service.end(selection.room, user_id)

        if result.room is None:
            await self._send_text(event, group_id, result.message, reply_id=source_message_id)
        else:
            await send_group_message(
                event,
                group_id,
                message_chain(
                    notification_text(parsed.action, result.room, result.message),
                    result.room.members,
                    reply_id=source_message_id,
                    actor_id=user_id,
                ),
            )
        _stop_event(event)

    async def _send_text(
        self,
        event,
        group_id: str,
        text: str,
        reply_id: str | None = None,
    ) -> None:
        await send_group_message(
            event,
            group_id,
            message_chain(text, reply_id=reply_id, include_members=False),
        )

    async def _room_timer_loop(self):
        while self._timer_stop is not None and not self._timer_stop.is_set():
            try:
                await self._process_room_timers()
            except Exception:
                logger.exception("排卡房间定时任务执行失败")
            try:
                await asyncio.wait_for(self._timer_stop.wait(), timeout=30)
            except asyncio.TimeoutError:
                continue

    async def _process_room_timers(self):
        if self.auto_disband_minutes <= 0 and self.reminder_minutes <= 0:
            return
        now = datetime.now(timezone.utc)
        for room in self.storage.list_waiting_rooms():
            created_at = _parse_timestamp(room.created_at)
            if created_at is None:
                continue
            age = now - created_at
            if self.auto_disband_minutes > 0 and age >= timedelta(minutes=self.auto_disband_minutes):
                code, ended = self.storage.end_room(
                    room.room_id,
                    expected_status=RoomStatus.WAITING,
                )
                if code == "ended" and ended is not None:
                    await self._send_scheduled_message(
                        ended,
                        f"⏰「{ended.title}」超过 {self.auto_disband_minutes} 分钟未发车，已自动解散。",
                    )
                continue
            if self.reminder_minutes <= 0 or age < timedelta(minutes=self.reminder_minutes):
                continue
            last_reminded_at = _parse_timestamp(room.last_reminded_at)
            if last_reminded_at is not None and now - last_reminded_at < timedelta(
                minutes=self.reminder_minutes
            ):
                continue
            reminded_at = now.isoformat()
            if not self.storage.claim_reminder(room.room_id, room.last_reminded_at, reminded_at):
                continue
            refreshed = self.storage.get_room(room.room_id)
            if refreshed is not None:
                await self._send_scheduled_message(
                    refreshed,
                    f"⏰「{refreshed.title}」已等待 {int(age.total_seconds() // 60)} 分钟，请尽快发车。",
                )

        if self.auto_disband_minutes <= 0:
            return
        for room in self.storage.list_started_rooms():
            started_at = _parse_timestamp(room.started_at)
            if started_at is None or now - started_at < timedelta(minutes=self.auto_disband_minutes):
                continue
            code, ended = self.storage.end_room(
                room.room_id,
                expected_status=RoomStatus.STARTED,
            )
            if code == "ended" and ended is not None:
                await self._send_scheduled_message(
                    ended,
                    f"⏰「{ended.title}」已发车超过 {self.auto_disband_minutes} 分钟，房间已自动结束。",
                )

    async def _send_scheduled_message(self, room, detail: str):
        if not room.message_origin:
            logger.warning(f"房间 #{room.room_id} 没有消息来源，无法发送定时通知")
            return
        sent = await send_context_message(
            self.context,
            room.message_origin,
            message_chain(
                notification_text("timer", room, detail),
                room.members,
            ),
        )
        if not sent:
            logger.warning(f"房间 #{room.room_id} 定时通知发送失败")

    def _operation_lock_for(self) -> asyncio.Lock:
        if self._operation_lock is None:
            self._operation_lock = asyncio.Lock()
        return self._operation_lock

    def _data_dir(self) -> Path:
        try:
            from astrbot.core.star.star_tools import StarTools

            path = Path(StarTools.get_data_dir(self.name))
            path.mkdir(parents=True, exist_ok=True)
            return path
        except Exception:
            pass
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            path = Path(get_astrbot_data_path()) / "plugin_data" / self.name
            path.mkdir(parents=True, exist_ok=True)
            return path
        except Exception:
            path = Path(__file__).resolve().parent / "data"
            path.mkdir(parents=True, exist_ok=True)
            return path

    async def terminate(self):
        if self._closing:
            return
        self._closing = True
        if self._timer_stop is not None:
            self._timer_stop.set()
        timer_task = self._timer_task
        if timer_task is not None:
            try:
                await asyncio.wait_for(timer_task, timeout=2)
            except asyncio.TimeoutError:
                timer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await timer_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("排卡定时任务退出时发生异常")
            finally:
                self._timer_task = None
        async with self._operation_lock_for():
            self.storage.close()


def _format_room_list(rooms) -> str:
    if not rooms:
        return "当前群没有正在排卡的房间。"
    return "当前群排卡房间：\n\n" + "\n\n".join(room_summary(room) for room in rooms)


def _group_id(event) -> str:
    getter = getattr(event, "get_group_id", None)
    value = getter() if callable(getter) else getattr(event, "group_id", "")
    return "" if value is None else str(value).strip()


def _sender_id(event) -> str:
    getter = getattr(event, "get_sender_id", None)
    value = getter() if callable(getter) else getattr(event, "sender_id", "")
    return "" if value is None else str(value).strip()


def _sender_name(event, fallback: str) -> str:
    getter = getattr(event, "get_sender_name", None)
    value = getter() if callable(getter) else getattr(event, "sender_name", "")
    value = "" if value is None else str(value).strip()
    return value or fallback


def _self_id(event) -> str:
    getter = getattr(event, "get_self_id", None)
    value = getter() if callable(getter) else getattr(event, "self_id", "")
    return "" if value is None else str(value).strip()


def _message_id(event) -> str | None:
    message_obj = getattr(event, "message_obj", None)
    value = getattr(message_obj, "message_id", None)
    if value is None:
        value = getattr(event, "message_id", None)
    return None if value is None else str(value)


def _message_origin(event) -> str | None:
    value = getattr(event, "unified_msg_origin", None)
    if value is None:
        value = getattr(event, "session", None)
    if value is None or callable(value):
        return None
    text = str(value).strip()
    return text or None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _starts_with_slash(event) -> bool:
    return extract_text(event).lstrip().startswith("/")


def _has_at_component(event) -> bool:
    getter = getattr(event, "get_messages", None)
    messages = getter() if callable(getter) else getattr(event, "message", [])
    if messages is None:
        return False
    self_id = _self_id(event)
    for component in messages:
        if not _is_at_component(component):
            continue
        target = _at_target(component)
        if not self_id or target == self_id:
            return True
    return False


def _is_at_component(component) -> bool:
    if isinstance(component, dict):
        component_type = component.get("type", "")
        data = component.get("data")
        if not component_type and isinstance(data, dict) and "qq" in data:
            return True
    else:
        component_type = getattr(component, "type", "")
    name = getattr(component_type, "name", component_type)
    return str(name).lower().split(".")[-1] == "at"


def _at_target(component) -> str:
    if isinstance(component, dict):
        data = component.get("data")
        if isinstance(data, dict):
            value = data.get("qq") or data.get("qq_id") or data.get("target")
        else:
            value = None
        return "" if value is None else str(value).strip()
    for name in ("qq", "qq_id", "target"):
        value = getattr(component, name, None)
        if value is not None:
            return str(value).strip()
    return ""


def _stop_event(event) -> None:
    stop = getattr(event, "stop_event", None)
    if callable(stop):
        stop()


def _int_config(
    config: dict[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    try:
        value = max(minimum, int(config.get(key, default)))
    except (TypeError, ValueError):
        value = default
    if maximum is not None:
        value = min(value, maximum)
    return value


def _bool_config(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default
