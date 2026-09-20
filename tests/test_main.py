import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from conftest import install_astrbot_stubs


class FakeBot:
    def __init__(self):
        self.calls = []
        self.next_message_id = 100

    async def call_action(self, action, **kwargs):
        self.calls.append((action, kwargs))
        if action == "send_group_msg":
            self.next_message_id += 1
            return {"data": {"message_id": self.next_message_id}}
        return {"status": "ok"}


class FakeContext:
    def __init__(self):
        self.sent = []

    async def send_message(self, origin, message_chain):
        self.sent.append((origin, message_chain.chain))
        return True


class FakeEvent:
    def __init__(
        self,
        text,
        user_id="u1",
        name="用户",
        message_id="10",
        group_id="g1",
        bot=None,
        messages=None,
    ):
        self.message_str = text
        self.user_id = user_id
        self.sender_name = name
        self.group_id = group_id
        self.unified_msg_origin = f"hiro:GroupMessage:{group_id}"
        self.message_obj = SimpleNamespace(
            message_id=message_id,
            raw_message={"post_type": "message"},
        )
        self.bot = bot or FakeBot()
        self.messages = messages or []
        self.stopped = False

    def get_group_id(self):
        return self.group_id

    def get_sender_id(self):
        return self.user_id

    def get_sender_name(self):
        return self.sender_name

    def get_message_str(self):
        return self.message_str

    def get_messages(self):
        return self.messages

    def get_self_id(self):
        return "bot-1"

    def stop_event(self):
        self.stopped = True


def test_create_and_join_via_main(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    plugin = main.PaikaPlugin(object(), {"reaction_enabled": True})
    owner_event = FakeEvent("排卡 2 周末开黑")
    asyncio.run(plugin.command_create_room(owner_event))

    room = plugin.service.list_rooms("g1")[0]
    assert room.content == "周末开黑"
    assert room.bot_message_id == "101"
    assert owner_event.stopped is True

    join_event = FakeEvent("上车", user_id="u2", name="队友", message_id="11", bot=FakeBot())
    asyncio.run(plugin.command_join_room(join_event))
    assert plugin.service.storage.get_room(room.room_id).status.value == "started"
    assert join_event.stopped is True


def test_reply_message_selects_the_right_room(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    plugin = main.PaikaPlugin(object(), {"reaction_enabled": False})
    owner_event = FakeEvent("排卡 3 房间A")
    asyncio.run(plugin.command_create_room(owner_event))
    room = plugin.service.list_rooms("g1")[0]

    reply = SimpleNamespace(type="Reply", id=room.bot_message_id)
    join_event = FakeEvent("上车", user_id="u2", name="队友", messages=[reply])
    asyncio.run(plugin.on_message(join_event))
    updated = plugin.service.storage.get_room(room.room_id)
    assert [member.user_id for member in updated.members] == ["u1", "u2"]


def test_reaction_notice_joins_but_ignores_bot_reaction(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    plugin = main.PaikaPlugin(object(), {"reaction_enabled": True})
    owner_event = FakeEvent("排卡 3 开黑")
    asyncio.run(plugin.command_create_room(owner_event))
    room = plugin.service.list_rooms("g1")[0]

    bot_event = FakeEvent("", user_id="bot-1", bot=FakeBot())
    bot_event.message_obj.raw_message = {
        "post_type": "notice",
        "notice_type": "group_msg_emoji_like",
        "group_id": "g1",
        "message_id": room.bot_message_id,
        "user_id": "bot-1",
        "likes": [{"emoji_id": "76", "count": 1}],
        "is_add": True,
    }
    asyncio.run(plugin.on_reaction(bot_event))
    assert len(plugin.service.storage.get_room(room.room_id).members) == 1

    user_event = FakeEvent("", user_id="u2", name="队友", bot=FakeBot())
    user_event.message_obj.raw_message = {
        "post_type": "notice",
        "notice_type": "group_msg_emoji_like",
        "group_id": "g1",
        "message_id": room.bot_message_id,
        "user_id": "u2",
        "likes": [{"emoji_id": "76", "count": 1}],
        "is_add": True,
    }
    asyncio.run(plugin.on_reaction(user_event))
    updated = plugin.service.storage.get_room(room.room_id)
    assert [member.user_id for member in updated.members] == ["u1", "u2"]
    assert user_event.stopped is True


def test_llm_tool_creates_room(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    plugin = main.PaikaPlugin(object(), {"reaction_enabled": False})
    event = FakeEvent("", message_id="20")
    asyncio.run(plugin.llm_create_room(event, 2, "自然语言开黑"))

    room = plugin.service.list_rooms("g1")[0]
    assert room.content == "自然语言开黑"
    assert event.stopped is True


def test_bare_command_is_left_for_llm_when_native_commands_exist(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    plugin = main.PaikaPlugin(object())
    event = FakeEvent("排卡 2 测试")
    asyncio.run(plugin.on_message(event))

    assert event.stopped is False
    assert plugin.service.list_rooms("g1") == []


def test_unknown_message_is_left_alone(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    plugin = main.PaikaPlugin(object())
    event = FakeEvent("今晚吃什么")
    asyncio.run(plugin.on_message(event))
    assert event.stopped is False
    assert plugin.service.list_rooms("g1") == []


def test_reaction_duplicate_sends_feedback(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    plugin = main.PaikaPlugin(object(), {"reaction_enabled": True})
    owner_event = FakeEvent("排卡 3 开黑")
    asyncio.run(plugin.command_create_room(owner_event))
    room = plugin.service.list_rooms("g1")[0]

    def reaction_event(user_id):
        event = FakeEvent("", user_id=user_id, name="队友", bot=FakeBot())
        event.message_obj.raw_message = {
            "post_type": "notice",
            "notice_type": "group_msg_emoji_like",
            "group_id": "g1",
            "message_id": room.bot_message_id,
            "user_id": user_id,
            "likes": [{"emoji_id": "76", "count": 1}],
            "is_add": True,
        }
        return event

    first = reaction_event("u2")
    asyncio.run(plugin.on_reaction(first))
    duplicate = reaction_event("u2")
    asyncio.run(plugin.on_reaction(duplicate))

    assert duplicate.stopped is True
    assert any(call[0] == "send_group_msg" for call in duplicate.bot.calls)


def test_room_timer_reminds_once_and_dissolves(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    context = FakeContext()
    plugin = main.PaikaPlugin(
        context,
        {"reaction_enabled": False, "auto_disband_minutes": 15, "reminder_minutes": 5},
    )
    owner_event = FakeEvent("排卡 3 开黑")
    asyncio.run(plugin.command_create_room(owner_event))
    room = plugin.service.list_rooms("g1")[0]
    old = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    plugin.storage._connection.execute(
        "UPDATE rooms SET created_at = ? WHERE id = ?", (old, room.room_id)
    )
    plugin.storage._connection.commit()

    asyncio.run(plugin._process_room_timers())
    asyncio.run(plugin._process_room_timers())
    assert len(context.sent) == 1

    plugin.auto_disband_minutes = 1
    old = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    plugin.storage._connection.execute(
        "UPDATE rooms SET created_at = ? WHERE id = ?", (old, room.room_id)
    )
    plugin.storage._connection.commit()
    asyncio.run(plugin._process_room_timers())
    assert plugin.service.storage.get_room(room.room_id).status.value == "ended"
    assert len(context.sent) == 2


def test_started_room_auto_ends_after_timeout(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    context = FakeContext()
    plugin = main.PaikaPlugin(
        context,
        {"reaction_enabled": False, "auto_disband_minutes": 15, "reminder_minutes": 0},
    )
    asyncio.run(plugin.command_create_room(FakeEvent("排卡 2 周末开黑")))
    asyncio.run(plugin.command_join_room(FakeEvent("上车", user_id="u2", name="队友")))
    room = plugin.service.list_rooms("g1")[0]
    old = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
    plugin.storage._connection.execute(
        "UPDATE rooms SET started_at = ? WHERE id = ?", (old, room.room_id)
    )
    plugin.storage._connection.commit()

    asyncio.run(plugin._process_room_timers())
    assert plugin.storage.get_room(room.room_id).status.value == "ended"
    assert len(context.sent) == 1


def test_failed_room_message_ends_created_room(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    class FailingBot:
        async def call_action(self, action, **kwargs):
            raise RuntimeError("send failed")

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    plugin = main.PaikaPlugin(object(), {"reaction_enabled": False})
    event = FakeEvent("排卡 3 发送失败", bot=FailingBot())
    asyncio.run(plugin.command_create_room(event))

    rooms = plugin.service.storage.list_rooms("g1", include_ended=True)
    assert len(rooms) == 1
    assert rooms[0].status.value == "ended"
    assert rooms[0].bot_message_id is None


def test_config_values_are_normalized(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    plugin = main.PaikaPlugin(
        object(),
        {
            "default_capacity": 50,
            "max_capacity": 20,
            "reaction_enabled": "false",
            "auto_disband_minutes": 9999,
        },
    )
    assert plugin.default_capacity == 20
    assert plugin.max_capacity == 20
    assert plugin.reaction_enabled is False
    assert plugin.auto_disband_minutes == 1440


def test_at_filter_only_matches_the_bot(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    plugin = main.PaikaPlugin(object())
    bot_at = SimpleNamespace(type=SimpleNamespace(name="At"), qq="bot-1")
    other_at = SimpleNamespace(type=SimpleNamespace(name="At"), qq="other")
    event = FakeEvent("上车", messages=[other_at])
    assert main._has_at_component(event) is False
    event.messages = [bot_at]
    assert main._has_at_component(event) is True


def test_terminate_is_idempotent(tmp_path, monkeypatch):
    install_astrbot_stubs(monkeypatch)
    import main

    monkeypatch.setattr(main.PaikaPlugin, "_data_dir", lambda self: tmp_path)
    plugin = main.PaikaPlugin(object())
    asyncio.run(plugin.terminate())
    asyncio.run(plugin.terminate())
