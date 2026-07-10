from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"
    restaurant_timezone: str = "Pacific/Auckland"

    database_url: str

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_staff_number: str = ""
    twilio_sms_from: str = ""

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"

    stt_provider: str = "deepgram"
    deepgram_api_key: str = ""
    assemblyai_api_key: str = ""

    tts_provider: str = "elevenlabs"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    cartesia_api_key: str = ""

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    notification_channels: str = "sms"  # comma-separated: sms,email


@lru_cache
def get_settings() -> Settings:
    return Settings()
