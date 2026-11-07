from pydantic import BaseModel, Field


class WeatherArgs(BaseModel):
    city: str = Field(description="City name, e.g. 'Paris'")


class CurrencyArgs(BaseModel):
    amount: float = Field(description="Amount to convert")
    from_currency: str = Field(description="Source ISO code, e.g. 'USD'")
    to_currency: str = Field(description="Target ISO code, e.g. 'EUR'")


class FlightArgs(BaseModel):
    origin: str = Field(description="Origin city or airport code")
    destination: str = Field(description="Destination city or airport code")
    date: str = Field(description="Departure date in YYYY-MM-DD format")
