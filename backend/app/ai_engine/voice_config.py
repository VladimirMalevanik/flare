"""Independent voice upload, inspection and provider budgets."""
from dataclasses import dataclass, field
import math
import os


@dataclass(frozen=True)
class VoiceSettings:
    api_key: str | None = field(default=None, repr=False)
    model: str = 'whisper-large-v3-turbo'
    max_upload_bytes: int = 10 * 1024 * 1024
    max_duration_seconds: int = 300
    upload_deadline_seconds: float = 15.0
    media_inspection_timeout_seconds: float = 8.0
    provider_deadline_seconds: float = 45.0
    max_transcript_chars: int = 30_000
    ffprobe_path: str = 'ffprobe'

    def validate(self) -> None:
        if self.model != 'whisper-large-v3-turbo':
            raise ValueError('Invalid voice model')
        for value, maximum in ((self.max_upload_bytes, 10 * 1024 * 1024),
                               (self.max_duration_seconds, 600),
                               (self.max_transcript_chars, 200_000)):
            if type(value) is not int or not 0 < value <= maximum:
                raise ValueError('Invalid voice budget')
        for value, maximum in (
            (self.upload_deadline_seconds, 60.0),
            (self.media_inspection_timeout_seconds, 30.0),
            (self.provider_deadline_seconds, 120.0),
        ):
            if (type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 < value <= maximum):
                raise ValueError('Invalid voice deadline')
        if (not isinstance(self.ffprobe_path, str) or not self.ffprobe_path
            or len(self.ffprobe_path) > 500 or '\x00' in self.ffprobe_path):
            raise ValueError('Invalid ffprobe path')


def load_voice_settings() -> VoiceSettings:
    try:
        settings = VoiceSettings(
            api_key=os.getenv('VOICE_GROQ_API_KEY'),
            model=os.getenv('VOICE_MODEL', 'whisper-large-v3-turbo'),
            max_upload_bytes=int(os.getenv('VOICE_MAX_UPLOAD_BYTES', str(10 * 1024 * 1024))),
            max_duration_seconds=int(os.getenv('VOICE_MAX_DURATION_SECONDS', '300')),
            upload_deadline_seconds=float(os.getenv('VOICE_UPLOAD_DEADLINE_SECONDS', '15')),
            media_inspection_timeout_seconds=float(os.getenv('VOICE_MEDIA_INSPECTION_TIMEOUT_SECONDS', '8')),
            provider_deadline_seconds=float(os.getenv('VOICE_PROVIDER_DEADLINE_SECONDS', '45')),
            max_transcript_chars=int(os.getenv('VOICE_MAX_TRANSCRIPT_CHARS', '30000')),
            ffprobe_path=os.getenv('VOICE_FFPROBE_PATH', 'ffprobe'),
        )
        settings.validate()
        return settings
    except (ValueError, TypeError):
        raise ValueError('Invalid voice configuration') from None
