from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class VehicleListing(BaseModel):
    id: str
    vin: str | None = None
    stock_number: str | None = None
    year: int
    make: str
    model: str
    trim: str | None = None
    condition: Literal["new", "used"]
    mileage: int | None = Field(default=None, ge=0)
    advertised_price: Decimal | None = Field(default=None, ge=0)
    msrp: Decimal | None = Field(default=None, ge=0)
    exterior_color: str | None = None
    interior_color: str | None = None
    features: list[str] = Field(default_factory=list)
    dealer_id: str
    dealer_name: str
    latitude: float | None = None
    longitude: float | None = None
    distance_miles: float | None = Field(default=None, ge=0)
    source_url: str
    source_provider: str
