"""Bounded ffprobe inspection for untrusted, in-memory voice recordings."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
from typing import Awaitable, Callable, Literal, Protocol

from app.ai_engine.voice import AudioInput


MediaErrorCode = Literal[
    "invalid_audio",
    "audio_too_long",
    "inspection_timeout",
    "inspection_unavailable",
]


class MediaInspectionError(Exception):
    """Stable media failures which never retain probe stderr or source bytes."""

    def __init__(self, code: MediaErrorCode, *, retryable: bool = False):
        super().__init__(f"Audio inspection failed: {code}")
        self.code = code
        self.retryable = retryable


class VoiceMediaInspector(Protocol):
    async def duration_seconds(self, audio: AudioInput) -> float: ...


ProbeRunner = Callable[[bytes], Awaitable[bytes]]
# Ten minutes (the configuration hard cap) of compact packet timestamps from
# the allowed audio codecs stays below this ceiling. The cap also prevents a
# malformed file from making ffprobe's metadata output grow without bound.
_MAX_PROBE_OUTPUT_BYTES = 4 * 1024 * 1024
_ALLOWED_DEMUXERS = "matroska,webm,wav,mp3,mov,ogg"
_ALLOWED_CODECS = (
    "opus,vorbis,aac,mp3,pcm_u8,pcm_s16le,pcm_s24le,pcm_s32le,"
    "pcm_f32le,pcm_f64le"
)


def _probe_arguments() -> tuple[str, ...]:
    """Allow only local stdin and known audio containers inside ffprobe."""
    return (
        "-v",
        "error",
        "-protocol_whitelist",
        "pipe",
        "-format_whitelist",
        _ALLOWED_DEMUXERS,
        "-codec_whitelist",
        _ALLOWED_CODECS,
        "-max_streams",
        "2",
        "-max_probe_packets",
        "500",
        "-probesize",
        "10485760",
        "-show_entries",
        (
            "stream=codec_type,duration:format=duration:"
            "packet=pts_time,dts_time,duration_time"
        ),
        "-of",
        "json=compact=1",
        "-i",
        "pipe:0",
    )


@dataclass(frozen=True)
class FfprobeMediaInspector:
    """Validate tracks and duration without writing uploaded audio to a file."""

    max_duration_seconds: int
    timeout_seconds: float
    max_upload_bytes: int = 10 * 1024 * 1024
    ffprobe_path: str = "ffprobe"
    probe_runner: ProbeRunner | None = None

    async def duration_seconds(self, audio: AudioInput) -> float:
        try:
            # MIME is only a hint. Require the matching container signature
            # before invoking the native parser as a second line of defense.
            audio.validate(self.max_upload_bytes)
            payload = await (
                self.probe_runner(audio.content)
                if self.probe_runner is not None
                else self._run_probe(audio.content)
            )
            decoded = json.loads(payload)
            streams = decoded.get("streams") if isinstance(decoded, dict) else None
            format_info = decoded.get("format") if isinstance(decoded, dict) else None
            packets = decoded.get("packets") if isinstance(decoded, dict) else None
            if not isinstance(streams, list) or not streams:
                raise ValueError
            if any(
                not isinstance(stream, dict) or stream.get("codec_type") != "audio"
                for stream in streams
            ):
                raise ValueError

            durations: list[float] = []
            for candidate in [
                *(stream.get("duration") for stream in streams),
                format_info.get("duration") if isinstance(format_info, dict) else None,
            ]:
                try:
                    value = float(candidate)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value) and value > 0:
                    durations.append(value)

            # Containers recorded by browsers are commonly streamed and may not
            # publish a duration in their headers.  ffprobe still emits bounded
            # packet timestamps while reading stdin, so derive the media end
            # without ever writing the recording to disk.
            if packets is not None:
                if not isinstance(packets, list):
                    raise ValueError
                for packet in packets:
                    if not isinstance(packet, dict):
                        raise ValueError
                    starts: list[float] = []
                    for key in ("pts_time", "dts_time"):
                        try:
                            start = float(packet.get(key))
                        except (TypeError, ValueError):
                            continue
                        if math.isfinite(start) and start >= 0:
                            starts.append(start)
                    if not starts:
                        continue
                    try:
                        packet_duration = float(packet.get("duration_time", 0))
                    except (TypeError, ValueError):
                        packet_duration = 0
                    if not math.isfinite(packet_duration) or packet_duration < 0:
                        packet_duration = 0
                    end = max(starts) + packet_duration
                    if end > 0:
                        durations.append(end)
            if not durations:
                raise ValueError
            duration = max(durations)
        except MediaInspectionError:
            raise
        except (ValueError, TypeError, json.JSONDecodeError):
            raise MediaInspectionError("invalid_audio") from None

        if duration > self.max_duration_seconds:
            raise MediaInspectionError("audio_too_long")
        return duration

    async def _run_probe(self, content: bytes) -> bytes:
        try:
            process = await asyncio.create_subprocess_exec(
                self.ffprobe_path,
                *_probe_arguments(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except (FileNotFoundError, PermissionError, OSError):
            raise MediaInspectionError("inspection_unavailable") from None

        try:
            stdout = await asyncio.wait_for(
                self._communicate_bounded(process, content),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise MediaInspectionError("inspection_timeout", retryable=True) from None
        if process.returncode != 0:
            raise MediaInspectionError("invalid_audio")
        return stdout

    @staticmethod
    async def _communicate_bounded(
        process: asyncio.subprocess.Process,
        content: bytes,
    ) -> bytes:
        if process.stdin is None or process.stdout is None:
            raise MediaInspectionError("inspection_unavailable")

        async def feed() -> None:
            try:
                process.stdin.write(content)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

        async def read() -> bytes:
            output = bytearray()
            while True:
                chunk = await process.stdout.read(8192)
                if not chunk:
                    return bytes(output)
                output.extend(chunk)
                if len(output) > _MAX_PROBE_OUTPUT_BYTES:
                    raise MediaInspectionError("invalid_audio")

        try:
            _, stdout = await asyncio.gather(feed(), read())
            await process.wait()
            return stdout
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
