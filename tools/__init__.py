import json

from pydantic import ValidationError

from schemas import CurrencyArgs, FlightArgs, WeatherArgs
from .currency import convert_currency
from .flights import search_flights
from .weather import get_weather

# name -> (args model, function, description the LLM sees)
TOOLS = {
    "get_weather": (
        WeatherArgs, get_weather,
        "Get the current weather for a city or town. Use for any live weather question.",
    ),
    "convert_currency": (
        CurrencyArgs, convert_currency,
        "Convert an amount between currencies using live exchange rates.",
    ),
    "search_flights": (
        FlightArgs, search_flights,
        "Search flights between two places on a given date.",
    ),
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": model.model_json_schema(),
        },
    }
    for name, (model, _fn, description) in TOOLS.items()
]


def execute_tool(name: str, raw_args: str) -> dict:
    """Validate arguments and run a tool. Never raises, returns {'error': ...}."""
    if name not in TOOLS:
        return {"error": f"Unknown tool '{name}'"}
    model, fn, _ = TOOLS[name]
    try:
        args = model(**json.loads(raw_args or "{}"))
    except (json.JSONDecodeError, ValidationError) as e:
        return {"error": f"Invalid arguments: {e}"}
    try:
        return fn(**args.model_dump())
    except Exception as e:  # network errors, bad API responses, etc.
        return {"error": f"{name} failed: {e}"}
