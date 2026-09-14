# Voice transcription

Flare now has the production safety pieces for the voice path: browser recording
keeps one bounded Blob in memory, `FfprobeMediaInspector` checks the real media
tracks and duration through stdin, and `VoiceTranscriptService` saves an already
validated transcript as an immutable `audio` item and chunk in PostgreSQL. Source
audio is never written to a file or database. Direct placeholder `audio` creation
through `POST /items` is rejected, including in mock mode.

The final HTTP/provider handoff is deliberately gated until the product owner
explicitly authorizes sending recordings to Groq Whisper. The shipped application
must show that disclosure before an upload and the API must verify the matching
consent signal before reading a body or calling Groq. Until that gate is connected,
recordings can be discarded but cannot produce a fake saved transcript.

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

The backend image installs ffprobe. Inspection receives the bounded bytes over
stdin with stderr discarded, checks that every reported stream is audio, requires
a finite positive duration, and rejects media longer than the configured limit.
It allows only the `pipe` protocol, a small container/codec allowlist, at most two
streams and 500 probe packets, and caps machine-readable output at 64 KiB. Playlist,
URL and local-file protocols cannot be followed. It never trusts a browser-supplied
duration, MIME label or container signature alone.

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

The old Dashboard recorder which saved invented demo transcripts was removed.
File actions now open the shared bounded import flow. The microphone action is
disabled and labelled as coming soon until the consent-gated provider handoff is
enabled, so the shipped UI does not record audio it cannot save. Mock mode rejects
attempts to manufacture an audio item. Vault already lists existing `audio` items
and opens their stored transcript; transcript edits publish another immutable version
through the ordinary item-edit path.

Analytics stores only bounded action names and IDs: voice start/stop in the browser,
`capture_submitted` after a durable item exists, and the server-owned `item_created`
outcome with `item_type=audio`. Audio and transcript text are not analytics fields.

## Verification

```sh
PYTHONPATH=backend python -m pytest -q \
  backend/tests/test_voice.py \
  backend/tests/test_voice_media_inspection.py \
  backend/tests/test_voice_service.py
node --test frontend/tests/voice-recorder.test.cjs
```

The opt-in local provider smoke remains separate from the web product. It requires
`--live`, a worker-selected dotenv file and a local audio path. It prints the
transcript, so it must not be redirected into retained logs.
