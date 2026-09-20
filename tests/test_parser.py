from paika.parser import extract_reply_message_id, parse_text


class Reply:
    type = "Reply"

    def __init__(self, message_id):
        self.id = message_id


def test_parse_create_with_capacity_and_content():
    parsed = parse_text("/排卡 4 今晚打本")
    assert parsed.action == "create"
    assert parsed.capacity == 4
    assert parsed.content == "今晚打本"


def test_parse_plain_action_and_reply():
    assert parse_text("上车").action == "join"
    assert parse_text("发车 12").room_id == 12
    event = type("Event", (), {"get_messages": lambda self: [Reply("99")]})()
    assert extract_reply_message_id(event) == "99"


def test_parse_command_after_leading_mention():
    parsed = parse_text("[At:123456] /排卡 4 今晚打本")
    assert parsed.action == "create"
    assert parsed.capacity == 4
    assert parsed.content == "今晚打本"


def test_parse_room_title_selector():
    parsed = parse_text("/上车 周末 开黑")
    assert parsed.room_id is None
    assert parsed.room_title == "周末 开黑"


def test_reply_dict_message_component_is_supported():
    event = type(
        "Event",
        (),
        {"get_messages": lambda self: [{"type": "Reply", "data": {"id": "101"}}]},
    )()
    assert extract_reply_message_id(event) == "101"


def test_reference_text_is_not_parsed_as_current_command():
    assert parse_text("普通聊天\n上车") is None
