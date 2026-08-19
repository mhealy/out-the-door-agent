from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class VehicleSearchCriteria(BaseModel):
    make: str
    model: str
    trims: list[str] = Field(default_factory=list)
    condition: Literal["new", "used", "either"]
    years: list[int] = Field(default_factory=list)
    home_location: str
    max_distance_miles: int = Field(gt=0)
    max_advertised_price: Decimal | None = Field(default=None, ge=0)
    max_otd_price: Decimal | None = Field(default=None, ge=0)
    required_features: list[str] = Field(default_factory=list)
    excluded_features: list[str] = Field(default_factory=list)
    preferred_exterior_colors: list[str] = Field(default_factory=list)
    excluded_exterior_colors: list[str] = Field(default_factory=list)
    preferred_interior_colors: list[str] = Field(default_factory=list)
    excluded_interior_colors: list[str] = Field(default_factory=list)
    hard_constraints: list[str] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)
    ranking_preference: Literal["lowest_price", "balanced", "lowest_friction"] = (
        "lowest_price"
    )


class CriteriaExtractionResult(BaseModel):
    criteria: VehicleSearchCriteria
    assumptions: list[str] = Field(default_factory=list)
    unresolved_ambiguities: list[str] = Field(default_factory=list)
