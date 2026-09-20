import asyncio
from types import SimpleNamespace

from conftest import install_astrbot_stubs

from paika.models import Member


def test_room_text_uses_title_and_explains_controls(monkeypatch):
    install_astrbot_stubs(monkeypatch)
    from paika.models import Room, RoomStatus
    from paika.transport import room_creation_text, room_summary

    room = Room(
        room_id=7,
        group_id="g",
        owner_id="u1",
        owner_name="甲",
        capacity=3,
        content="周末开黑",
        status=RoomStatus.WAITING,
        source_message_id=None,
        bot_message_id=None,
        created_at="now",
        started_at=None,
        ended_at=None,
    )
    summary = room_summary(room)
    creation = room_creation_text(room)
    assert "周末开黑" in summary
    assert "#7" not in summary
    assert "点击本消息下方表情按钮" in creation
    assert "取消点击" in creation
    assert "/结束" in creation


def test_message_chain_places_mentions_inside_member_section(monkeypatch):
    install_astrbot_stubs(monkeypatch)
    from paika.transport import message_chain

    chain = message_chain(
        "🎴 房间标题",
        [Member("u1", "甲", "now"), Member("u2", "乙", "later")],
    )

    assert [component.type for component in chain] == ["Plain", "At", "At", "Plain"]
    assert "房间成员" in chain[0].text
    assert chain[1].qq == "u1"
    assert chain[2].qq == "u2"


def test_message_chain_mentions_actor_before_action(monkeypatch):
    install_astrbot_stubs(monkeypatch)
    from paika.transport import message_chain

    chain = message_chain("已上车。", actor_id="u9")
    assert [component.type for component in chain[:2]] == ["At", "Plain"]
    assert chain[0].qq == "u9"
    assert "已上车" in chain[1].text


def test_message_chain_can_skip_members_for_error_text(monkeypatch):
    install_astrbot_stubs(monkeypatch)
    from paika.transport import message_chain

    chain = message_chain("操作失败", include_members=False)
    assert len(chain) == 1
    assert chain[0].text == "操作失败"


def test_event_send_fallback_returns_message_id(monkeypatch):
    install_astrbot_stubs(monkeypatch)
    from paika.transport import send_group_message

    class Event:
        bot = object()

        async def send(self, _message_chain):
            return SimpleNamespace(message_id=321)

    result = asyncio.run(send_group_message(Event(), "g1", []))
    assert result.sent is True
    assert result.message_id == "321"


def test_group_message_send_failure_response_is_reported(monkeypatch):
    install_astrbot_stubs(monkeypatch)
    from paika.transport import send_group_message

    class Bot:
        async def call_action(self, _action, **_kwargs):
            return {"status": "failed", "retcode": 100}

    event = SimpleNamespace(bot=Bot())
    result = asyncio.run(send_group_message(event, "g1", []))
    assert result.sent is False


def test_group_message_send_failure_is_reported(monkeypatch):
    install_astrbot_stubs(monkeypatch)
    from paika.transport import send_group_message

    class Event:
        bot = object()

        async def send(self, _message_chain):
            raise RuntimeError("send failed")

    result = asyncio.run(send_group_message(Event(), "g1", []))
    assert result.sent is False
    assert result.message_id is None
