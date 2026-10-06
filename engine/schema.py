"""Typed records shared by every adapter and engine module.

Every row carries a provenance label so simulated data can never be mistaken
for a real fill (SIM_* never calibrates anything).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class Provenance(str, Enum):
    REAL_OWN = "REAL_OWN"                  # the user's own exchange fills
    REAL_PLATFORM_PUBLIC = "REAL_PLATFORM_PUBLIC"  # public on-chain fills of someone else
    REPLAY_NATIVE = "REPLAY_NATIVE"        # replay of recorded exchange tape
    SIM_PAPER = "SIM_PAPER"                # paper or demo fills
    SIM_BACKTEST = "SIM_BACKTEST"          # counterfactual computed by us
    SIM_PLANTED = "SIM_PLANTED"            # planted-leak self-test fixture


class Fill(BaseModel):
    model_config = ConfigDict(frozen=True)

    venue: str
    account: str            # account id, so a later sub-account stream can merge
    exec_id: str            # exchange fill id (dedupe key together with account)
    order_id: str
    t_ms: int
    symbol: str
    side: str               # "buy" or "sell"
    is_open: bool           # opens or adds to a position
    price: float
    size: float
    fee: float              # positive number = cost
    realized_pnl: float     # exchange-reported realised pnl on this fill (gross of fee)
    start_position: float   # signed position before this fill, if the venue reports it
    provenance: Provenance


class Order(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str
    symbol: str
    t_first_ms: int
    t_last_ms: int
    side: str
    is_open: bool
    notional: float
    fee: float
    realized_pnl: float
    provenance: Provenance

    @property
    def net_pnl(self) -> float:
        return self.realized_pnl - self.fee


class RoundTrip(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    t_open_ms: int
    t_close_ms: int
    side: str                 # direction of the first fill
    first_order_notional: float
    opened_notional: float
    net_pnl: float            # realised pnl minus every fee in the trip
    first_order_id: str
    provenance: Provenance

    @property
    def hold_ms(self) -> int:
        return self.t_close_ms - self.t_open_ms
