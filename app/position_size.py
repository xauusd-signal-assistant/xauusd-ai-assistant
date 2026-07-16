from decimal import Decimal, ROUND_DOWN
from .config import settings

def _floor(value: float, step: float) -> float:
    units = (Decimal(str(value)) / Decimal(str(step))).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return float(units * Decimal(str(step)))

def estimated_lot(balance_gbp: float, risk_percent: float, stop_distance: float) -> float | None:
    if stop_distance <= 0:
        return None
    risk_usd = balance_gbp * risk_percent / 100 * settings.gbpusd_rate
    raw = risk_usd / (stop_distance * settings.xauusd_contract_size)
    lot = min(_floor(raw, settings.xauusd_lot_step), settings.xauusd_max_lot)
    return round(lot, 2) if lot >= settings.xauusd_min_lot else None

def add_lots(decision):
    if decision.action == "WAIT" or decision.entry is None or decision.stop_loss is None:
        return decision
    distance = abs(decision.entry - decision.stop_loss)
    decision.demo_lot = estimated_lot(settings.demo_balance_gbp, settings.demo_risk_percent, distance)
    decision.live_lot = estimated_lot(settings.live_balance_gbp, settings.live_risk_percent, distance)
    return decision
