# XAUUSD Signal Assistant

A demo-first signal system:

TradingView alert → FastAPI webhook → deterministic risk checks → optional OpenAI review → BUY / SELL / WAIT response.

It **does not place trades**. It is intentionally designed for manual approval and forward testing.

## Features

- Receives TradingView JSON webhooks
- Validates a shared webhook secret
- Rejects stale and duplicate alerts
- Calculates a rules-based market bias
- Applies hard risk gates before any AI call
- Optionally asks OpenAI for a structured BUY / SELL / WAIT assessment
- Logs every alert and decision to SQLite
- Includes a Pine Script indicator for XAUUSD
- Includes a small test suite

## 1. Install

Python 3.11+ recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and choose a long random `WEBHOOK_SECRET`.

## 2. Run locally

```bash
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

Test webhook:

```bash
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{
    "secret":"change-me",
    "alert_id":"manual-test-001",
    "symbol":"OANDA:XAUUSD",
    "timeframe":"5",
    "timestamp":1784217600,
    "price":3991.46,
    "ema20":3993.10,
    "ema50":3995.40,
    "rsi":42.8,
    "atr":4.2,
    "trend_1h":"bearish",
    "setup":"short"
  }'
```

Use a current Unix timestamp when testing because stale alerts are rejected.

## 3. OpenAI mode

Set:

```env
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5-mini
ENABLE_OPENAI=true
```

When disabled or unavailable, the service still works using deterministic rules.

The AI never overrides a hard risk rejection. A failed AI call falls back to the rules engine.

## 4. TradingView setup

1. Open XAUUSD in TradingView.
2. Open Pine Editor.
3. Paste `pine/xauusd_signal_assistant.pine`.
4. Add it to the chart.
5. Create an alert using **Any alert() function call**.
6. Set the webhook URL to:

```text
https://YOUR-DOMAIN/webhook/tradingview
```

7. Set the Pine input `Webhook secret` to the same value as `.env`.

Use HTTPS in production. Do not put broker passwords, OpenAI keys, or account credentials in the alert.

## 5. Recommended demo testing

- Begin with 0.25% account risk per idea.
- Manually approve every signal.
- Collect at least 200–300 signals.
- Review expectancy, profit factor, maximum drawdown, losing streaks, session performance, spread and slippage.
- Do not evaluate the system from one profitable day.

## API endpoints

- `GET /health`
- `POST /webhook/tradingview`
- `GET /signals?limit=50`

## Important limitations

Indicators supplied by TradingView are not a complete picture of market context. The service does not know about broker-specific spread, slippage, margin, execution quality or economic-news risk unless you add those data sources.

This project is educational software, not financial advice.


## Phone and laptop notifications

This version sends signals through Telegram. Install Telegram on the iPhone and
Telegram Desktop on the Dell laptop, signed into the same account. One bot
message then produces a notification on both devices.

1. In Telegram, open `@BotFather`.
2. Send `/newbot` and follow the prompts.
3. Copy the bot token into `TELEGRAM_BOT_TOKEN`.
4. Open the new bot and send it any message.
5. In a browser, open:
   `https://api.telegram.org/botYOUR_TOKEN/getUpdates`
6. Find the numeric `chat.id` and put it into `TELEGRAM_CHAT_ID`.
7. Restart the API and check `/health`; `telegram` should be `true`.

Enable notifications for Telegram in Windows Settings and iPhone Settings.
Keep `NOTIFY_WAIT_SIGNALS=false` to receive only actionable BUY/SELL alerts.

## News and scheduled-event protection

Two optional feeds are supported:

- `FINNHUB_API_KEY`: upcoming high-impact US economic events.
- `NEWSAPI_KEY`: recent gold, Federal Reserve, inflation, employment, dollar,
  yields and geopolitical headlines.

When a high-impact US event is within the configured before/after buffer, the
system forces `WAIT`. If either feed is missing, the system tells the AI that
context is incomplete; it cannot guarantee that every speech or breaking event
has been captured.

For the requested UK schedule, signals are accepted from 12:30 to 16:30. The hard 13:30–13:50 volatility blackout remains active, so signals during that interval are forced to WAIT.

## Account setting

The default demo balance is now 4500. Update `ACCOUNT_BALANCE` whenever the
demo balance changes. Before moving to a £2,000 live account, change it to 2000
and repeat forward testing; do not reuse position sizes from the larger demo.


## Version 3 trading window

The configured UK signal window is now:

- Start: 12:30
- End: 16:30
- Safety blackout: 13:30–13:50

The API can assess and notify signals from 12:30 onward, but it will return
`WAIT` during the 13:30–13:50 high-volatility period you asked to avoid.
