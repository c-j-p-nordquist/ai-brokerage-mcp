from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class IBKRSessionStatus:
    authenticated: bool
    connected: bool
    competing: bool
    message: str
    last_checked_at: datetime
    sso_expires_ms: int | None = None
