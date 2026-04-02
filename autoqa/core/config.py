from pathlib import Path
from autoqa.utils import make_output_directory
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str = "your_api_key"
    model: str = "gpt-4o"
    max_requests_per_minute: int = 490
    max_tokens_per_minute: int = 200000
    log_file_path: str = str(Path(make_output_directory(fold_path="./logs")) / "autoqa.log")
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
