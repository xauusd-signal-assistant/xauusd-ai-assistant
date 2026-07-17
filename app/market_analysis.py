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


BULLISH = "bullish"
BEARISH = "bearish"
NEUTRAL = "neutral"


def _round_price(value: float) -> float:
    return round(float(value), 3)


def _ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        raise ValueError("EMA requires price values")

    multiplier = 2.0 / (period + 1.0)
    results = [values[0]]

    for value in values[1:]:
        results.append(
            value * multiplier
            + results[-1] * (1.0 - multiplier)
        )

    return results


def _wilder_average(values: list[float], period: int) -> float:
    if len(values) < period:
        raise ValueError(
            f"Wilder average requires at least {period} values"
        )

    average = sum(values[:period]) / period

    for value in values[period:]:
        average = (
            average * (period - 1)
            + value
        ) / period

    return average


def _wilder_series(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        raise ValueError(
            f"Wilder series requires at least {period} values"
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


def _rsi(closes: list[float], period: int = 14) -> float:
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
    return 100.0 - (100.0 / (1.0 + relative_strength))


def _true_ranges(candles: list[dict[str, Any]]) -> list[float]:
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
    return _wilder_average(
        _true_ranges(candles),
        period,
    )


def _adx_metrics(
    candles: list[dict[str, Any]],
    period: int = 14,
) -> dict[str, float]:
    if len(candles) < period * 2 + 2:
        raise ValueError("ADX requires more candle history")

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
            if upward_move > downward_move and upward_move > 0
            else 0.0
        )
        minus_dm.append(
            downward_move
            if downward_move > upward_move and downward_move > 0
            else 0.0
        )

    smoothed_tr = _wilder_series(true_ranges, period)
    smoothed_plus = _wilder_series(plus_dm, period)
    smoothed_minus = _wilder_series(minus_dm, period)

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
            plus_di = 100.0 * plus_value / smoothed_range
            minus_di = 100.0 * minus_value / smoothed_range

        denominator = plus_di + minus_di
        dx = (
            0.0
            if denominator == 0
            else 100.0 * abs(plus_di - minus_di) / denominator
        )

        dx_values.append(dx)
        current_plus_di = plus_di
        current_minus_di = minus_di

    adx = (
        _wilder_average(dx_values, period)
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
        return NEUTRAL

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

    if recent_high > previous_high and recent_low > previous_low:
        return BULLISH

    if recent_high < previous_high and recent_low < previous_low:
        return BEARISH

    return "ranging"


def _candle_rejection(candle: dict[str, Any]) -> str:
    open_price = float(candle["open"])
    high = float(candle["high"])
    low = float(candle["low"])
    close = float(candle["close"])

    candle_range = max(high - low, 1e-9)
    body = max(abs(close - open_price), candle_range * 0.05)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low

    if (
        close > open_price
        and lower_wick >= body * 1.15
        and close >= low + candle_range * 0.62
    ):
        return BULLISH

    if (
        close < open_price
        and upper_wick >= body * 1.15
        and close <= low + candle_range * 0.38
    ):
        return BEARISH

    return "none"


def _timeframe_analysis(
    label: str,
    candles: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(candles) < 80:
        raise ValueError(
            f"{label} requires at least 80 completed candles"
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

    ema20_slope = ema20 - previous_ema20

    bullish_trend = (
        close > ema20 > ema50
        and ema20_slope >= 0
    )
    bearish_trend = (
        close < ema20 < ema50
        and ema20_slope <= 0
    )

    if bullish_trend:
        trend = BULLISH
    elif bearish_trend:
        trend = BEARISH
    else:
        trend = NEUTRAL

    previous_high = max(
        float(candle["high"])
        for candle in candles[-21:-1]
    )
    previous_low = min(
        float(candle["low"])
        for candle in candles[-21:-1]
    )

    breakout = (
        BULLISH
        if close > previous_high
        else BEARISH
        if close < previous_low
        else "none"
    )

    latest = candles[-1]
    latest_low = float(latest["low"])
    latest_high = float(latest["high"])

    pullback = (
        BULLISH
        if (
            trend == BULLISH
            and latest_low <= ema20 + atr * 0.25
            and close >= ema20
        )
        else BEARISH
        if (
            trend == BEARISH
            and latest_high >= ema20 - atr * 0.25
            and close <= ema20
        )
        else "none"
    )

    momentum = (
        BULLISH
        if (
            close > previous_close
            and ema20_slope > 0
            and rsi >= 50
        )
        else BEARISH
        if (
            close < previous_close
            and ema20_slope < 0
            and rsi <= 50
        )
        else NEUTRAL
    )

    if directional["adx"] >= 20 and trend != NEUTRAL:
        regime = "trending"
    elif directional["adx"] <= 18 or structure == "ranging":
        regime = "ranging"
    else:
        regime = "transitional"

    recent_range = max(previous_high - previous_low, 1e-9)
    range_position = (close - previous_low) / recent_range

    return {
        "timeframe": label,
        "time": latest["time"],
        "open": _round_price(float(latest["open"])),
        "high": _round_price(latest_high),
        "low": _round_price(latest_low),
        "close": _round_price(close),
        "previous_close": _round_price(previous_close),
        "ema20": _round_price(ema20),
        "ema50": _round_price(ema50),
        "ema20_slope": _round_price(ema20_slope),
        "rsi": round(rsi, 2),
        "atr": _round_price(atr),
        "adx": round(directional["adx"], 2),
        "plus_di": round(directional["plus_di"], 2),
        "minus_di": round(directional["minus_di"], 2),
        "trend": trend,
        "structure": structure,
        "regime": regime,
        "breakout": breakout,
        "pullback": pullback,
        "momentum": momentum,
        "rejection": _candle_rejection(latest),
        "recent_high": _round_price(previous_high),
        "recent_low": _round_price(previous_low),
        "range_position": round(range_position, 3),
        "distance_to_ema20_atr": round(
            abs(close - ema20) / max(atr, 1e-9),
            3,
        ),
    }


def _direction_score(analysis: dict[str, Any]) -> int:
    score = 0

    if analysis["trend"] == BULLISH:
        score += 2
    elif analysis["trend"] == BEARISH:
        score -= 2

    if analysis["structure"] == BULLISH:
        score += 1
    elif analysis["structure"] == BEARISH:
        score -= 1

    if analysis["plus_di"] > analysis["minus_di"]:
        score += 1
    elif analysis["minus_di"] > analysis["plus_di"]:
        score -= 1

    if analysis["ema20_slope"] > 0:
        score += 1
    elif analysis["ema20_slope"] < 0:
        score -= 1

    return score


def _hierarchical_bias(
    analyses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    component_scores = {
        label: _direction_score(analyses[label])
        for label in ("15m", "30m", "1h", "4h")
    }

    composite = (
        component_scores["1h"] * 3
        + component_scores["30m"] * 2
        + component_scores["15m"]
        + component_scores["4h"]
    )

    if composite >= 5:
        direction = BULLISH
    elif composite <= -5:
        direction = BEARISH
    else:
        direction = NEUTRAL

    return {
        "direction": direction,
        "score": composite,
        "strength": round(
            min(abs(composite) / 35.0 * 100.0, 100.0),
            1,
        ),
        "component_scores": component_scores,
        "primary_1h": analyses["1h"]["trend"],
        "structure_30m": analyses["30m"]["structure"],
        "context_4h": analyses["4h"]["trend"],
    }


def _opposite(direction: str) -> str:
    return BEARISH if direction == BULLISH else BULLISH


def _one_minute_confirmation(
    direction: str,
    one_minute: dict[str, Any],
) -> bool:
    if direction == BULLISH:
        return (
            one_minute["momentum"] == BULLISH
            or one_minute["rejection"] == BULLISH
            or (
                one_minute["close"] > one_minute["ema20"]
                and one_minute["plus_di"]
                >= one_minute["minus_di"]
                and 48 <= one_minute["rsi"] <= 74
            )
        )

    return (
        one_minute["momentum"] == BEARISH
        or one_minute["rejection"] == BEARISH
        or (
            one_minute["close"] < one_minute["ema20"]
            and one_minute["minus_di"]
            >= one_minute["plus_di"]
            and 26 <= one_minute["rsi"] <= 52
        )
    )


def _trend_pullback_candidate(
    analyses: dict[str, dict[str, Any]],
    bias: dict[str, Any],
) -> dict[str, Any] | None:
    direction = bias["direction"]

    if direction not in {BULLISH, BEARISH}:
        return None

    one_hour = analyses["1h"]
    thirty = analyses["30m"]
    five = analyses["5m"]
    one = analyses["1m"]

    if (
        one_hour["trend"] == _opposite(direction)
        and thirty["structure"] == _opposite(direction)
    ):
        return None

    near_value = five["distance_to_ema20_atr"] <= 0.60
    five_minute_setup = (
        five["pullback"] == direction
        or (
            near_value
            and five["momentum"] in {direction, NEUTRAL}
        )
    )

    if not five_minute_setup:
        return None

    if direction == BULLISH:
        momentum_ok = 40 <= five["rsi"] <= 70
    else:
        momentum_ok = 30 <= five["rsi"] <= 60

    if not momentum_ok:
        return None

    if not _one_minute_confirmation(direction, one):
        return None

    confidence = 81
    reasons = [
        f"1-hour/30-minute bias is {direction}",
        "5-minute price has pulled back toward EMA20",
        "1-minute chart confirms the entry direction",
    ]

    if one_hour["trend"] == direction:
        confidence += 4
        reasons.append("1-hour trend is aligned")

    if thirty["structure"] == direction:
        confidence += 3
        reasons.append("30-minute structure is aligned")

    if five["pullback"] == direction:
        confidence += 3
        reasons.append("5-minute EMA pullback is confirmed")

    if five["adx"] >= 18:
        confidence += 2
        reasons.append("5-minute trend strength is adequate")

    if one["rejection"] == direction:
        confidence += 2
        reasons.append("1-minute rejection candle confirms timing")

    if analyses["4h"]["trend"] == _opposite(direction):
        confidence -= 2
        reasons.append("4-hour context is opposite, so size conservatively")

    return {
        "action": "BUY" if direction == BULLISH else "SELL",
        "direction": direction,
        "setup_type": "trend_pullback",
        "confidence": min(max(confidence, 0), 95),
        "reason": "Trend pullback with 1-minute confirmation",
        "reasons": reasons,
    }


def _breakout_candidate(
    price: dict[str, Any],
    analyses: dict[str, dict[str, Any]],
    bias: dict[str, Any],
) -> dict[str, Any] | None:
    five = analyses["5m"]
    one = analyses["1m"]
    thirty = analyses["30m"]

    direction = five["breakout"]

    if direction not in {BULLISH, BEARISH}:
        if (
            one["breakout"] in {BULLISH, BEARISH}
            and one["breakout"] == one["momentum"]
        ):
            direction = one["breakout"]
        else:
            return None

    if (
        bias["direction"] == _opposite(direction)
        and abs(bias["score"]) >= 12
    ):
        return None

    if five["adx"] < 15 and one["adx"] < 18:
        return None

    if not _one_minute_confirmation(direction, one):
        return None

    breakout_level = (
        float(five["recent_high"])
        if direction == BULLISH
        else float(five["recent_low"])
    )

    current_mid = float(price["mid"])
    distance = abs(current_mid - breakout_level)

    if distance > float(five["atr"]) * 0.75:
        return None

    confidence = 82
    reasons = [
        f"5-minute breakout is {direction}",
        "1-minute momentum confirms continuation",
        "Current price remains close to the breakout level",
    ]

    if bias["direction"] == direction:
        confidence += 4
        reasons.append("Higher-timeframe bias supports the breakout")

    if thirty["structure"] == direction:
        confidence += 3
        reasons.append("30-minute structure supports continuation")

    if five["adx"] >= 20:
        confidence += 3
        reasons.append("5-minute ADX confirms expansion")

    if one["breakout"] == direction:
        confidence += 2
        reasons.append("1-minute breakout confirms timing")

    return {
        "action": "BUY" if direction == BULLISH else "SELL",
        "direction": direction,
        "setup_type": "breakout_continuation",
        "confidence": min(max(confidence, 0), 95),
        "reason": "Breakout continuation with momentum confirmation",
        "reasons": reasons,
    }


def _range_reversal_candidate(
    analyses: dict[str, dict[str, Any]],
    bias: dict[str, Any],
) -> dict[str, Any] | None:
    thirty = analyses["30m"]
    five = analyses["5m"]
    one = analyses["1m"]

    if thirty["regime"] == "trending" and abs(bias["score"]) >= 12:
        return None

    if thirty["adx"] > 25:
        return None

    range_position = float(thirty["range_position"])

    if range_position <= 0.25:
        direction = BULLISH
        edge_reason = "Price is near the lower edge of the 30-minute range"
        oscillator_ok = five["rsi"] <= 46 or one["rsi"] <= 42
    elif range_position >= 0.75:
        direction = BEARISH
        edge_reason = "Price is near the upper edge of the 30-minute range"
        oscillator_ok = five["rsi"] >= 54 or one["rsi"] >= 58
    else:
        return None

    if not oscillator_ok:
        return None

    if not _one_minute_confirmation(direction, one):
        return None

    if (
        bias["direction"] == _opposite(direction)
        and abs(bias["score"]) >= 10
    ):
        return None

    confidence = 81
    reasons = [
        edge_reason,
        "5-minute momentum is stretched near the range edge",
        "1-minute reversal confirmation is present",
    ]

    if one["rejection"] == direction:
        confidence += 4
        reasons.append("1-minute rejection candle confirms the reversal")

    if five["structure"] == direction:
        confidence += 2
        reasons.append("5-minute structure has started to turn")

    if bias["direction"] in {direction, NEUTRAL}:
        confidence += 2
        reasons.append("The reversal is not fighting a strong higher-timeframe bias")

    if thirty["adx"] <= 18:
        confidence += 2
        reasons.append("30-minute conditions are consistent with a range")

    return {
        "action": "BUY" if direction == BULLISH else "SELL",
        "direction": direction,
        "setup_type": "range_reversal",
        "confidence": min(max(confidence, 0), 93),
        "reason": "Range-edge reversal with 1-minute confirmation",
        "reasons": reasons,
    }


def _select_candidate(
    price: dict[str, Any],
    analyses: dict[str, dict[str, Any]],
    bias: dict[str, Any],
) -> dict[str, Any] | None:
    candidates = [
        candidate
        for candidate in (
            _trend_pullback_candidate(analyses, bias),
            _breakout_candidate(price, analyses, bias),
            _range_reversal_candidate(analyses, bias),
        )
        if candidate is not None
    ]

    if not candidates:
        return None

    priority = {
        "trend_pullback": 3,
        "breakout_continuation": 2,
        "range_reversal": 1,
    }

    return max(
        candidates,
        key=lambda item: (
            int(item["confidence"]),
            priority.get(str(item["setup_type"]), 0),
        ),
    )


def _build_trade_signal(
    candidate: dict[str, Any],
    price: dict[str, Any],
    analyses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    direction = str(candidate["direction"])
    action = str(candidate["action"])
    setup_type = str(candidate["setup_type"])

    five = analyses["5m"]
    one = analyses["1m"]
    thirty = analyses["30m"]

    mid = float(price["mid"])
    spread = float(price["spread"])
    atr = max(float(five["atr"]), spread * 2.0, 0.001)

    if setup_type == "trend_pullback":
        reference = float(five["ema20"])
        entry_low = min(mid, reference) - atr * 0.06
        entry_high = max(mid, reference) + atr * 0.06
        maximum_stop_distance = atr * 2.10
    elif setup_type == "breakout_continuation":
        reference = (
            float(five["recent_high"])
            if direction == BULLISH
            else float(five["recent_low"])
        )
        entry_low = min(mid, reference) - atr * 0.05
        entry_high = max(mid, reference) + atr * 0.08
        maximum_stop_distance = atr * 1.85
    else:
        entry_low = mid - atr * 0.12
        entry_high = mid + atr * 0.12
        maximum_stop_distance = atr * 1.70

    average_entry = (entry_low + entry_high) / 2.0
    minimum_stop_distance = max(atr * 0.85, spread * 4.0)

    if direction == BULLISH:
        if setup_type == "range_reversal":
            desired_stop = min(
                float(thirty["recent_low"]) - atr * 0.20,
                average_entry - minimum_stop_distance,
            )
        elif setup_type == "breakout_continuation":
            desired_stop = min(
                float(one["recent_low"]) - atr * 0.10,
                float(five["recent_high"]) - atr * 0.65,
                average_entry - minimum_stop_distance,
            )
        else:
            desired_stop = min(
                float(five["recent_low"]) - atr * 0.10,
                float(one["recent_low"]) - atr * 0.10,
                average_entry - minimum_stop_distance,
            )

        stop_loss = max(
            desired_stop,
            average_entry - maximum_stop_distance,
        )

        if stop_loss >= average_entry:
            stop_loss = average_entry - minimum_stop_distance

        risk_distance = average_entry - stop_loss
        take_profit_prices = [
            average_entry + risk_distance,
            average_entry + risk_distance * 2.0,
            average_entry + risk_distance * 3.0,
        ]

    else:
        if setup_type == "range_reversal":
            desired_stop = max(
                float(thirty["recent_high"]) + atr * 0.20,
                average_entry + minimum_stop_distance,
            )
        elif setup_type == "breakout_continuation":
            desired_stop = max(
                float(one["recent_high"]) + atr * 0.10,
                float(five["recent_low"]) + atr * 0.65,
                average_entry + minimum_stop_distance,
            )
        else:
            desired_stop = max(
                float(five["recent_high"]) + atr * 0.10,
                float(one["recent_high"]) + atr * 0.10,
                average_entry + minimum_stop_distance,
            )

        stop_loss = min(
            desired_stop,
            average_entry + maximum_stop_distance,
        )

        if stop_loss <= average_entry:
            stop_loss = average_entry + minimum_stop_distance

        risk_distance = stop_loss - average_entry
        take_profit_prices = [
            average_entry - risk_distance,
            average_entry - risk_distance * 2.0,
            average_entry - risk_distance * 3.0,
        ]

    return {
        "action": action,
        "confidence": int(candidate["confidence"]),
        "reason": candidate["reason"],
        "reasons": candidate["reasons"],
        "setup_type": setup_type,
        "execution_timeframe": "5m",
        "entry_zone": {
            "low": _round_price(entry_low),
            "high": _round_price(entry_high),
            "average": _round_price(average_entry),
        },
        "stop_loss": _round_price(stop_loss),
        "take_profits": [
            {
                "name": "TP1",
                "price": _round_price(take_profit_prices[0]),
                "risk_reward": 1.0,
            },
            {
                "name": "TP2",
                "price": _round_price(take_profit_prices[1]),
                "risk_reward": 2.0,
            },
            {
                "name": "TP3",
                "price": _round_price(take_profit_prices[2]),
                "risk_reward": 3.0,
            },
        ],
        "risk_reward": 3.0,
        "atr": _round_price(atr),
        "spread": _round_price(spread),
    }


def _build_wait_signal(
    analyses: dict[str, dict[str, Any]],
    bias: dict[str, Any],
) -> dict[str, Any]:
    five = analyses["5m"]
    one = analyses["1m"]
    thirty = analyses["30m"]

    clarity = min(abs(int(bias["score"])) * 2, 20)
    setup_progress = 0

    if five["distance_to_ema20_atr"] <= 0.75:
        setup_progress += 4
    if five["breakout"] in {BULLISH, BEARISH}:
        setup_progress += 5
    if one["momentum"] in {BULLISH, BEARISH}:
        setup_progress += 4
    if one["rejection"] in {BULLISH, BEARISH}:
        setup_progress += 4
    if thirty["regime"] in {"trending", "ranging"}:
        setup_progress += 3

    confidence = int(
        min(88, 58 + clarity + setup_progress)
    )

    if bias["direction"] == NEUTRAL:
        reason = (
            "Higher-timeframe direction is not clear enough yet"
        )
    elif not _one_minute_confirmation(bias["direction"], one):
        reason = (
            "Direction is present but the 1-minute entry trigger is missing"
        )
    else:
        reason = (
            "Direction is present but no complete 5-minute setup is ready"
        )

    return {
        "action": "WAIT",
        "confidence": confidence,
        "reason": reason,
        "reasons": [
            f"Hierarchical bias: {bias['direction']}",
            f"30-minute regime: {thirty['regime']}",
            f"5-minute trend: {five['trend']}",
            f"1-minute momentum: {one['momentum']}",
        ],
        "setup_type": None,
        "execution_timeframe": "5m",
        "entry_zone": None,
        "stop_loss": None,
        "take_profits": [],
        "risk_reward": None,
    }


def analyze_market() -> dict[str, Any]:
    """
    Analyse XAUUSD using a hierarchy rather than equal voting:

    - 4h: broad context only
    - 1h: primary directional bias
    - 30m: structure and market regime
    - 5m: trade setup
    - 1m: entry timing

    The function performs read-only market analysis and cannot
    place, edit or close trades.
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

    bias = _hierarchical_bias(analyses)
    candidate = _select_candidate(
        price=price,
        analyses=analyses,
        bias=bias,
    )

    signal = (
        _build_trade_signal(
            candidate=candidate,
            price=price,
            analyses=analyses,
        )
        if candidate is not None
        else _build_wait_signal(
            analyses=analyses,
            bias=bias,
        )
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
