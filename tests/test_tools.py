import json

from tools import TOOL_SCHEMAS, execute_tool


def test_schemas_registered():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {"get_weather", "convert_currency", "search_flights"}


def test_unknown_tool():
    assert "error" in execute_tool("nope", "{}")


def test_bad_json():
    assert "error" in execute_tool("get_weather", "not json")


def test_missing_argument():
    assert "error" in execute_tool("get_weather", "{}")


def test_flights_mock_is_deterministic():
    args = json.dumps({"origin": "NYC", "destination": "LON", "date": "2026-12-01"})
    assert execute_tool("search_flights", args) == execute_tool("search_flights", args)
