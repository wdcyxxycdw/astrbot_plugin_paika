from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RoomStatus(str, Enum):
    WAITING = "waiting"
    STARTED = "started"
    ENDED = "ended"

    @property
    def label(self) -> str:
        return {
            RoomStatus.WAITING: "等待中",
            RoomStatus.STARTED: "已发车",
            RoomStatus.ENDED: "已结束",
        }[self]


@dataclass(frozen=True)
class Member:
    user_id: str
    display_name: str
    joined_at: str


@dataclass(frozen=True)
class Room:
    room_id: int
    group_id: str
    owner_id: str
    owner_name: str
    capacity: int
    content: str
    status: RoomStatus
    source_message_id: str | None
    bot_message_id: str | None
    created_at: str
    started_at: str | None
    ended_at: str | None
    message_origin: str | None = None
    last_reminded_at: str | None = None
    members: tuple[Member, ...] = ()

    @property
    def title(self) -> str:
        return self.content

    @property
    def member_count(self) -> int:
        return len(self.members)


@dataclass(frozen=True)
class ServiceResult:
    ok: bool
    code: str
    room: Room | None = None
    message: str = ""
