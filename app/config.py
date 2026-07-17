from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    webhook_secret: str = "change-me"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    enable_openai: bool = True
    notify_wait_signals: bool = True
    timezone: str = "Europe/London"
    session_start: str = "12:30"
    session_end: str = "16:30"
    hard_blackout_start: str = "13:30"
    hard_blackout_end: str = "13:50"
    demo_balance_gbp: float = 4500.0
    live_balance_gbp: float = 2000.0
    demo_risk_percent: float = 0.25
    live_risk_percent: float = 0.25
    max_daily_loss_percent: float = 1.5
    min_risk_reward: float = 2.0
    xauusd_contract_size: float = 100.0
    xauusd_min_lot: float = 0.01
    xauusd_lot_step: float = 0.01
    xauusd_max_lot: float = 0.50
    gbpusd_rate: float = 1.27
    finnhub_api_key: str | None = None
    fmp_api_key: str | None = None
    newsapi_key: str | None = None
    news_lookback_hours: int = 12
    event_blackout_minutes_before: int = 20
    event_blackout_minutes_after: int = 20
    max_alert_age_seconds: int = 180
    database_path: str = "signals.db"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
