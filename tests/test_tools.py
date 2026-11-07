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


def test_stub_search():
    from tools.search import execute_search
    result = execute_search("search_web", '{"query": "kubernetes"}')
    assert len(result["results"]) == 3
    assert "error" in execute_search("search_web", "{}")


def _place(name, admin1, country, code, pop=None):
    return {"name": name, "admin1": admin1, "country": country,
            "country_code": code, "population": pop}


def test_weather_never_returns_a_fuzzy_match():
    """Regression: the geocoder returns Genoa for 'Goa'. Don't accept it."""
    from tools.weather import choose_place
    result = choose_place([_place("Genoa", "Liguria", "Italy", "IT", 580097)], "Goa")
    assert "error" in result and "Genoa" in result["error"]


def test_weather_prefers_exact_and_biggest_and_reports_others():
    from tools.weather import choose_place
    results = [_place("Paris", "Texas", "United States", "US", 24782),
               _place("Paris", "Île-de-France", "France", "FR", 2138551)]
    choice = choose_place(results, "Paris")
    assert choice["place"]["country"] == "France"
    assert choice["others"][0]["admin1"] == "Texas"


def test_weather_region_hint_and_accents():
    from tools.weather import _norm, choose_place
    results = [_place("Panjim", "Xinjiang", "China", "CN", 25307),
               _place("Panjim", "Goa", "India", "IN", 70991)]
    assert choose_place(results, "Panjim", _norm("xinjiang"))["place"]["country"] == "China"
    assert _norm("Goā") == "goa"
