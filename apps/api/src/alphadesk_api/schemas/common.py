"""Common response fields."""

from datetime import datetime

from pydantic import BaseModel


class TimestampedResponse(BaseModel):
    timestamp: datetime
