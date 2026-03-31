from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str
    model: str = "gpt-4o"
    max_requests_per_minute: int = 490
    max_tokens_per_minute: int = 200000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
