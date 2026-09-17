import asyncio
import json

import pytest

from app.ai_engine.media_inspection import (
    FfprobeMediaInspector,
    MediaInspectionError,
    _MAX_PROBE_OUTPUT_BYTES,
    _probe_arguments,
)
from app.ai_engine.voice import AudioInput


AUDIO = AudioInput(b"\x1aE\xdf\xa3safe", "memo.webm", "audio/webm")


def inspect(payload: object, *, limit: int = 300) -> float:
    async def runner(content: bytes) -> bytes:
        assert content == AUDIO.content
        return json.dumps(payload).encode()

    return asyncio.run(
        FfprobeMediaInspector(
            max_duration_seconds=limit,
            timeout_seconds=1,
            probe_runner=runner,
        ).duration_seconds(AUDIO)
    )


def test_duration_accepts_audio_only_and_uses_longest_probe_duration():
    assert inspect(
        {
            "streams": [{"codec_type": "audio", "duration": "12.25"}],
            "format": {"duration": "12.5"},
        }
    ) == 12.5


def test_duration_is_derived_from_packets_for_streamed_browser_audio():
    assert inspect(
        {
            "packets": [
                {"pts_time": "0.000", "duration_time": "0.020"},
                {"pts_time": "2.980", "duration_time": "0.020"},
            ],
            "streams": [{"codec_type": "audio"}],
            "format": {},
        }
    ) == 3.0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"streams": []},
        {"streams": [{"codec_type": "video", "duration": "1"}]},
        {"streams": [{"codec_type": "audio", "duration": None}], "format": {}},
        {"streams": [{"codec_type": "audio", "duration": "nan"}]},
        {"streams": [{"codec_type": "audio", "duration": "-1"}]},
        b"not-json",
    ],
)
def test_invalid_or_non_audio_probe_output_is_rejected(payload):
    async def runner(_: bytes) -> bytes:
        return payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    inspector = FfprobeMediaInspector(300, 1, probe_runner=runner)
    with pytest.raises(MediaInspectionError, match="invalid_audio"):
        asyncio.run(inspector.duration_seconds(AUDIO))


def test_duration_limit_is_enforced_from_media_not_client_metadata():
    with pytest.raises(MediaInspectionError, match="audio_too_long"):
        inspect(
            {
                "streams": [{"codec_type": "audio", "duration": "300.001"}],
                "format": {"duration": "300.001"},
            }
        )


def test_runner_failure_is_sanitized():
    async def runner(_: bytes) -> bytes:
        raise ValueError("PRIVATE AUDIO DETAIL")

    inspector = FfprobeMediaInspector(300, 1, probe_runner=runner)
    with pytest.raises(MediaInspectionError) as caught:
        asyncio.run(inspector.duration_seconds(AUDIO))
    assert caught.value.code == "invalid_audio"
    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_missing_probe_has_stable_configuration_error():
    inspector = FfprobeMediaInspector(
        max_duration_seconds=300,
        timeout_seconds=1,
        ffprobe_path="/definitely/missing/ffprobe",
    )
    with pytest.raises(MediaInspectionError, match="inspection_unavailable"):
        asyncio.run(inspector.duration_seconds(AUDIO))


def test_probe_is_stdin_only_and_restricts_untrusted_demuxers():
    arguments = _probe_arguments()
    assert arguments[0:2] == ("-v", "error")
    assert arguments[arguments.index("-protocol_whitelist") + 1] == "pipe"
    formats = arguments[arguments.index("-format_whitelist") + 1].split(",")
    assert set(formats) == {"matroska", "webm", "wav", "mp3", "mov", "ogg"}
    codecs = arguments[arguments.index("-codec_whitelist") + 1].split(",")
    assert {"opus", "vorbis", "aac", "mp3", "pcm_s16le"}.issubset(codecs)
    assert arguments[arguments.index("-max_streams") + 1] == "2"
    assert arguments[arguments.index("-max_probe_packets") + 1] == "500"
    assert arguments[arguments.index("-probesize") + 1] == "10485760"
    entries = arguments[arguments.index("-show_entries") + 1]
    assert "packet=pts_time,dts_time,duration_time" in entries
    assert "http" not in arguments
    assert "https" not in arguments
    assert "file" not in arguments
    assert arguments[-1] == "pipe:0"


def test_playlist_content_is_rejected_before_probe_even_with_audio_mime():
    calls = 0

    async def runner(_: bytes) -> bytes:
        nonlocal calls
        calls += 1
        return b'{}'

    playlist = AudioInput(
        b"#EXTM3U\n#EXTINF:1,secret\nfile:///etc/passwd\n",
        "memo.mp3",
        "audio/mpeg",
    )
    inspector = FfprobeMediaInspector(300, 1, probe_runner=runner)
    with pytest.raises(MediaInspectionError, match="invalid_audio"):
        asyncio.run(inspector.duration_seconds(playlist))
    assert calls == 0


def test_native_probe_never_receives_bytes_above_its_own_limit():
    calls = 0

    async def runner(_: bytes) -> bytes:
        nonlocal calls
        calls += 1
        return b'{}'

    oversized = AudioInput(
        AUDIO.content + b"x",
        AUDIO.filename,
        AUDIO.content_type,
    )
    inspector = FfprobeMediaInspector(
        300,
        1,
        max_upload_bytes=len(AUDIO.content),
        probe_runner=runner,
    )
    with pytest.raises(MediaInspectionError, match="invalid_audio"):
        asyncio.run(inspector.duration_seconds(oversized))
    assert calls == 0


def test_probe_output_is_bounded_and_process_is_reaped():
    class Stdin:
        def write(self, _content):
            pass

        async def drain(self):
            pass

        def close(self):
            pass

    class Stdout:
        calls = 0

        async def read(self, _size):
            self.calls += 1
            chunks_before_limit = _MAX_PROBE_OUTPUT_BYTES // 8192
            return b"x" * 8192 if self.calls <= chunks_before_limit + 1 else b""

    class Process:
        stdin = Stdin()
        stdout = Stdout()
        returncode = None
        killed = False

        def kill(self):
            self.killed = True

        async def wait(self):
            self.returncode = -9

    process = Process()
    with pytest.raises(MediaInspectionError, match="invalid_audio"):
        asyncio.run(FfprobeMediaInspector._communicate_bounded(process, b"safe"))
    assert process.killed is True
    assert process.returncode == -9
