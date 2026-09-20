from paika.models import RoomStatus
from paika.service import PaikaService
from paika.storage import Storage


def test_one_active_room_per_user_and_group_isolation(tmp_path):
    storage = Storage(tmp_path / "paika.db")
    service = PaikaService(storage, max_capacity=5)

    first = service.create_room("g1", "u1", "甲", 3, "副本", "m1")
    conflict = service.create_room("g1", "u1", "甲", 3, "竞技场", "m2")
    second = service.create_room("g1", "u2", "乙", 3, "竞技场", "m3")
    other_group = service.create_room("g2", "u1", "甲", 3, "副本", "m4")
    assert first.ok and not conflict.ok and second.ok and other_group.ok

    assert service.join(first.room, "u3", "丙").ok
    assert service.join(second.room, "u3", "丙").code == "already_in_other_room"
    assert len(service.list_rooms("g1")) == 2
    assert len(service.list_rooms("g2")) == 1
    assert service.select_room("g2", first.room.room_id, None, "join").code == "not_found"


def test_membership_is_released_after_leave_and_end(tmp_path):
    service = PaikaService(Storage(tmp_path / "paika.db"), max_capacity=5)
    first = service.create_room("g", "owner", "房主", 3, "一", "m1")
    second = service.create_room("g", "other", "另一位", 3, "二", "m2")

    assert service.join(first.room, "u1", "用户").ok
    assert service.join(second.room, "u1", "用户").code == "already_in_other_room"
    assert service.leave(first.room, "u1", "用户").code == "left"
    assert service.join(second.room, "u1", "用户").ok
    assert service.end(second.room, "other").code == "ended"
    third = service.create_room("g", "u3", "第三位", 3, "三", "m3")
    assert service.join(third.room, "u1", "用户").ok


def test_title_selection_and_reply_precedence(tmp_path):
    service = PaikaService(Storage(tmp_path / "paika.db"), max_capacity=5)
    first = service.create_room("g", "u1", "甲", 3, "周末 开黑", "m1")
    second = service.create_room("g", "u2", "乙", 3, "副本", "m2")
    service.storage.set_bot_message_id(first.room.room_id, "message-1")
    service.storage.set_bot_message_id(second.room.room_id, "message-2")

    assert service.select_room("g", None, None, "join", "副本").room.room_id == second.room.room_id
    assert service.select_room("g", None, "message-1", "join", "副本").room.room_id == first.room.room_id


def test_same_title_is_ambiguous(tmp_path):
    service = PaikaService(Storage(tmp_path / "paika.db"), max_capacity=5)
    first = service.create_room("g", "u1", "甲", 3, "同名", "m1")
    second = service.create_room("g", "u2", "乙", 3, "同名", "m2")
    selection = service.select_room("g", None, None, "join", "同名")
    assert first.ok and second.ok
    assert selection.code == "ambiguous"


def test_full_room_auto_starts_and_blocks_more_members(tmp_path):
    service = PaikaService(Storage(tmp_path / "paika.db"), max_capacity=5)
    created = service.create_room("g", "owner", "房主", 2, "开黑", "m")

    joined = service.join(created.room, "u2", "队友")
    assert joined.code == "auto_started"
    assert joined.room.status is RoomStatus.STARTED
    assert service.join(joined.room, "u3", "迟到").code == "started"


def test_owner_permissions_and_leave(tmp_path):
    service = PaikaService(Storage(tmp_path / "paika.db"), max_capacity=5)
    created = service.create_room("g", "owner", "房主", 3, "开黑", "m")

    assert service.start(created.room, "u2").code == "forbidden"
    assert service.start(created.room, "owner").code == "started"
    started = service.storage.get_room(created.room.room_id)
    assert service.leave(started, "owner", "房主").code == "started"
    assert service.end(started, "owner").code == "ended"
    assert service.join(started, "u3", "迟到").code == "ended"




def test_database_recovers_after_reopen(tmp_path):
    path = tmp_path / "paika.db"
    storage = Storage(path)
    service = PaikaService(storage)
    created = service.create_room("g", "u", "用户", 4, "内容", "m")
    storage.close()

    reopened = Storage(path)
    room = reopened.get_room(created.room.room_id)
    assert room is not None
    assert room.members[0].user_id == "u"


def test_waiting_owner_cannot_leave_or_create_another_room(tmp_path):
    service = PaikaService(Storage(tmp_path / "paika.db"), max_capacity=5)
    created = service.create_room("g", "owner", "房主", 3, "开黑", "m")

    left = service.leave(created.room, "owner", "房主")
    assert left.code == "owner"
    current = service.storage.get_room(created.room.room_id)
    assert [member.user_id for member in current.members] == ["owner"]
    assert service.create_room("g", "owner", "房主", 3, "另一个", "m2").code == "already_in_room"


def test_timer_end_requires_expected_status(tmp_path):
    storage = Storage(tmp_path / "paika.db")
    code, room, _ = storage.create_room("g", "owner", "房主", 3, "开黑", "m")
    assert code == "created"
    assert room is not None

    assert storage.start_room(room.room_id)[0] == "started"
    state_changed, unchanged = storage.end_room(room.room_id, RoomStatus.WAITING)
    assert state_changed == "state_changed"
    assert unchanged.status is RoomStatus.STARTED
