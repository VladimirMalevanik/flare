# Block 6A: recording and Whisper boundary

Implemented: browser recording → in-memory Blob; separately, validated audio bytes
→ `VoiceTranscriber` → official Groq SDK → validated `Transcript(text)`.
There is no browser upload or saved voice Note yet. Block 6B waits for teammate
API/DB review. Capture says recording is ready but unsaved; discard/close releases it.
No mock transcription remains in Capture, including API mode.

## Configuration

Backend environment, read on explicit factory invocation:

| Setting | Default | Meaning |
| --- | --- | --- |
| `GROQ_API_KEY` | required | Backend only; excluded from settings repr |
| `VOICE_MODEL` | `whisper-large-v3-turbo` | Only accepted model; no fallback |
| `VOICE_MAX_UPLOAD_BYTES` | `10485760` | 10 MiB maximum, configurable downward |
| `VOICE_MAX_DURATION_SECONDS` | `300` | Five-minute target; maximum configurable target 600 |
| `VOICE_PROVIDER_DEADLINE_SECONDS` | `45` | Overall async deadline and SDK HTTP timeout |

Five minutes suits short capture memos. Ten MiB accommodates compressed browser
recording while bounding memory and upload costs; it deliberately constrains large
uncompressed WAV files. Transcript limit is 30,000 characters by default, within
the existing Note contract's 200,000-character bound. No per-user quotas.
Browser recording stops at five minutes and rejects chunks exceeding 10 MiB.
These browser checks are UX limits, not server security enforcement.

**Duration is not enforced by the 6A provider boundary.** No client duration is
accepted as evidence. Before exposing any upload route, 6B must inspect actual media
server-side and enforce `max_duration_seconds`. Container signatures are shallow
checks, not proof of valid audio, duration, codec or absence of video tracks. No
ffmpeg/parser dependency was added.

## Contract and safety

`AudioInput(content: bytes, filename: str, content_type: str)` derives `size` from
bytes. Validation happens before networking: nonempty bounded bytes, a restricted
basename, MIME/extension agreement and container signature. WEBM, WAV, MP3,
M4A/MP4 and OGG are accepted. MIME codec parameters are narrowly allowed for browser
recordings. User filenames never become paths and are replaced with a fixed
`recording.<extension>` in multipart. No arbitrary URL or server-side URL fetch.

SDK uses the official Groq origin, `max_retries=0`, no proxy environment or redirects,
and `audio.transcriptions.create` with `response_format=json`. Text must be a string,
nonempty after trim and within budget; no LLM rewriting or metadata is retained.
Provider body/exception is not attached to `VoiceError`. Existing status taxonomy is
reused; retryability is information for future orchestration, never an adapter retry.
SDK debug logging is disabled, matching the text boundary.

Audio stays in caller-owned memory. No temporary file, audio storage or DB write is
created; filesystem cleanup tests therefore do not apply. Callers must release audio
references after completion/cancellation; Python does not guarantee memory erasure.

## Required 6B integration after review

1. Agree authenticated FastAPI multipart upload route and frontend data-provider
   transport with teammate. Bound reads while receiving, before accumulating a Blob
   or body in server memory; enforce Origin and workspace membership normally.
2. Inspect media and enforce actual server-side duration before provider invocation.
3. Pass validated bytes to this boundary and persist transcript through the reviewed
   ordinary Note creation path, preserving workspace RLS and immutable versions.
4. Own cancellation/retry policy and temporary audio lifecycle in orchestration:
   audio → transcription → durable Note commit → delete/release source audio.
   Also clean up on terminal errors and timeout; never make audio permanent history.
5. Connect ready Blob to this transport; refresh Vault only after durable Note success.
   Add upload/auth/persistence/cleanup integration tests. Do not invoke Analyze.

No changes here to routes, Database, migrations, Item persistence, auth or workers.

## Verification and optional smoke

```sh
PYTHONPATH=backend python -m pytest -q backend/tests/test_voice.py
node --test frontend/tests/*.test.cjs
python backend/scripts/smoke_groq_voice.py memo.webm --content-type audio/webm --live
```

Smoke requires an explicitly provided backend environment key. It prints transcript
and model to the terminal and never stores them; avoid redirecting sensitive output.
It is not run by automated tests. The original local file remains owned by the user.

SDK reference: https://github.com/groq/groq-python/blob/main/_autodocs/api-reference/audio.md
