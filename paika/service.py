from __future__ import annotations

from dataclasses import dataclass

from .models import Room, RoomStatus, ServiceResult
from .storage import Storage


@dataclass(frozen=True)
class RoomSelection:
    room: Room | None
    code: str


class PaikaService:
    def __init__(self, storage: Storage, max_capacity: int = 20):
        self.storage = storage
        self.max_capacity = max_capacity

    def create_room(
        self,
        group_id: str,
        owner_id: str,
        owner_name: str,
        capacity: int,
        content: str,
        source_message_id: str | None,
        message_origin: str | None = None,
    ) -> ServiceResult:
        if capacity < 2:
            return ServiceResult(False, "invalid_capacity", message="人数至少要 2 人。")
        if capacity > self.max_capacity:
            return ServiceResult(
                False,
                "invalid_capacity",
                message=f"人数不能超过 {self.max_capacity} 人。",
            )
        code, room, conflict_id = self.storage.create_room(
            group_id,
            owner_id,
            owner_name,
            capacity,
            content.strip() or "未填写",
            source_message_id,
            message_origin,
        )
        if code == "already_in_room":
            return ServiceResult(
                False,
                code,
                room=room,
                message="你已经在当前群的其他房间中，请先下车或等待房间结束。",
            )
        return ServiceResult(True, "created", room=room)

    def list_rooms(self, group_id: str, include_ended: bool = False) -> list[Room]:
        return self.storage.list_rooms(group_id, include_ended)

    def select_room(
        self,
        group_id: str,
        room_id: int | None,
        reply_message_id: str | None,
        action: str,
        room_title: str | None = None,
    ) -> RoomSelection:
        if reply_message_id:
            room = self.storage.get_room_by_bot_message(group_id, reply_message_id)
            if room is not None:
                return RoomSelection(room, "selected")
        rooms = self._candidate_rooms(group_id, action)
        if room_title:
            titled = [room for room in rooms if room.title == room_title]
            if len(titled) == 1:
                return RoomSelection(titled[0], "selected")
            if len(titled) > 1:
                return RoomSelection(None, "ambiguous")
        if room_id is not None:
            room = self.storage.get_room(room_id)
            if room is None or room.group_id != group_id:
                return RoomSelection(None, "not_found")
            return RoomSelection(room, "selected")
        if len(rooms) == 1:
            return RoomSelection(rooms[0], "selected")
        if not rooms:
            return RoomSelection(None, "not_found")
        return RoomSelection(None, "ambiguous")

    def _candidate_rooms(self, group_id: str, action: str) -> list[Room]:
        rooms = self.storage.list_rooms(group_id)
        if action == "join":
            return [room for room in rooms if room.status is RoomStatus.WAITING]
        if action == "leave":
            return [room for room in rooms if room.status is not RoomStatus.ENDED]
        if action == "start":
            return [room for room in rooms if room.status is RoomStatus.WAITING]
        return [room for room in rooms if room.status is not RoomStatus.ENDED]

    def join(self, room: Room, user_id: str, display_name: str) -> ServiceResult:
        code, updated, conflict_id = self.storage.join_room(room.room_id, user_id, display_name)
        if updated is None:
            return ServiceResult(False, "not_found", message="房间不存在。")
        messages = {
            "joined": "已上车。",
            "auto_started": "已上车，人数已满，房间自动发车！",
            "already_member": "你已经在这辆车上了。",
            "already_in_other_room": "你已经在当前群的其他房间中，请先下车或等待房间结束。",
            "started": "房间已经发车，暂时不能再上车。",
            "ended": "房间已经结束，不能再上车。",
            "full": "房间人数已满，不能再上车。",
        }
        ok = code in {"joined", "auto_started", "already_member"}
        return ServiceResult(ok, code, updated, messages.get(code, "无法上车。"))

    def leave(self, room: Room, user_id: str, display_name: str) -> ServiceResult:
        code, updated = self.storage.leave_room(room.room_id, user_id)
        if updated is None:
            return ServiceResult(False, "not_found", message="房间不存在。")
        messages = {
            "left": "已下车。",
            "owner": "房主不能下车；如需解散房间，请使用 /结束。",
            "not_member": "你不在这辆车上。",
            "started": "房间已发车，成员状态已锁定，不能下车。",
            "ended": "房间已经结束，不能再下车。",
        }
        return ServiceResult(code == "left", code, updated, messages.get(code, "无法下车。"))

    def start(self, room: Room, user_id: str) -> ServiceResult:
        if room.owner_id != user_id or not _is_member(room, user_id):
            return ServiceResult(False, "forbidden", room, "只有仍在房间中的房主可以发车。")
        code, updated = self.storage.start_room(room.room_id)
        if updated is None:
            return ServiceResult(False, "not_found", message="房间不存在。")
        messages = {
            "started": "房主已发车！",
            "already_started": "房间已经发车了。",
            "ended": "房间已经结束，不能发车。",
        }
        return ServiceResult(code == "started", code, updated, messages.get(code, "无法发车。"))

    def end(self, room: Room, user_id: str) -> ServiceResult:
        if room.owner_id != user_id or not _is_member(room, user_id):
            return ServiceResult(False, "forbidden", room, "只有仍在房间中的房主可以结束房间。")
        code, updated = self.storage.end_room(room.room_id)
        if updated is None:
            return ServiceResult(False, "not_found", message="房间不存在。")
        messages = {
            "ended": "房间已结束。",
            "already_ended": "房间已经结束了。",
        }
        return ServiceResult(code == "ended", code, updated, messages.get(code, "无法结束房间。"))


def _is_member(room: Room, user_id: str) -> bool:
    return any(member.user_id == user_id for member in room.members)
