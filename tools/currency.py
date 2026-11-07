import httpx

URL = "https://api.frankfurter.dev/v1/latest"


def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    base, target = from_currency.upper(), to_currency.upper()
    if base == target:
        return {"amount": amount, "converted": amount, "rate": 1.0,
                "from": base, "to": target}

    resp = httpx.get(URL, params={"base": base, "symbols": target}, timeout=10)
    if resp.status_code != 200:
        return {"error": f"Could not get rate for {base}->{target}"}

    rate = resp.json()["rates"][target]
    return {
        "amount": amount,
        "from": base,
        "to": target,
        "rate": rate,
        "converted": round(amount * rate, 2),
    }
