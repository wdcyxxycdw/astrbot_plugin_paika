import sys
import types


class FakeFilter:
    class EventMessageType:
        GROUP_MESSAGE = "group"
        ALL = "all"

    class PlatformAdapterType:
        AIOCQHTTP = "aiocqhttp"

    @staticmethod
    def event_message_type(*_args, **_kwargs):
        return lambda function: function

    @staticmethod
    def platform_adapter_type(*_args, **_kwargs):
        return lambda function: function

    @staticmethod
    def command(*_args, **_kwargs):
        return lambda function: function

    @staticmethod
    def llm_tool(*_args, **_kwargs):
        return lambda function: function


def install_astrbot_stubs(monkeypatch):
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")
    components = types.ModuleType("astrbot.api.message_components")

    class FakeStar:
        def __init__(self, context):
            self.context = context
            self.name = "paika"

    def register(*_args, **_kwargs):
        return lambda cls: cls

    class Plain:
        type = "Plain"

        def __init__(self, text):
            self.text = text

        def toDict(self):
            return {"type": "text", "data": {"text": self.text}}

    class At:
        type = "At"

        def __init__(self, qq):
            self.qq = qq

        def toDict(self):
            return {"type": "at", "data": {"qq": str(self.qq)}}

    class Reply:
        type = "Reply"

        def __init__(self, id):
            self.id = id

        def toDict(self):
            return {"type": "reply", "data": {"id": str(self.id)}}

    class MessageChain:
        def __init__(self, chain):
            self.chain = chain

    api.event = event
    event.AstrMessageEvent = object
    event.filter = FakeFilter
    event.MessageChain = MessageChain
    api.star = star
    star.Context = object
    star.Star = FakeStar
    star.register = register
    components.Plain = Plain
    components.At = At
    components.Reply = Reply

    monkeypatch.setitem(sys.modules, "astrbot", astrbot)
    monkeypatch.setitem(sys.modules, "astrbot.api", api)
    monkeypatch.setitem(sys.modules, "astrbot.api.event", event)
    monkeypatch.setitem(sys.modules, "astrbot.api.star", star)
    monkeypatch.setitem(sys.modules, "astrbot.api.message_components", components)
