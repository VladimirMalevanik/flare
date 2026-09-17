#!/usr/bin/env python3
"""Exercise the pinned native ffprobe with generated in-memory audio."""

from __future__ import annotations

import argparse
import asyncio
from io import BytesIO
from pathlib import Path
import struct
import wave

from app.ai_engine.media_inspection import FfprobeMediaInspector
from app.ai_engine.voice import AudioInput


def _wav_seconds(seconds: float = 1.0, sample_rate: int = 16_000) -> bytes:
    frames = round(seconds * sample_rate)
    output = BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(sample_rate)
        recording.writeframes(struct.pack("<h", 0) * frames)
    return output.getvalue()


async def _check(ffprobe_path: Path) -> None:
    duration = await FfprobeMediaInspector(
        max_duration_seconds=5,
        timeout_seconds=10,
        max_upload_bytes=1024 * 1024,
        ffprobe_path=str(ffprobe_path),
    ).duration_seconds(AudioInput(_wav_seconds(), "runtime.wav", "audio/wav"))
    if not 0.99 <= duration <= 1.01:
        raise RuntimeError(f"unexpected ffprobe duration: {duration}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffprobe-path", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(_check(args.ffprobe_path.resolve()))
    print("voice runtime check passed")


if __name__ == "__main__":
    main()
