# OPS-006 — production acceptance record

Acceptance date: **15 October 2026 (UTC)**. Production entry point:
`https://flare4u.tech`. This document records sanitized observations from the
completed rollout. It contains no credentials, user email addresses, process
identifiers, tokens, connection strings, or raw production logs.

## Accepted release

| Item | Verified result |
| --- | --- |
| Runtime source | `c8836cdb856cfba4395432df3b355eececf9b63a` (merge of PR [#69](https://github.com/VladimirMalevanik/flare/pull/69)) |
| Immutable release | `azure-c8836cdb856c` |
| Build and publish run | GitHub Actions [run 38764599898](https://github.com/VladimirMalevanik/flare/actions/runs/38764599898), successful |
| Backend package | `flare-backend.zip`, SHA-256 `0c0becad75d84fe6f780e6122bd0ece234e61217dfd8fdabcaf3a50a207cf430` |
| Web package | `flare-web.zip`, SHA-256 `3471592e83d2871d3e1ab30cfac5f974aadb28937df1b2222981662737fb7df0` |
| Package integrity | Both published checksums matched; `unzip -tq` reported no compressed-data errors for either archive |

The immutable packages were deployed through Azure App Service OneDeploy. All
three deployment records reached `status=4`, `complete=true`:

| Service | OneDeploy deployment ID |
| --- | --- |
| Worker | `30bc0ced-ea21-41c1-9d55-a57f5197db6d` |
| API | `f605eaf0-366d-4b3c-8bc0-5d8332cdc19a` |
| Web | `f699f0b7-5f08-4fa2-8a16-998590e79f75` |

An independent check inside each running service found the exact release SHA
`c8836cdb856cfba4395432df3b355eececf9b63a` in `RELEASE_SHA`. The expected
runtime marker was present in each package: `bootstrap_flare_worker.sh` in the
worker, `bootstrap_flare_api.sh` in the API, and `server.js` in the web app.

## Database and worker acceptance

Production readiness and migration checks confirmed schema **0025** on Azure
Database for PostgreSQL **17**, with the application connection using TLS. The
existing point-in-time restore retention is **7 days**. This rollout did not
weaken TLS, expand network access, shorten retention, or create another database.

PR #69 replaced the worker's repeated physical TLS connection creation with a
bounded, process-local PostgreSQL pool. A read-only production acceptance probe
executed against the deployed worker code and returned:

```text
pool_reused_same_backend=true
row_factory_preserved=true
startup_options_preserved=true
rollback_restored_session=true
autocommit_preserved=true
autocommit_profile_isolated=true
closed_connection_replaced=true
acceptance_passed=true
```

The probe verified reuse, caller connection profiles, rollback cleanup, isolation
of the autocommit profile, and replacement of a deliberately closed probe
connection. It did not execute application business writes.

A controlled cold restart produced a different worker process-start marker,
proving that acceptance ran against a new instance rather than the pre-restart
process. After recovery, **30/30** sequential worker readiness requests passed.

The first deployment cold start emitted transient database-path errors while the
service was turning over. They are retained as an observed rollout event rather
than hidden. The final cold worker instance was established after
**2026-10-15 16:25:42 UTC**. From that point, the bounded post-restart log scan
found **0** new `database_unavailable` or
`database_or_storage_unavailable` hits.

Azure PostgreSQL `connections_succeeded` was measured at one-minute resolution
for the 16-minute interval `16:20:00Z`–`16:36:00Z`. The total was 73 connections:
minimum **3/minute**, maximum **7/minute**, mean **4.56/minute**. Before pooling,
the worker produced **173–340 successful connections/minute** after start. The
post-restart result confirms that the physical connection churn was removed; it
is an observed interval, not a permanent traffic or capacity guarantee.

Validation before release included **87 focused tests** and the full
non-integration backend result of **841 passed, 117 skipped, 394 deselected**.
The release workflow repeated the repository's backend and frontend checks before
publishing the packages.

## Provider and public-path acceptance

The configured text provider completed a real request with model
`openai/gpt-oss-20b`; the response passed the application validator and contained
one grounded observation. The configured voice provider completed a real audio
request with model `whisper-large-v3-turbo`; the verified input duration was
3.152 seconds and the result was a non-empty 59-character transcript. Provider
keys and request/response content are not included in this record.

The public release smoke passed against `https://flare4u.tech`. The landing page,
login page, download page, same-origin `/api/health`, and `/api/ready` returned
HTTP 200, and the release smoke script completed successfully.

## Authenticated user scenarios

The following scenarios were exercised through the production UI with a verified
owner account. No account identifier or uploaded content is reproduced here.

- A synthetic note was created, edited, refreshed, and observed to persist. The
  Vault count increased by one. The note remains clearly marked as synthetic.
- A UTM campaign and short redirect were created. Opening the short URL increased
  the recorded click count from zero to one. The campaign was archived; its count
  persisted after refresh.
- Settings persisted with the expected Free-plan state and insight scheduling
  disabled.
- Sources retained the prior Obsidian ZIP result: 13 entries checked, 12 supported
  files imported, and one unsupported entry skipped. Imported content remained in
  the Vault after refresh.
- The Insights page loaded the current persisted state, including the remembered
  item count and disabled schedule.

These checks prove the observed user paths and persistence at acceptance time;
they are not a claim that every optional integration is configured.

## Email configuration

Production reports `EMAIL_VERIFICATION_REQUIRED=true` and the public application
URL is `https://flare4u.tech`. SMTP TLS negotiation and authentication succeeded
in a no-send runtime check. No message was sent during this acceptance run, so
inbox delivery and verification-link completion remain unverified until a
controlled mailbox is used.

## Explicitly unactivated or blocked paths

The accepted core deployment does not turn the following external or incomplete
paths into production-ready features:

- Generic Slack, Google Drive, Gmail, and Notion synchronization remains disabled.
  The API runtime has no source callback URLs, credential-encryption keys, or
  Slack/Google/Notion OAuth credentials configured. External provider-console
  application and consent state was not inspected. The already accepted one-time
  ZIP import is a separate working path.
- Paddle **Sandbox** billing is configured for Pro. Team is disabled and has no
  Team Sandbox price configured; activation also requires the administrator-owned
  Team database policy. No Paddle Live payment behavior is claimed.
- The developer manual-mail form is restricted by an account allowlist. The
  production allowlist is currently empty, so the form is unavailable until the
  owner-approved account mapping is configured privately.
- Email verification is enabled and SMTP transport is valid, but fresh inbox
  delivery and verification-link clicking still require a controlled test
  mailbox.
- The tested `AnalyzeAction` implementation exists, but the active scheduled-only
  Insights policy intentionally does not render it, and `POST /analyze` rejects
  manual runs. Nothing therefore arms the Magic 8 Ball ritual, and
  shake-to-generation is unreachable. Capture and `FunnyEffects` remain mounted,
  but this is not an accepted end-to-end generation path.

No secrets were added to this record, and no unsupported external capability is
reported as accepted.
