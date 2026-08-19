import re
from typing import Protocol

from app.domain.criteria import CriteriaExtractionResult, VehicleSearchCriteria


class CriteriaInterpreter(Protocol):
    async def interpret(self, goal: str) -> CriteriaExtractionResult: ...


class FixtureCriteriaInterpreter:
    """Demo interpreter for the fixture inventory scenario.

    The boundary can be replaced by an LLM-backed interpreter without changing the
    API or deterministic inventory services.
    """

    async def interpret(self, goal: str) -> CriteriaExtractionResult:
        lowered = goal.casefold()
        years = [int(value) for value in re.findall(r"\b20\d{2}\b", goal)]
        distance = re.search(r"(?:within|under)\s+(\d+)\s+miles?", lowered)
        price = re.search(r"(?:under|below|max(?:imum)?)\s+\$([\d,]+)", lowered)
        trims = ["Limited"] if "limited" in lowered else []
        required_features = ["AWD"] if re.search(r"\b(?:require|must have)\b.*\bawd\b", lowered) else []
        preferred_colors = [
            color.title()
            for color in ("blue", "white", "gray", "silver", "red")
            if re.search(rf"\bprefer\w*\b.*\b{color}\b", lowered)
        ]
        excluded_colors = [
            color.title()
            for color in ("black", "white", "gray", "silver", "red")
            if re.search(rf"\b(?:avoid|no|exclude)\b.*\b{color}\b", lowered)
        ]
        assumptions: list[str] = []
        ambiguities: list[str] = []
        if not distance:
            assumptions.append("Using a 50-mile Houston-area search radius.")
        if not years:
            assumptions.append("Model year is not restricted.")
        if not price:
            assumptions.append("No advertised-price ceiling was specified.")
        if not trims:
            ambiguities.append("No trim was specified; all trims remain eligible.")

        criteria = VehicleSearchCriteria(
            make="Hyundai",
            model="Tucson Hybrid",
            trims=trims,
            condition="used" if "used" in lowered else "new",
            years=years,
            home_location="Houston, TX",
            max_distance_miles=int(distance.group(1)) if distance else 50,
            max_advertised_price=price.group(1).replace(",", "") if price else None,
            required_features=required_features,
            preferred_exterior_colors=preferred_colors,
            excluded_exterior_colors=excluded_colors,
            hard_constraints=[
                value
                for value in (
                    "make: Hyundai",
                    "model: Tucson Hybrid",
                    f"trim: {trims[0]}" if trims else None,
                    f"years: {', '.join(map(str, years))}" if years else None,
                    f"distance <= {distance.group(1)} miles" if distance else None,
                    f"advertised price <= ${price.group(1)}" if price else None,
                    "feature: AWD" if required_features else None,
                )
                if value is not None
            ],
            soft_preferences=[f"exterior color: {color}" for color in preferred_colors],
        )
        return CriteriaExtractionResult(
            criteria=criteria,
            assumptions=assumptions,
            unresolved_ambiguities=ambiguities,
        )
