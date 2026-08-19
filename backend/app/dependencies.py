from app.providers.criteria import CriteriaInterpreter, FixtureCriteriaInterpreter
from app.providers.inventory import FixtureInventoryProvider, InventoryProvider

_criteria_interpreter = FixtureCriteriaInterpreter()
_inventory_provider = FixtureInventoryProvider()


def get_criteria_interpreter() -> CriteriaInterpreter:
    return _criteria_interpreter


def get_inventory_provider() -> InventoryProvider:
    return _inventory_provider
