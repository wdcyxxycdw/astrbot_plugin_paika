from paika.reactions import parse_reaction_notice, set_message_reaction


def test_parse_napcat_reaction_notice():
    notice = parse_reaction_notice(
        {
            "post_type": "notice",
            "notice_type": "group_msg_emoji_like",
            "group_id": 123,
            "message_id": 456,
            "user_id": 789,
            "likes": [{"emoji_id": "76", "count": 1}],
            "is_add": True,
        },
        "76",
    )
    assert notice is not None
    assert notice.group_id == "123"
    assert notice.message_id == "456"
    assert notice.user_id == "789"
    assert notice.is_add is True


def test_parse_removed_reaction_and_ignore_wrong_emoji():
    raw = {
        "post_type": "notice",
        "notice_type": "group_msg_emoji_like",
        "group_id": "g",
        "message_id": "m",
        "user_id": "u",
        "emoji_likes": [{"emojiId": "76", "count": 0}],
        "isAdd": False,
    }
    assert parse_reaction_notice(raw, "76").is_add is False
    assert parse_reaction_notice(raw, "77") is None


def test_unknown_reaction_direction_is_ignored():
    raw = {
        "post_type": "notice",
        "notice_type": "group_msg_emoji_like",
        "group_id": "g",
        "message_id": "m",
        "user_id": "u",
        "likes": [{"emoji_id": "76"}],
    }
    assert parse_reaction_notice(raw, "76") is None


def test_set_reaction_retries_without_optional_type():
    import asyncio

    class Bot:
        def __init__(self):
            self.calls = []

        async def call_action(self, action, **kwargs):
            self.calls.append((action, kwargs))
            if "emoji_type" in kwargs:
                raise RuntimeError("unsupported optional field")

    bot = Bot()
    event = type("Event", (), {"bot": bot})()
    assert asyncio.run(set_message_reaction(event, "12", "76", 1)) is True
    assert len(bot.calls) == 2
    assert "emoji_type" not in bot.calls[-1][1]
