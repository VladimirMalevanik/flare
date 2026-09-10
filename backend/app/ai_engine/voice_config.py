"""Independent voice budgets; duration enforcement belongs to 6B media inspection."""
from dataclasses import dataclass, field
import math
import os


@dataclass(frozen=True)
class VoiceSettings:
    api_key: str | None = field(default=None, repr=False)
    model: str = 'whisper-large-v3-turbo'
    max_upload_bytes: int = 10 * 1024 * 1024
    max_duration_seconds: int = 300
    provider_deadline_seconds: float = 45.0
    max_transcript_chars: int = 30_000

    def validate(self) -> None:
        if self.model != 'whisper-large-v3-turbo':
            raise ValueError('Invalid voice model')
        for value, maximum in ((self.max_upload_bytes, 10 * 1024 * 1024),
                               (self.max_duration_seconds, 600),
                               (self.max_transcript_chars, 200_000)):
            if type(value) is not int or not 0 < value <= maximum:
                raise ValueError('Invalid voice budget')
        if (type(self.provider_deadline_seconds) not in (int, float)
            or not math.isfinite(self.provider_deadline_seconds)
            or self.provider_deadline_seconds <= 0):
            raise ValueError('Invalid voice deadline')


def load_voice_settings() -> VoiceSettings:
    try:
        settings = VoiceSettings(
            api_key=os.getenv('GROQ_API_KEY'),
            model=os.getenv('VOICE_MODEL', 'whisper-large-v3-turbo'),
            max_upload_bytes=int(os.getenv('VOICE_MAX_UPLOAD_BYTES', str(10 * 1024 * 1024))),
            max_duration_seconds=int(os.getenv('VOICE_MAX_DURATION_SECONDS', '300')),
            provider_deadline_seconds=float(os.getenv('VOICE_PROVIDER_DEADLINE_SECONDS', '45')),
        )
        settings.validate()
        return settings
    except (ValueError, TypeError):
        raise ValueError('Invalid voice configuration') from None
