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


def get_weather(city: str) -> dict:
    with httpx.Client(timeout=10) as client:
        geo = client.get(GEO_URL, params={"name": city, "count": 1}).json()
        results = geo.get("results")
        if not results:
            return {"error": f"City '{city}' not found"}
        place = results[0]

        forecast = client.get(
            FORECAST_URL,
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            },
        ).json()

    current = forecast["current"]
    return {
        "city": place["name"],
        "country": place.get("country"),
        "temperature_c": current["temperature_2m"],
        "humidity_percent": current["relative_humidity_2m"],
        "wind_kmh": current["wind_speed_10m"],
        "conditions": WEATHER_CODES.get(current["weather_code"], "Unknown"),
    }
