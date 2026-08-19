from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Evidence(BaseModel):
    id: str
    source_type: Literal[
        "DEALER_EMAIL",
        "DEALER_ATTACHMENT",
        "LISTING",
        "OEM_SOURCE",
        "WEB_SOURCE",
    ]
    source_id: str
    field_name: str
    excerpt: str
    created_at: datetime
