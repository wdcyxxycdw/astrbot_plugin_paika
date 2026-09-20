import sqlite3

from paika.storage import Storage


def test_existing_database_gets_timer_columns(tmp_path):
    path = tmp_path / "paika.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            source_message_id TEXT,
            bot_message_id TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT
        );
        CREATE TABLE room_members (
            room_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            PRIMARY KEY (room_id, user_id)
        );
        """
    )
    connection.commit()
    connection.close()

    storage = Storage(path)
    columns = {
        row[1]
        for row in storage._connection.execute("PRAGMA table_info(rooms)").fetchall()
    }
    assert {"message_origin", "last_reminded_at"} <= columns


def test_claim_reminder_is_idempotent(tmp_path):
    storage = Storage(tmp_path / "paika.db")
    code, room, _ = storage.create_room(
        "g1", "u1", "用户", 3, "测试", "source", "hiro:GroupMessage:g1"
    )
    assert code == "created"
    assert room is not None

    assert storage.claim_reminder(room.room_id, None, "2026-01-01T00:05:00+00:00") is True
    assert storage.claim_reminder(room.room_id, None, "2026-01-01T00:10:00+00:00") is False
    assert storage.claim_reminder(
        room.room_id,
        "2026-01-01T00:05:00+00:00",
        "2026-01-01T00:10:00+00:00",
    ) is True


def test_old_database_migration_is_safe_for_two_connections(tmp_path):
    import threading

    path = tmp_path / "paika.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            source_message_id TEXT,
            bot_message_id TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT
        );
        CREATE TABLE room_members (
            room_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            PRIMARY KEY (room_id, user_id)
        );
        """
    )
    connection.commit()
    connection.close()

    stores = []
    errors = []

    def open_storage():
        try:
            stores.append(Storage(path))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=open_storage) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for storage in stores:
        storage.close()

    assert errors == []
    assert len(stores) == 2
