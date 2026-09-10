"""Voice-only contracts. Bytes stay in caller-owned memory, never filesystem paths."""
from dataclasses import dataclass, field
import re
from typing import Protocol

from app.ai_engine.errors import ErrorCode


class VoiceError(Exception):
    def __init__(self, code: ErrorCode, *, retryable: bool = False):
        super().__init__(f'Voice transcription failed: {code}')
        self.code = code
        self.retryable = retryable


TYPES = {
    'audio/webm': {'webm'}, 'audio/wav': {'wav'}, 'audio/x-wav': {'wav'},
    'audio/wave': {'wav'}, 'audio/mpeg': {'mp3'}, 'audio/mp3': {'mp3'},
    'audio/mp4': {'mp4', 'm4a'}, 'audio/x-m4a': {'m4a'}, 'audio/ogg': {'ogg'},
}


@dataclass(frozen=True)
class AudioInput:
    content: bytes = field(repr=False)
    filename: str
    content_type: str

    @property
    def size(self) -> int:
        return len(self.content)

    def validate(self, max_bytes: int) -> tuple[str, str]:
        if type(self.content) is not bytes or not 0 < self.size <= max_bytes:
            raise ValueError('Invalid audio size')
        if (not isinstance(self.filename, str)
            or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_. -]{0,199}', self.filename)):
            raise ValueError('Invalid audio filename')
        if not isinstance(self.content_type, str):
            raise ValueError('Invalid audio type')
        # MediaRecorder may append codecs; accept only this narrowly defined parameter.
        match = re.fullmatch(r'([a-zA-Z0-9/+-]+)(?:;\s*codecs=(?:"[a-zA-Z0-9., -]+"|[a-zA-Z0-9.,-]+))?', self.content_type)
        mime = match[1].lower() if match else ''
        ext = self.filename.rsplit('.', 1)[-1].lower()
        if ext not in TYPES.get(mime, set()):
            raise ValueError('Audio type mismatch')
        data = self.content
        valid = {
            'webm': data.startswith(b'\x1aE\xdf\xa3'),
            'wav': data.startswith(b'RIFF') and data[8:12] == b'WAVE',
            'mp3': data.startswith(b'ID3') or (len(data) >= 2 and data[0] == 255 and data[1] & 0xe0 == 0xe0),
            'mp4': data[4:8] == b'ftyp', 'm4a': data[4:8] == b'ftyp',
            'ogg': data.startswith(b'OggS'),
        }[ext]
        if not valid:
            raise ValueError('Audio container mismatch')
        # Never forward user filenames or interpret them as paths.
        return f'recording.{ext}', mime


@dataclass(frozen=True)
class Transcript:
    text: str

    def __post_init__(self):
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text) > 200_000:
            raise ValueError('Invalid transcript')
        object.__setattr__(self, 'text', self.text.strip())


class VoiceTranscriber(Protocol):
    async def transcribe(self, audio: AudioInput) -> Transcript: ...
