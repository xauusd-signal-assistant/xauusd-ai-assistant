from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Webhook security
    webhook_secret: str = "change-me"

    # Telegram
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    notify_wait_signals: bool = True

    # OpenAI
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    enable_openai: bool = True

    # Trading session
    timezone: str = "Europe/London"
    session_start: str = "05:00"
    session_end: str = "23:00"
    hard_blackout_start: str = "00:00"
    hard_blackout_end: str = "00:00"

    # Account balances and risk
    demo_balance_gbp: float = 4500.0
    live_balance_gbp: float = 2000.0
    demo_risk_percent: float = 0.25
    live_risk_percent: float = 0.25
    max_daily_loss_percent: float = 1.5
    min_risk_reward: float = 2.0

    # Temporary XAUUSD contract settings
    # These will later be replaced with exact MT5 broker information.
    xauusd_contract_size: float = 100.0
    xauusd_min_lot: float = 0.01
    xauusd_lot_step: float = 0.01
    xauusd_max_lot: float = 0.50
    gbpusd_rate: float = 1.27

    # Economic calendar and news
    finnhub_api_key: str | None = None
    fmp_api_key: str | None = None
    newsapi_key: str | None = None
    news_lookback_hours: int = 12
    event_blackout_minutes_before: int = 20
    event_blackout_minutes_after: int = 20

    # OANDA practice market-data connection
    oanda_api_token: str | None = None
    oanda_account_id: str | None = None
    oanda_env: str = "practice"
    oanda_instrument: str = "XAU_USD"

    # Signal processing
    max_alert_age_seconds: int = 180

    # Database
    database_path: str = "signals.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
