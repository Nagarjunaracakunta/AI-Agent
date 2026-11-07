from pydantic import BaseModel, Field


class WeatherArgs(BaseModel):
    city: str = Field(description=(
        "A city or town, e.g. 'Paris'. NOT a state or region: for a region "
        "use its main city (e.g. 'Panjim' for Goa). 'City, Region' is allowed."))
    country_code: str | None = Field(default=None, description=(
        "ISO 3166-1 alpha-2 country code such as 'IN' or 'US'. Provide it "
        "whenever the country is known; it avoids same-name cities."))


class CurrencyArgs(BaseModel):
    amount: float = Field(description="Amount to convert")
    from_currency: str = Field(description="Source ISO code, e.g. 'USD'")
    to_currency: str = Field(description="Target ISO code, e.g. 'EUR'")


class FlightArgs(BaseModel):
    origin: str = Field(description="Origin city or airport code")
    destination: str = Field(description="Destination city or airport code")
    date: str = Field(description="Departure date in YYYY-MM-DD format")
