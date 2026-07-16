import json
from openai import OpenAI
from .config import settings
from .models import SignalDecision

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["BUY", "SELL", "WAIT"]},
        "execution_timeframe": {"type": "string", "enum": ["1 Minute", "5 Minute", "None"]},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "entry": {"type": ["number", "null"]},
        "stop_loss": {"type": ["number", "null"]},
        "take_profit": {"type": ["number", "null"]},
        "risk_reward": {"type": ["number", "null"]},
        "demo_lot": {"type": ["number", "null"]},
        "live_lot": {"type": ["number", "null"]},
        "reason": {"type": "string"},
        "invalidation": {"type": "string"},
        "source": {"type": "string", "enum": ["openai"]}
    },
    "required": ["action", "execution_timeframe", "confidence", "entry", "stop_loss",
                 "take_profit", "risk_reward", "demo_lot", "live_lot", "reason",
                 "invalidation", "source"],
    "additionalProperties": False
}

def review(alert, baseline, context):
    if not settings.enable_openai or not settings.openai_api_key or baseline.action == "WAIT":
        return baseline
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_model,
        instructions=(
            "You are a cautious XAUUSD safety reviewer. Use only supplied data. "
            "Never reverse BUY to SELL or SELL to BUY. Approve the same action or return WAIT. "
            "Prefer WAIT if news context is concerning, conflicting or incomplete. "
            "Keep reason under 45 characters. Preserve candidate chart and levels when approving. "
            "Leave demo_lot and live_lot null; the server calculates them."
        ),
        input=json.dumps({
            "chart_data": alert.model_dump(exclude={"secret"}),
            "candidate": baseline.model_dump(),
            "news_context": context,
        }),
        text={"format": {"type": "json_schema", "name": "xauusd_review", "strict": True, "schema": SCHEMA}},
    )
    decision = SignalDecision.model_validate_json(response.output_text)
    if decision.action not in {baseline.action, "WAIT"}:
        return baseline
    if decision.action == "WAIT":
        decision.execution_timeframe = "None"
        decision.entry = decision.stop_loss = decision.take_profit = None
        decision.risk_reward = None
    else:
        decision.execution_timeframe = baseline.execution_timeframe
        decision.entry = baseline.entry
        decision.stop_loss = baseline.stop_loss
        decision.take_profit = baseline.take_profit
        decision.risk_reward = baseline.risk_reward
    decision.demo_lot = None
    decision.live_lot = None
    return decision
