import os
from dotenv import load_dotenv
from pathlib import Path
from autoqa.utils import make_output_directory
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

class Settings(BaseSettings):
    openai_api_key: str = os.getenv('BEDROCK_API_KEY_SONNET_45')
    url: str = os.getenv('BEDROCK_API_BASE_URL')
    model: str = os.getenv('BEDROCK_MODEL_SONNET_45')
    max_requests_per_minute: int = 490
    max_tokens_per_minute: int = 200000
    log_file_path: str = str(Path(make_output_directory(fold_path="./logs")) / "autoqa.log")
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
