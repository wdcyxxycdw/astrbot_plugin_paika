from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

from .models import Member, Room, RoomStatus

T = TypeVar("T")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            self.path,
            check_same_thread=False,
            timeout=10,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=10000")
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS rooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    owner_name TEXT NOT NULL,
                    capacity INTEGER NOT NULL CHECK (capacity > 1),
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'waiting',
                    source_message_id TEXT,
                    bot_message_id TEXT,
                    message_origin TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    last_reminded_at TEXT
                );
                CREATE TABLE IF NOT EXISTS room_members (
                    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY (room_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_rooms_group_status
                    ON rooms(group_id, status);
                CREATE INDEX IF NOT EXISTS idx_rooms_bot_message
                    ON rooms(bot_message_id);
                CREATE INDEX IF NOT EXISTS idx_members_user
                    ON room_members(user_id);
                """
            )
            self._migrate_rooms()

    def _migrate_rooms(self) -> None:
        columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(rooms)").fetchall()
        }
        for column in ("message_origin", "last_reminded_at"):
            if column in columns:
                continue
            try:
                self._connection.execute(f"ALTER TABLE rooms ADD COLUMN {column} TEXT")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

    def _write(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                result = operation(self._connection)
            except Exception:
                self._connection.rollback()
                raise
            self._connection.commit()
            return result

    def _read(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        with self._lock:
            return operation(self._connection)

    def create_room(
        self,
        group_id: str,
        owner_id: str,
        owner_name: str,
        capacity: int,
        content: str,
        source_message_id: str | None,
        message_origin: str | None = None,
    ) -> tuple[str, Room | None, int | None]:
        now = _now()

        def operation(connection: sqlite3.Connection) -> tuple[str, Room | None, int | None]:
            conflict_id = self._find_active_room_id(connection, group_id, owner_id)
            if conflict_id is not None:
                return "already_in_room", self._load_room(connection, conflict_id), conflict_id
            cursor = connection.execute(
                """
                INSERT INTO rooms (
                    group_id, owner_id, owner_name, capacity, content,
                    status, source_message_id, message_origin, created_at
                ) VALUES (?, ?, ?, ?, ?, 'waiting', ?, ?, ?)
                """ ,
                (
                    group_id,
                    owner_id,
                    owner_name,
                    capacity,
                    content,
                    source_message_id,
                    message_origin,
                    now,
                ),
            )
            room_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO room_members (room_id, user_id, display_name, joined_at)
                VALUES (?, ?, ?, ?)
                """,
                (room_id, owner_id, owner_name, now),
            )
            return "created", self._load_room(connection, room_id), None

        return self._write(operation)

    def set_bot_message_id(self, room_id: int, message_id: str) -> None:
        self._write(
            lambda connection: connection.execute(
                "UPDATE rooms SET bot_message_id = ? WHERE id = ?",
                (message_id, room_id),
            )
        )

    def get_room(self, room_id: int) -> Room | None:
        return self._read(lambda connection: self._load_room_or_none(connection, room_id))

    def get_room_by_bot_message(self, group_id: str, message_id: str) -> Room | None:
        def operation(connection: sqlite3.Connection) -> Room | None:
            row = connection.execute(
                "SELECT id FROM rooms WHERE group_id = ? AND bot_message_id = ?",
                (group_id, str(message_id)),
            ).fetchone()
            return None if row is None else self._load_room(connection, int(row["id"]))

        return self._read(operation)

    def get_active_room_for_user(self, group_id: str, user_id: str) -> Room | None:
        def operation(connection: sqlite3.Connection) -> Room | None:
            room_id = self._find_active_room_id(connection, group_id, user_id)
            return None if room_id is None else self._load_room(connection, room_id)

        return self._read(operation)

    def list_rooms(self, group_id: str, include_ended: bool = False) -> list[Room]:
        def operation(connection: sqlite3.Connection) -> list[Room]:
            if include_ended:
                rows = connection.execute(
                    "SELECT id FROM rooms WHERE group_id = ? ORDER BY id DESC",
                    (group_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id FROM rooms
                    WHERE group_id = ? AND status != 'ended'
                    ORDER BY id DESC
                    """,
                    (group_id,),
                ).fetchall()
            return [self._load_room(connection, int(row["id"])) for row in rows]

        return self._read(operation)

    def list_waiting_rooms(self) -> list[Room]:
        def operation(connection: sqlite3.Connection) -> list[Room]:
            rows = connection.execute(
                "SELECT id FROM rooms WHERE status = 'waiting' ORDER BY id",
            ).fetchall()
            return [self._load_room(connection, int(row["id"])) for row in rows]

        return self._read(operation)

    def list_started_rooms(self) -> list[Room]:
        def operation(connection: sqlite3.Connection) -> list[Room]:
            rows = connection.execute(
                "SELECT id FROM rooms WHERE status = 'started' ORDER BY id",
            ).fetchall()
            return [self._load_room(connection, int(row["id"])) for row in rows]

        return self._read(operation)

    def claim_reminder(
        self,
        room_id: int,
        expected_last_reminded_at: str | None,
        reminded_at: str,
    ) -> bool:
        def operation(connection: sqlite3.Connection) -> bool:
            if expected_last_reminded_at is None:
                cursor = connection.execute(
                    """
                    UPDATE rooms
                    SET last_reminded_at = ?
                    WHERE id = ? AND status = 'waiting' AND last_reminded_at IS NULL
                    """,
                    (reminded_at, room_id),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE rooms
                    SET last_reminded_at = ?
                    WHERE id = ? AND status = 'waiting' AND last_reminded_at = ?
                    """,
                    (reminded_at, room_id, expected_last_reminded_at),
                )
            return cursor.rowcount == 1

        return self._write(operation)

    def join_room(
        self,
        room_id: int,
        user_id: str,
        display_name: str,
    ) -> tuple[str, Room | None, int | None]:
        now = _now()

        def operation(connection: sqlite3.Connection) -> tuple[str, Room | None, int | None]:
            room = self._load_room_or_none(connection, room_id)
            if room is None:
                return "not_found", None, None
            if room.status is RoomStatus.ENDED:
                return "ended", room, None
            if room.status is RoomStatus.STARTED:
                return "started", room, None
            existing = connection.execute(
                "SELECT 1 FROM room_members WHERE room_id = ? AND user_id = ?",
                (room_id, user_id),
            ).fetchone()
            if existing is not None:
                return "already_member", room, None
            conflict_id = self._find_active_room_id(
                connection,
                room.group_id,
                user_id,
                exclude_room_id=room_id,
            )
            if conflict_id is not None:
                return "already_in_other_room", room, conflict_id
            if room.member_count >= room.capacity:
                return "full", room, None
            connection.execute(
                """
                INSERT INTO room_members (room_id, user_id, display_name, joined_at)
                VALUES (?, ?, ?, ?)
                """,
                (room_id, user_id, display_name, now),
            )
            new_count = connection.execute(
                "SELECT COUNT(*) FROM room_members WHERE room_id = ?", (room_id,)
            ).fetchone()[0]
            code = "joined"
            if new_count >= room.capacity:
                connection.execute(
                    """
                    UPDATE rooms
                    SET status = 'started', started_at = ?
                    WHERE id = ? AND status = 'waiting'
                    """,
                    (now, room_id),
                )
                code = "auto_started"
            return code, self._load_room(connection, room_id), None

        return self._write(operation)

    def leave_room(self, room_id: int, user_id: str) -> tuple[str, Room | None]:
        def operation(connection: sqlite3.Connection) -> tuple[str, Room | None]:
            room = self._load_room_or_none(connection, room_id)
            if room is None:
                return "not_found", None
            if room.status is RoomStatus.ENDED:
                return "ended", room
            if room.status is RoomStatus.STARTED:
                return "started", room
            if user_id == room.owner_id:
                return "owner", room
            deleted = connection.execute(
                "DELETE FROM room_members WHERE room_id = ? AND user_id = ?",
                (room_id, user_id),
            ).rowcount
            if not deleted:
                return "not_member", room
            return "left", self._load_room(connection, room_id)

        return self._write(operation)

    def start_room(self, room_id: int) -> tuple[str, Room | None]:
        now = _now()

        def operation(connection: sqlite3.Connection) -> tuple[str, Room | None]:
            room = self._load_room_or_none(connection, room_id)
            if room is None:
                return "not_found", None
            if room.status is RoomStatus.ENDED:
                return "ended", room
            if room.status is RoomStatus.STARTED:
                return "already_started", room
            connection.execute(
                "UPDATE rooms SET status = 'started', started_at = ? WHERE id = ?",
                (now, room_id),
            )
            return "started", self._load_room(connection, room_id)

        return self._write(operation)

    def end_room(
        self,
        room_id: int,
        expected_status: RoomStatus | None = None,
    ) -> tuple[str, Room | None]:
        now = _now()

        def operation(connection: sqlite3.Connection) -> tuple[str, Room | None]:
            room = self._load_room_or_none(connection, room_id)
            if room is None:
                return "not_found", None
            if room.status is RoomStatus.ENDED:
                return "already_ended", room
            if expected_status is not None and room.status is not expected_status:
                return "state_changed", room
            connection.execute(
                "UPDATE rooms SET status = 'ended', ended_at = ? WHERE id = ?",
                (now, room_id),
            )
            return "ended", self._load_room(connection, room_id)

        return self._write(operation)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def _find_active_room_id(
        self,
        connection: sqlite3.Connection,
        group_id: str,
        user_id: str,
        exclude_room_id: int | None = None,
    ) -> int | None:
        if exclude_room_id is None:
            row = connection.execute(
                """
                SELECT r.id
                FROM rooms AS r
                JOIN room_members AS m ON m.room_id = r.id
                WHERE r.group_id = ? AND r.status != 'ended' AND m.user_id = ?
                ORDER BY r.id LIMIT 1
                """,
                (group_id, user_id),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT r.id
                FROM rooms AS r
                JOIN room_members AS m ON m.room_id = r.id
                WHERE r.group_id = ? AND r.status != 'ended'
                  AND m.user_id = ? AND r.id != ?
                ORDER BY r.id LIMIT 1
                """,
                (group_id, user_id, exclude_room_id),
            ).fetchone()
        return None if row is None else int(row["id"])

    def _load_room_or_none(
        self,
        connection: sqlite3.Connection,
        room_id: int,
    ) -> Room | None:
        row = connection.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
        return None if row is None else self._room_from_row(connection, row)

    def _load_room(self, connection: sqlite3.Connection, room_id: int) -> Room:
        room = self._load_room_or_none(connection, room_id)
        if room is None:
            raise LookupError(f"room {room_id} does not exist")
        return room

    def _room_from_row(self, connection: sqlite3.Connection, row: sqlite3.Row) -> Room:
        members = connection.execute(
            """
            SELECT user_id, display_name, joined_at
            FROM room_members WHERE room_id = ? ORDER BY joined_at, user_id
            """,
            (row["id"],),
        ).fetchall()
        return Room(
            room_id=int(row["id"]),
            group_id=str(row["group_id"]),
            owner_id=str(row["owner_id"]),
            owner_name=str(row["owner_name"]),
            capacity=int(row["capacity"]),
            content=str(row["content"]),
            status=RoomStatus(str(row["status"])),
            source_message_id=(
                None if row["source_message_id"] is None else str(row["source_message_id"])
            ),
            bot_message_id=(
                None if row["bot_message_id"] is None else str(row["bot_message_id"])
            ),
            created_at=str(row["created_at"]),
            started_at=None if row["started_at"] is None else str(row["started_at"]),
            ended_at=None if row["ended_at"] is None else str(row["ended_at"]),
            message_origin=(
                None if row["message_origin"] is None else str(row["message_origin"])
            ),
            last_reminded_at=(
                None if row["last_reminded_at"] is None else str(row["last_reminded_at"])
            ),
            members=tuple(
                Member(
                    user_id=str(member["user_id"]),
                    display_name=str(member["display_name"]),
                    joined_at=str(member["joined_at"]),
                )
                for member in members
            ),
        )
