import unicodedata

import httpx

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers",
    95: "Thunderstorm",
}


def _norm(text) -> str:
    """Lower-case and strip accents so 'Goā' == 'goa'."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).casefold().strip()


def choose_place(results: list, name: str, hint: str = "") -> dict:
    """Pick the right geocoder match without guessing.

    Returns {"place": ..., "others": [...]} or {"error": ...}. The geocoder is
    fuzzy ("Goa" -> Genoa), so only exact name matches are accepted; if several
    places share the name, the biggest wins and the rest are reported.
    """
    if hint:  # "Panjim, Goa": keep matches whose region/country contains the hint
        hinted = [r for r in results
                  if hint in _norm(r.get("admin1")) or hint in _norm(r.get("country"))
                  or hint == _norm(r.get("country_code"))]
        results = hinted or results

    exact = [r for r in results if _norm(r["name"]) == _norm(name)]
    if not exact:
        close = ", ".join(f"{r['name']} ({r.get('admin1') or r.get('country')})"
                          for r in results[:3])
        return {"error": (
            f"No exact match for '{name}'." + (f" Closest places: {close}." if close else "")
            + " Do not guess: ask the user which place they mean, or retry with a "
              "city name or a country_code.")}

    exact.sort(key=lambda r: r.get("population") or 0, reverse=True)
    return {"place": exact[0], "others": exact[1:4]}


def get_weather(city: str, country_code: str | None = None) -> dict:
    name, _, hint = city.partition(",")  # accepts "City" or "City, Region/Country"
    name, hint = name.strip(), _norm(hint)
    params = {"name": name, "count": 10}
    if country_code:
        params["countryCode"] = country_code.upper()

    with httpx.Client(timeout=10) as client:
        results = client.get(GEO_URL, params=params).json().get("results") or []
        if not results:
            return {"error": f"Place '{city}' not found"}
        choice = choose_place(results, name, hint)
        if "error" in choice:
            return choice
        place = choice["place"]

        forecast = client.get(
            FORECAST_URL,
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            },
        ).json()

    current = forecast["current"]
    result = {
        "city": place["name"],
        "region": place.get("admin1"),
        "country": place.get("country"),
        "temperature_c": current["temperature_2m"],
        "humidity_percent": current["relative_humidity_2m"],
        "wind_kmh": current["wind_speed_10m"],
        "conditions": WEATHER_CODES.get(current["weather_code"], "Unknown"),
    }
    if choice["others"]:
        result["note"] = (
            "Several places share this name. If the user meant another one, call "
            "again with country_code. Other matches: "
            + "; ".join(f"{r['name']}, {r.get('admin1')}, {r.get('country')}"
                        for r in choice["others"]))
    return result
