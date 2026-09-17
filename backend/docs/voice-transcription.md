# Voice transcription

Flare's production voice path keeps one bounded browser Blob in memory,
`FfprobeMediaInspector` checks the real media tracks and duration through stdin,
and `POST /voice/transcribe` sends valid audio to Groq Whisper. After Groq returns,
`VoiceTranscriptService` saves the validated transcript as an immutable `audio`
item and chunk in PostgreSQL. Source audio is never written to a file or database.
Direct placeholder `audio` creation through `POST /items` is rejected, including
in mock mode.

The endpoint requires an authenticated user who has accepted the current legal
documents. The Privacy Policy names Groq and describes the third-party AI
processing before a user can upload a recording.

## Configuration

Voice uses a distinct API-process credential. It may belong to the same Groq
account as the analysis worker key, but a separate secret lets either path be
rotated or revoked independently.

| Setting | Default | Meaning |
| --- | --- | --- |
| `VOICE_GROQ_API_KEY` | required for provider activation | API-only Groq credential |
| `VOICE_MODEL` | `whisper-large-v3-turbo` | Only accepted voice model |
| `VOICE_MAX_UPLOAD_BYTES` | `10485760` | Maximum recording size, capped at 10 MiB |
| `VOICE_MAX_DURATION_SECONDS` | `300` | Maximum measured duration, hard cap 600 seconds |
| `VOICE_UPLOAD_DEADLINE_SECONDS` | `15` | Planned total body-read deadline, hard cap 60 seconds |
| `VOICE_MEDIA_INSPECTION_TIMEOUT_SECONDS` | `8` | ffprobe deadline, hard cap 30 seconds |
| `VOICE_PROVIDER_DEADLINE_SECONDS` | `45` | Provider/SDK deadline, hard cap 120 seconds |
| `VOICE_MAX_TRANSCRIPT_CHARS` | `30000` | Transcript bound, hard cap 200,000 characters |
| `VOICE_FFPROBE_PATH` | `ffprobe` | Operator-controlled executable path |

The backend image installs ffprobe. The Azure built-in runtime instead bootstraps
a pinned FFmpeg 7.0.2 static `ffprobe` into the persistent `/home` volume and
verifies both the archive and executable with cryptographic checksums. Inspection
receives the bounded bytes over stdin with stderr discarded, checks that every
reported stream is audio, and rejects media longer than the configured limit.
For streamed browser containers that omit header duration, it derives the end time
from ffprobe packet timestamps. It allows only the `pipe` protocol, a small
container/codec allowlist, at most two streams and 500 initial probe packets, and
caps compact machine-readable output at 4 MiB. Playlist, URL and local-file
protocols cannot be followed. It never trusts a browser-supplied duration, MIME
label or container signature alone.

## Existing provider boundary

`AudioInput(content, filename, content_type)` validates nonempty bounded bytes, a
restricted basename, MIME/extension agreement, and the WEBM, WAV, MP3, M4A/MP4 or
OGG container signature before networking. Browser codec parameters are narrowly
accepted. The Groq adapter replaces the supplied filename with a fixed safe name,
uses the official Groq origin, disables proxy-environment trust and redirects,
sets `max_retries=0`, and validates a nonempty bounded text response.

Provider errors have stable codes and never retain provider bodies or exception
text. The adapter writes neither audio nor transcript to logs. It is intentionally
separate from `VoiceTranscriptService`, so the provider call completes before the
short PostgreSQL transaction begins.

## Browser behavior

`VoiceRecorder` stops at five minutes, rejects accumulated chunks above 10 MiB,
stops microphone tracks on success, error, cancel and component disposal, and
ignores stale callbacks. These are UX limits; the server-side byte, timeout and
ffprobe checks remain authoritative.

The old Dashboard recorder which saved invented demo transcripts was removed. The
microphone action now records real audio and calls the production voice endpoint;
file actions use the shared bounded import flow. Mock mode rejects attempts to
manufacture an audio item. Vault lists `audio` items and opens their stored
transcript; transcript edits publish another immutable version through the ordinary
item-edit path.

Analytics stores only bounded action names and IDs: voice start/stop in the browser,
`capture_submitted` after a durable item exists, and the server-owned `item_created`
outcome with `item_type=audio`. Audio and transcript text are not analytics fields.

## Verification

```sh
PYTHONPATH=backend python -m pytest -q \
  backend/tests/test_voice.py \
  backend/tests/test_voice_media_inspection.py \
  backend/tests/test_voice_api.py \
  backend/tests/test_groq_voice_adapter.py \
  backend/tests/test_voice_service.py
node --test frontend/tests/voice-recorder.test.cjs
python backend/deploy/ensure_ffprobe.py --destination /tmp/flare-ffprobe
PYTHONPATH=backend python backend/scripts/check_voice_runtime.py \
  --ffprobe-path /tmp/flare-ffprobe
```

The opt-in local provider smoke remains separate from normal tests. It requires
`--live`, a worker-selected dotenv file and a local audio path. It prints the
transcript, so it must not be redirected into retained logs. A production smoke
should create a temporary user, upload a public sample, verify a durable `audio`
item, delete that item, and log out.
