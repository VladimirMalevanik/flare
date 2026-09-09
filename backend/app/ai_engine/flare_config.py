"""Independent generation budget and version identity; no key duplication."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from app.config import AISettings
from app.ai_engine.flare_prompts import PROMPT_VERSION, SCHEMA_VERSION


@dataclass(frozen=True)
class FlareSettings:
    max_completion_tokens: int = 1024
    max_request_bytes: int = 32000

    def validate(self):
        if type(self.max_completion_tokens) is not int or not 1 <= self.max_completion_tokens <= 65536:
            raise ValueError('Invalid Flare completion limit')
        if type(self.max_request_bytes) is not int or self.max_request_bytes <= 0:
            raise ValueError('Invalid Flare input limit')

    def revision(self, ai: AISettings) -> str:
        self.validate()
        ai.validate()
        values = [PROMPT_VERSION, SCHEMA_VERSION, ai.model, ai.reasoning_effort,
                  self.max_completion_tokens, self.max_request_bytes, ai.max_sources, ai.max_input_bytes]
        return 'flare-v1:' + sha256(json.dumps(values).encode()).hexdigest()


def load_flare_settings() -> FlareSettings:
    try:
        settings = FlareSettings(int(os.getenv('FLARE_MAX_COMPLETION_TOKENS','1024')),
                                 int(os.getenv('FLARE_MAX_REQUEST_BYTES','32000')))
        settings.validate()
        return settings
    except ValueError:
        raise ValueError('Invalid Flare configuration') from None
