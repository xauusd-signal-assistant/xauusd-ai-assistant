from typing import Any

from .oanda_client import get_candles, get_current_price


TIMEFRAMES = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1h": "H1",
    "4h": "H4",
}

TIMEFRAME_WEIGHTS = {
    "1m": 1,
    "5m": 2,
    "15m": 3,
    "30m": 3,
    "1h": 4,
    "4h": 4,
}


def _round_price(value: float) -> float:
    return round(value, 3)


def _ema_series(
    values: list[float],
    period: int,
) -> list[float]:
    if not values:
        raise ValueError("EMA requires price values")

    multiplier = 2.0 / (period + 1.0)
    ema_values = [values[0]]

    for value in values[1:]:
        previous = ema_values[-1]
        current = (
            value * multiplier
            + previous * (1.0 - multiplier)
        )
        ema_values.append(current)

    return ema_values


def _rma(
    values: list[float],
    period: int,
) -> float:
    if len(values) < period:
        raise ValueError(
            f"RMA requires at least {period} values"
        )

    average = sum(values[:period]) / period

    for value in values[period:]:
        average = (
            average * (period - 1)
            + value
        ) / period

    return average


def _rma_series(
    values: list[float],
    period: int,
) -> list[float]:
    if len(values) < period:
        raise ValueError(
            f"RMA requires at least {period} values"
        )

    average = sum(values[:period]) / period
    results = [average]

    for value in values[period:]:
        average = (
            average * (period - 1)
            + value
        ) / period
        results.append(average)

    return results


def _rsi(
    closes: list[float],
    period: int = 14,
) -> float:
    if len(closes) <= period:
        raise ValueError(
            f"RSI requires more than {period} closes"
        )

    gains: list[float] = []
    losses: list[float] = []

    for index in range(1, len(closes)):
        change = closes[index] - closes[index - 1]

        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    for index in range(period, len(gains)):
        average_gain = (
            average_gain * (period - 1)
            + gains[index]
        ) / period

        average_loss = (
            average_loss * (period - 1)
            + losses[index]
        ) / period

    if average_loss == 0:
        return 100.0

    relative_strength = average_gain / average_loss

    return 100.0 - (
        100.0 / (1.0 + relative_strength)
    )


def _true_ranges(
    candles: list[dict[str, Any]],
) -> list[float]:
    ranges: list[float] = []

    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]

        high = float(current["high"])
        low = float(current["low"])
        previous_close = float(previous["close"])

        ranges.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )

    return ranges


def _atr(
    candles: list[dict[str, Any]],
    period: int = 14,
) -> float:
    return _rma(
        _true_ranges(candles),
        period,
    )


def _adx_metrics(
    candles: list[dict[str, Any]],
    period: int = 14,
) -> dict[str, float]:
    if len(candles) < period * 2 + 2:
        raise ValueError(
            "ADX requires more candle history"
        )

    true_ranges: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []

    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]

        high = float(current["high"])
        low = float(current["low"])
        previous_high = float(previous["high"])
        previous_low = float(previous["low"])
        previous_close = float(previous["close"])

        upward_move = high - previous_high
        downward_move = previous_low - low

        true_ranges.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )

        plus_dm.append(
            upward_move
            if (
                upward_move > downward_move
                and upward_move > 0
            )
            else 0.0
        )

        minus_dm.append(
            downward_move
            if (
                downward_move > upward_move
                and downward_move > 0
            )
            else 0.0
        )

    smoothed_tr = _rma_series(
        true_ranges,
        period,
    )
    smoothed_plus = _rma_series(
        plus_dm,
        period,
    )
    smoothed_minus = _rma_series(
        minus_dm,
        period,
    )

    dx_values: list[float] = []
    current_plus_di = 0.0
    current_minus_di = 0.0

    for smoothed_range, plus_value, minus_value in zip(
        smoothed_tr,
        smoothed_plus,
        smoothed_minus,
    ):
        if smoothed_range == 0:
            plus_di = 0.0
            minus_di = 0.0
        else:
            plus_di = (
                100.0
                * plus_value
                / smoothed_range
            )
            minus_di = (
                100.0
                * minus_value
                / smoothed_range
            )

        denominator = plus_di + minus_di

        dx = (
            0.0
            if denominator == 0
            else (
                100.0
                * abs(plus_di - minus_di)
                / denominator
            )
        )

        dx_values.append(dx)
        current_plus_di = plus_di
        current_minus_di = minus_di

    adx = (
        _rma(dx_values, period)
        if len(dx_values) >= period
        else sum(dx_values) / len(dx_values)
    )

    return {
        "adx": adx,
        "plus_di": current_plus_di,
        "minus_di": current_minus_di,
    }


def _market_structure(
    candles: list[dict[str, Any]],
) -> str:
    if len(candles) < 24:
        return "neutral"

    previous_section = candles[-24:-12]
    recent_section = candles[-12:]

    previous_high = max(
        float(candle["high"])
        for candle in previous_section
    )
    previous_low = min(
        float(candle["low"])
        for candle in previous_section
    )

    recent_high = max(
        float(candle["high"])
        for candle in recent_section
    )
    recent_low = min(
        float(candle["low"])
        for candle in recent_section
    )

    if (
        recent_high > previous_high
        and recent_low > previous_low
    ):
        return "bullish"

    if (
        recent_high < previous_high
        and recent_low < previous_low
    ):
        return "bearish"

    return "ranging"


def _timeframe_analysis(
    label: str,
    candles: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(candles) < 60:
        raise ValueError(
            f"{label} requires at least 60 candles"
        )

    closes = [
        float(candle["close"])
        for candle in candles
    ]

    ema20_series = _ema_series(closes, 20)
    ema50_series = _ema_series(closes, 50)

    close = closes[-1]
    previous_close = closes[-2]

    ema20 = ema20_series[-1]
    previous_ema20 = ema20_series[-2]
    ema50 = ema50_series[-1]

    rsi = _rsi(closes)
    atr = _atr(candles)
    directional = _adx_metrics(candles)
    structure = _market_structure(candles)

    bullish_trend = (
        close > ema20 > ema50
        and ema20 >= previous_ema20
    )

    bearish_trend = (
        close < ema20 < ema50
        and ema20 <= previous_ema20
    )

    if bullish_trend:
        trend = "bullish"
    elif bearish_trend:
        trend = "bearish"
    else:
        trend = "neutral"

    previous_high = max(
        float(candle["high"])
        for candle in candles[-21:-1]
    )
    previous_low = min(
        float(candle["low"])
        for candle in candles[-21:-1]
    )

    breakout = (
        "bullish"
        if close > previous_high
        else "bearish"
        if close < previous_low
        else "none"
    )

    pullback = (
        "bullish"
        if (
            trend == "bullish"
            and float(candles[-1]["low"])
            <= ema20 + atr * 0.15
            and close > ema20
        )
        else "bearish"
        if (
            trend == "bearish"
            and float(candles[-1]["high"])
            >= ema20 - atr * 0.15
            and close < ema20
        )
        else "none"
    )

    return {
        "timeframe": label,
        "time": candles[-1]["time"],
        "close": _round_price(close),
        "previous_close": _round_price(
            previous_close
        ),
        "ema20": _round_price(ema20),
        "ema50": _round_price(ema50),
        "rsi": round(rsi, 2),
        "atr": _round_price(atr),
        "adx": round(directional["adx"], 2),
        "plus_di": round(
            directional["plus_di"],
            2,
        ),
        "minus_di": round(
            directional["minus_di"],
            2,
        ),
        "trend": trend,
        "structure": structure,
        "breakout": breakout,
        "pullback": pullback,
        "recent_high": _round_price(
            previous_high
        ),
        "recent_low": _round_price(
            previous_low
        ),
    }


def _weighted_bias(
    analyses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    bullish_score = 0
    bearish_score = 0
    neutral_score = 0

    for label, analysis in analyses.items():
        weight = TIMEFRAME_WEIGHTS[label]
        trend = analysis["trend"]

        if trend == "bullish":
            bullish_score += weight
        elif trend == "bearish":
            bearish_score += weight
        else:
            neutral_score += weight

        structure = analysis["structure"]

        if structure == "bullish":
            bullish_score += 1
        elif structure == "bearish":
            bearish_score += 1

    difference = bullish_score - bearish_score

    if difference >= 6:
        direction = "bullish"
    elif difference <= -6:
        direction = "bearish"
    else:
        direction = "neutral"

    return {
        "direction": direction,
        "bullish_score": bullish_score,
        "bearish_score": bearish_score,
        "neutral_score": neutral_score,
        "score_difference": difference,
    }


def _build_signal(
    price: dict[str, Any],
    analyses: dict[str, dict[str, Any]],
    bias: dict[str, Any],
) -> dict[str, Any]:
    execution = analyses["5m"]
    direction = bias["direction"]

    reasons: list[str] = []

    if direction == "neutral":
        return {
            "action": "WAIT",
            "confidence": 70,
            "reason": "Multi-timeframe direction is mixed",
            "reasons": [
                "No clear weighted bullish or bearish bias"
            ],
            "execution_timeframe": "5m",
            "entry_zone": None,
            "stop_loss": None,
            "take_profits": [],
            "risk_reward": None,
        }

    expected_trend = direction

    higher_timeframes_aligned = all(
        analyses[label]["trend"]
        in {expected_trend, "neutral"}
        for label in ("15m", "30m", "1h", "4h")
    )

    if not higher_timeframes_aligned:
        return {
            "action": "WAIT",
            "confidence": 78,
            "reason": "Higher timeframes conflict",
            "reasons": [
                "15m, 30m, 1h or 4h opposes the setup"
            ],
            "execution_timeframe": "5m",
            "entry_zone": None,
            "stop_loss": None,
            "take_profits": [],
            "risk_reward": None,
        }

    if execution["trend"] not in {
        expected_trend,
        "neutral",
    }:
        return {
            "action": "WAIT",
            "confidence": 80,
            "reason": "5-minute trend conflicts",
            "reasons": [
                "Execution timeframe opposes the higher-timeframe bias"
            ],
            "execution_timeframe": "5m",
            "entry_zone": None,
            "stop_loss": None,
            "take_profits": [],
            "risk_reward": None,
        }

    minimum_adx = (
        14.0
        if all(
            analyses[label]["trend"]
            == expected_trend
            for label in ("15m", "30m", "1h")
        )
        else 17.0
    )

    if execution["adx"] < minimum_adx:
        return {
            "action": "WAIT",
            "confidence": 82,
            "reason": (
                "5-minute trend strength is below "
                f"{minimum_adx:.0f}"
            ),
            "reasons": [
                (
                    f"Current 5-minute ADX is "
                    f"{execution['adx']:.1f}"
                )
            ],
            "execution_timeframe": "5m",
            "entry_zone": None,
            "stop_loss": None,
            "take_profits": [],
            "risk_reward": None,
        }

    mid = float(price["mid"])
    atr = float(execution["atr"])
    ema20 = float(execution["ema20"])

    if atr <= 0:
        return {
            "action": "WAIT",
            "confidence": 90,
            "reason": "Invalid volatility measurement",
            "reasons": ["ATR is not usable"],
            "execution_timeframe": "5m",
            "entry_zone": None,
            "stop_loss": None,
            "take_profits": [],
            "risk_reward": None,
        }

    long_setup = direction == "bullish"

    trigger_present = (
        execution["pullback"] == direction
        or execution["breakout"] == direction
        or (
            long_setup
            and 52 <= execution["rsi"] <= 70
            and mid >= ema20
        )
        or (
            not long_setup
            and 30 <= execution["rsi"] <= 48
            and mid <= ema20
        )
    )

    if not trigger_present:
        return {
            "action": "WAIT",
            "confidence": 84,
            "reason": "Bias exists but entry trigger is missing",
            "reasons": [
                "Waiting for pullback, breakout or momentum confirmation"
            ],
            "execution_timeframe": "5m",
            "entry_zone": None,
            "stop_loss": None,
            "take_profits": [],
            "risk_reward": None,
        }

    zone_width = atr * 0.10

    if long_setup:
        action = "BUY"

        entry_low = min(
            mid,
            ema20 + atr * 0.10,
        )
        entry_high = mid + zone_width

        structural_stop = min(
            float(execution["recent_low"]),
            entry_low - atr * 1.15,
        )

        maximum_stop = entry_low - atr * 2.20
        stop_loss = max(
            structural_stop,
            maximum_stop,
        )

        average_entry = (
            entry_low + entry_high
        ) / 2.0

        risk_distance = (
            average_entry - stop_loss
        )

        take_profits = [
            average_entry + risk_distance,
            average_entry + risk_distance * 2,
            average_entry + risk_distance * 3,
        ]

    else:
        action = "SELL"

        entry_low = mid - zone_width
        entry_high = max(
            mid,
            ema20 - atr * 0.10,
        )

        structural_stop = max(
            float(execution["recent_high"]),
            entry_high + atr * 1.15,
        )

        maximum_stop = entry_high + atr * 2.20
        stop_loss = min(
            structural_stop,
            maximum_stop,
        )

        average_entry = (
            entry_low + entry_high
        ) / 2.0

        risk_distance = (
            stop_loss - average_entry
        )

        take_profits = [
            average_entry - risk_distance,
            average_entry - risk_distance * 2,
            average_entry - risk_distance * 3,
        ]

    alignment_points = min(
        abs(bias["score_difference"]) * 2,
        20,
    )

    adx_points = min(
        max(execution["adx"] - minimum_adx, 0),
        8,
    )

    structure_points = (
        5
        if execution["structure"] == direction
        else 2
    )

    trigger_points = (
        5
        if execution["pullback"] == direction
        or execution["breakout"] == direction
        else 3
    )

    confidence = int(
        min(
            95,
            60
            + alignment_points
            + adx_points
            + structure_points
            + trigger_points,
        )
    )

    reasons.append(
        f"Weighted market bias is {direction}"
    )
    reasons.append(
        (
            f"5-minute ADX is "
            f"{execution['adx']:.1f}"
        )
    )
    reasons.append(
        (
            f"15m trend: "
            f"{analyses['15m']['trend']}"
        )
    )
    reasons.append(
        (
            f"1h trend: "
            f"{analyses['1h']['trend']}"
        )
    )

    if execution["pullback"] == direction:
        reasons.append("EMA20 pullback confirmed")

    if execution["breakout"] == direction:
        reasons.append("Recent range breakout confirmed")

    return {
        "action": action,
        "confidence": confidence,
        "reason": reasons[0],
        "reasons": reasons,
        "execution_timeframe": "5m",
        "entry_zone": {
            "low": _round_price(entry_low),
            "high": _round_price(entry_high),
            "average": _round_price(
                average_entry
            ),
        },
        "stop_loss": _round_price(stop_loss),
        "take_profits": [
            {
                "name": "TP1",
                "price": _round_price(
                    take_profits[0]
                ),
                "risk_reward": 1.0,
            },
            {
                "name": "TP2",
                "price": _round_price(
                    take_profits[1]
                ),
                "risk_reward": 2.0,
            },
            {
                "name": "TP3",
                "price": _round_price(
                    take_profits[2]
                ),
                "risk_reward": 3.0,
            },
        ],
        "risk_reward": 3.0,
        "atr": _round_price(atr),
        "spread": price["spread"],
    }


def analyze_market() -> dict[str, Any]:
    """
    Read and analyse XAUUSD across six timeframes.

    This function performs market analysis only.
    It cannot place, edit or close trades.
    """

    price = get_current_price()
    analyses: dict[str, dict[str, Any]] = {}

    for label, granularity in TIMEFRAMES.items():
        candles = get_candles(
            granularity=granularity,
            count=250,
        )

        analyses[label] = _timeframe_analysis(
            label=label,
            candles=candles,
        )

    bias = _weighted_bias(analyses)

    signal = _build_signal(
        price=price,
        analyses=analyses,
        bias=bias,
    )

    return {
        "status": "ok",
        "instrument": price["instrument"],
        "market_time": price["time"],
        "price": price,
        "bias": bias,
        "signal": signal,
        "timeframes": analyses,
        "read_only": True,
    }
