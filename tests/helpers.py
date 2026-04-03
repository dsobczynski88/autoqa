from pathlib import Path
import json
from unittest.mock import MagicMock, AsyncMock
from pydantic import BaseModel
from autoqa.components.clients import RateLimitOpenAIClient

def load_jsonl(fixture_name: str) -> list[dict]:
    """Load test cases from a JSONL fixture file in tests/fixtures/."""
    path = Path(__file__).parent / "fixtures" / fixture_name
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def serialize_state(state: dict) -> dict:
    """Convert an RTMReviewState dict to a JSON-serializable dict."""
    out = {}
    for key, value in state.items():
        if isinstance(value, BaseModel):
            out[key] = value.model_dump()
        elif isinstance(value, list):
            out[key] = [v.model_dump() if isinstance(v, BaseModel) else v for v in value]
        else:
            out[key] = value
    return out


def make_mock_client(response_content: str) -> RateLimitOpenAIClient:
    """Return a RateLimitOpenAIClient mock whose chat_completion returns response_content."""
    choice = MagicMock()
    choice.message.content = response_content
    completion = MagicMock()
    completion.choices = [choice]
    client = MagicMock(spec=RateLimitOpenAIClient)
    client.chat_completion = AsyncMock(return_value=completion)
    return client