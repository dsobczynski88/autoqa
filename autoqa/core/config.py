from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from autoqa.utils import make_output_directory


class PromptConfig(BaseModel):
    """Jinja2 template filenames used by each LLM node in the RTM review graph."""
    decomposer: str = "decomposer-v2.jinja2"
    summarizer: str = "summarizer-v2.jinja2"
    coverage: str = "coverage_evaluator-v4.jinja2"
    synthesizer: str = "synthesizer_assessment.jinja2"


class Settings(BaseSettings):
    openai_api_key: str = "your_api_key"
    model: str = "gpt-4o"
    max_requests_per_minute: int = 490
    max_tokens_per_minute: int = 200000
    log_file_path: str = str(Path(make_output_directory(fold_path="./logs")) / "autoqa.log")
    prompt_config: PromptConfig = Field(default_factory=PromptConfig)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
