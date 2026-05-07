from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AccountState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nlv: float
    cash: float
    buying_power: float
    margin_usage: float
    gross_exposure: float
    open_risk: float
