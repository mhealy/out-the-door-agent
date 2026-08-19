from typing import Protocol

from app.domain.criteria import VehicleSearchCriteria
from app.domain.vehicle import VehicleListing


class InventoryProvider(Protocol):
    async def search(self, criteria: VehicleSearchCriteria) -> list[VehicleListing]: ...

    async def get_by_id(self, vehicle_id: str) -> VehicleListing | None: ...


FIXTURE_RECORDS = [
    {
        "id": "baytown-blue",
        "vin": "KM8JCDD10SU000001",
        "stock_number": "B1001",
        "year": 2025,
        "make": "Hyundai",
        "model": "Tucson Hybrid",
        "trim": "Limited",
        "condition": "new",
        "mileage": 8,
        "advertised_price": "37800",
        "msrp": "42150",
        "exterior_color": "Deep Sea Blue",
        "interior_color": "Gray",
        "features": ["AWD", "panoramic roof", "heated seats"],
        "dealer_id": "baytown",
        "dealer_name": "Baytown Hyundai",
        "distance_miles": 34,
        "source_url": "https://example.test/inventory/baytown-blue",
    },
    {
        "id": "houston-white",
        "vin": "KM8JCDD11SU000002",
        "stock_number": "H2002",
        "year": 2025,
        "make": "Hyundai",
        "model": "Tucson Hybrid",
        "trim": "Limited",
        "condition": "new",
        "mileage": 12,
        "advertised_price": "37250",
        "msrp": "41980",
        "exterior_color": "White Pearl",
        "interior_color": "Black",
        "features": ["AWD", "panoramic roof"],
        "dealer_id": "houston",
        "dealer_name": "Houston Hyundai",
        "distance_miles": 12,
        "source_url": "https://example.test/inventory/houston-white",
    },
    {
        "id": "katy-blue",
        "vin": "KM8JCDD12TU000003",
        "stock_number": "K3003",
        "year": 2026,
        "make": "Hyundai",
        "model": "Tucson Hybrid",
        "trim": "Limited",
        "condition": "new",
        "mileage": 5,
        "advertised_price": "39500",
        "msrp": "42900",
        "exterior_color": "Blue Stone",
        "interior_color": "Gray",
        "features": ["AWD", "heated seats"],
        "dealer_id": "katy",
        "dealer_name": "Katy Hyundai",
        "distance_miles": 28,
        "source_url": "https://example.test/inventory/katy-blue",
    },
    {
        "id": "too-far",
        "year": 2025,
        "make": "Hyundai",
        "model": "Tucson Hybrid",
        "trim": "Limited",
        "condition": "new",
        "advertised_price": "36000",
        "exterior_color": "Blue",
        "features": ["AWD"],
        "dealer_id": "austin",
        "dealer_name": "Austin Hyundai",
        "distance_miles": 155,
        "source_url": "https://example.test/inventory/too-far",
    },
]


class FixtureInventoryProvider:
    @staticmethod
    def _listings() -> list[VehicleListing]:
        return [
            VehicleListing(source_provider="fixture", **record)
            for record in FIXTURE_RECORDS
        ]

    async def search(self, criteria: VehicleSearchCriteria) -> list[VehicleListing]:
        del criteria
        return self._listings()

    async def get_by_id(self, vehicle_id: str) -> VehicleListing | None:
        return next(
            (listing for listing in self._listings() if listing.id == vehicle_id),
            None,
        )
