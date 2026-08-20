from sqlalchemy.orm import Session

from app.domain.purchase import PurchaseActivityItem
from app.persistence.purchase_activity import PurchaseActivityRepository
from app.persistence.purchases import PurchaseRunRepository


class PurchaseActivityService:
    """Read purchase history without resuming workflows or calling providers."""

    def __init__(self, session: Session) -> None:
        self._purchases = PurchaseRunRepository(session)
        self._activity = PurchaseActivityRepository(session)

    def list(self, purchase_id: str) -> list[PurchaseActivityItem]:
        self._purchases.get(purchase_id)
        return self._activity.list_for_purchase(purchase_id)
