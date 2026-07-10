import json

from friday.skills.registry import SkillRegistry


def make_registry():
    reg = SkillRegistry()

    @reg.register("greet", "Say hello", {"type": "object", "properties": {}})
    def greet(name: str = "world"):
        return {"hello": name}

    @reg.register("boom", "Always fails", {"type": "object", "properties": {}})
    def boom():
        raise RuntimeError("kaput")

    return reg


def test_dispatch_returns_json():
    reg = make_registry()
    assert json.loads(reg.dispatch("greet", "{}")) == {"hello": "world"}


def test_dispatch_drops_hallucinated_kwargs():
    reg = make_registry()
    out = reg.dispatch("greet", json.dumps({"name": "miku", "made_up_field": 1}))
    assert json.loads(out) == {"hello": "miku"}


def test_dispatch_never_raises():
    reg = make_registry()
    assert "kaput" in json.loads(reg.dispatch("boom", "{}"))["error"]
    assert "unknown tool" in json.loads(reg.dispatch("nope", "{}"))["error"]
    assert "bad JSON" in json.loads(reg.dispatch("greet", "{not json"))["error"]


def test_tools_schema_shape():
    reg = make_registry()
    schema = reg.tools_schema()
    assert {s["function"]["name"] for s in schema} == {"greet", "boom"}
    assert all(s["type"] == "function" for s in schema)
