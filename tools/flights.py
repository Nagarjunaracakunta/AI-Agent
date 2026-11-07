import random


def search_flights(origin: str, destination: str, date: str) -> dict:
    # Mock data, seeded so the same search gives the same results.
    rng = random.Random(f"{origin}-{destination}-{date}".lower())
    airlines = ["SkyJet", "AeroWays", "BlueAir", "Globe Airlines"]
    flights = []
    for _ in range(3):
        hour = rng.randint(5, 21)
        flights.append({
            "airline": rng.choice(airlines),
            "departure": f"{date} {hour:02d}:{rng.choice(['00', '15', '30', '45'])}",
            "duration_hours": round(rng.uniform(1.5, 9), 1),
            "price_usd": rng.randint(120, 900),
        })
    return {"origin": origin, "destination": destination,
            "note": "Mock data, not real flights", "flights": flights}
