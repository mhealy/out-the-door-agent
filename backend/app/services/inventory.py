from decimal import Decimal

from app.domain.criteria import VehicleSearchCriteria
from app.domain.vehicle import VehicleListing


def _normalized(values: list[str]) -> set[str]:
    return {value.casefold() for value in values}


def _matches(criteria: VehicleSearchCriteria, listing: VehicleListing) -> bool:
    features = _normalized(listing.features)
    if listing.make.casefold() != criteria.make.casefold():
        return False
    if listing.model.casefold() != criteria.model.casefold():
        return False
    if criteria.condition != "either" and listing.condition != criteria.condition:
        return False
    if criteria.years and listing.year not in criteria.years:
        return False
    if criteria.trims and (listing.trim or "").casefold() not in _normalized(criteria.trims):
        return False
    if listing.distance_miles is None or listing.distance_miles > criteria.max_distance_miles:
        return False
    if criteria.max_advertised_price is not None and (
        listing.advertised_price is None
        or listing.advertised_price > criteria.max_advertised_price
    ):
        return False
    if not _normalized(criteria.required_features).issubset(features):
        return False
    if _normalized(criteria.excluded_features) & features:
        return False
    if any(color in (listing.exterior_color or "").casefold() for color in _normalized(criteria.excluded_exterior_colors)):
        return False
    if any(color in (listing.interior_color or "").casefold() for color in _normalized(criteria.excluded_interior_colors)):
        return False
    return True


def filter_candidates(
    criteria: VehicleSearchCriteria, listings: list[VehicleListing]
) -> list[VehicleListing]:
    return [listing for listing in listings if _matches(criteria, listing)]


def shortlist_candidates(
    criteria: VehicleSearchCriteria,
    listings: list[VehicleListing],
    limit: int = 5,
) -> list[VehicleListing]:
    trims = _normalized(criteria.trims)
    colors = _normalized(criteria.preferred_exterior_colors)

    def key(item: VehicleListing) -> tuple[bool, bool, Decimal, float, str]:
        return (
            bool(trims) and (item.trim or "").casefold() not in trims,
            bool(colors) and not any(
                color in (item.exterior_color or "").casefold() for color in colors
            ),
            item.advertised_price if item.advertised_price is not None else Decimal("Infinity"),
            item.distance_miles if item.distance_miles is not None else float("inf"),
            item.id,
        )

    return sorted(listings, key=key)[:limit]
