from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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

    @model_validator(mode="after")
    def derive_display_constraints(self) -> "VehicleSearchCriteria":
        """Keep inspectable labels synchronized with filtering inputs."""
        constraints = [
            f"condition: {self.condition}",
            f"make: {self.make}",
            f"model: {self.model}",
        ]
        constraints.extend(f"trim: {trim}" for trim in self.trims)
        constraints.extend(f"model year: {year}" for year in self.years)
        constraints.extend(
            [
                f"location: {self.home_location}",
                f"distance <= {self.max_distance_miles} miles",
            ]
        )
        if self.max_advertised_price is not None:
            constraints.append(
                f"advertised price <= ${self.max_advertised_price:,.0f}"
            )
        if self.max_otd_price is not None:
            constraints.append(f"out-the-door price <= ${self.max_otd_price:,.0f}")
        constraints.extend(
            f"required feature: {feature}" for feature in self.required_features
        )
        constraints.extend(
            f"excluded feature: {feature}" for feature in self.excluded_features
        )
        constraints.extend(
            f"excluded exterior color: {color}"
            for color in self.excluded_exterior_colors
        )
        constraints.extend(
            f"excluded interior color: {color}"
            for color in self.excluded_interior_colors
        )
        self.hard_constraints = constraints

        derived_preferences = [
            *(f"preferred exterior color: {color}" for color in self.preferred_exterior_colors),
            *(f"preferred interior color: {color}" for color in self.preferred_interior_colors),
        ]
        self.soft_preferences = list(
            dict.fromkeys([*self.soft_preferences, *derived_preferences])
        )
        return self


class CriteriaExtractionResult(BaseModel):
    criteria: VehicleSearchCriteria
    assumptions: list[str] = Field(default_factory=list)
    unresolved_ambiguities: list[str] = Field(default_factory=list)
