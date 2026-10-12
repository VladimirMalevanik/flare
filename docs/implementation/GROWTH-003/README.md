# GROWTH-003 — activate the three X acquisition links

This branch prepares explicit link-measurement consent, withdrawal and restricted
operator tooling. It does **not** enable production collection. Production was
observed disabled on October 10, 2026; no production database rows were inspected.
The local browser has no authenticated Azure session. OPS-005/Vova is deploying
imports to the same services; coordinate the release instead of overwriting it.

## Product and design decisions

- Keep the three prepared links: source `x`, medium `organic_social`, campaign
  `launch_2026_10`, with `utm_content` and `ref` set to `ilyas`, `fedor`, or `flare`.
  `ref` is the existing aggregate grouping field; it is not a reward programme.
- Separate explicit consent from Azure page-count analytics. Existing Azure
  approval does not authorize campaign linking. Notices appear in sequence using
  the existing telemetry banner, buttons, palette and settings spacing.
- Reference lock: `frontend/src/features/telemetry/site-analytics.tsx`,
  `telemetry.module.css` and `analytics-preferences.tsx`. No new design system,
  dependency, icon, animation or tracking provider.
- Only the reviewed notice `measurement-x-v1` / `x-launch-2026-10-v1` can enable
  this UI. Unknown revisions or retention fail closed. GPC/DNT suppress touches;
  storage failure, policy outages and collection failures never block auth.
- Store only the consent/rejection revision in sessionStorage. Campaign values,
  full URLs and content are never persisted client-side. The server owns the
  opaque HttpOnly cookie. Acquisition POSTs have a bounded wait; withdrawal stops
  new calls and follows any pending touch, then clears the anonymous cookie and
  removes account measurement. Pending/unverified users can withdraw without
  gaining access to verified product endpoints.
- The Settings action is account-scoped, not a workspace-wide opt-out. Existing
  ownership and Origin checks remain intact. An expired session is reported as a
  failure rather than falsely claiming account deletion.
  Settings does not infer server account status from tab consent, which is reset
  at the login/register boundary. Only a successful withdrawal reports removal.
- Reports count registrations and ordered product outcomes. They cannot provide
  total clicks or an all-visitor conversion rate. Small cohorts and missing
  observations remain explicit. Do not reinterpret a hidden bucket as zero.

## Proposed settings — Vova approval required

`policy.proposed.json` is a reviewable proposal, not a migration/default/approval.
It uses existing infrastructure and does not create a paid service.

| Setting | Proposed value |
| --- | --- |
| Anonymous cookie, touch and attribution lookback | 7 days |
| Account-linked attribution and facts | 90 days |
| Report window / calendar | Up to 30 days / UTC |
| Minimum disclosed cohort | 5 accounts; any small bucket hides all attribution |
| Global / network touches | 1,000 / 100 per hour |
| Per-reference touch limit | 20 |
| Visitor / network budget row caps | 10,000 / 10,000 |
| Optional intake deadline | 500 ms |
| Allowed referrer domains | t.co, x.com, twitter.com |
| Cleanup owner | Vova, after accepting the operational responsibility |

Changing retention, consent purpose or cohort threshold requires updating the
notice/UI rather than silently changing database values. Numeric admission caps
can be lowered within validated bounds after infrastructure review. Unknown X
referrer domains are rejected rather than widening collection automatically.

## Operator runbook

Run from `backend` with the existing installed runtime: `python -m scripts.growth_ops`.
The tool never loads dotenv, prints connection details, provisions credentials,
grants roles, installs a scheduler or resets quotas. Supply approved connections
through the existing protected operator environment:

- `GROWTH_ADMIN_DATABASE_URL`: existing migration/policy administrator, activation only.
- `GROWTH_WORKER_DATABASE_URL`: existing restricted `flare_worker`, cleanup/reconciliation.
- `GROWTH_REPORT_DATABASE_URL`: separately approved restricted `flare_growth_reporter`,
  aggregate report only; no table SELECT, inheritance, superuser or bypass privileges.

Do not copy these values into source, chat, exports or command-line arguments.

1. Review the proposal without connecting:
   `python -m scripts.growth_ops plan ../docs/implementation/GROWTH-003/policy.proposed.json`.
2. Vova reviews notice, eligibility, allowlist, retention, admission budgets,
   reporting access and disclosure threshold. Provisioning reporting access is a
   separate approved infrastructure action; do not grant it to app/worker.
3. Deploy the accepted source after OPS-005's release, preserving its API/web/worker
   changes. Verify frontend notice and withdrawal endpoint before enabling collection.
4. Install a bounded cleanup pass in an existing scheduler, proposed every hour:
   `python -m scripts.growth_ops maintain cleanup --batch 100 --max-batches 20`.
   Observe job success/failure and resume bounded passes if needed. The SQL return
   omits removed inspection-event counts, so the tool explicitly **does not claim
   cleanup backlog exhaustion**. Deletion may occur at the next successful pass;
   the routine's processing count is not an exact storage audit.
5. Check the existing policy revision and disabled state. Only after approval and
   an operational cleanup schedule run `activate` with the proposal file,
   `--expected-revision none` (or the actual existing revision),
   `--approved-by Vova --cleanup-ready`. Activation is transactional, serialized
   with privacy/intake and rejects an already-enabled or changed policy. It does
   not delete existing references or silently overwrite another activation.
6. Confirm `/api/acquisition/policy` shows the exact enabled notice/revision. Run
   owner-authorized disposable-account smoke: allow a tagged link, register,
   verify email, save a note, manually Analyze, explicitly inspect a Flare/evidence;
   later-day inspection requires waiting for another UTC day. Decline/withdrawal
   and failed-collection cases must keep product behavior intact. Production
   email and Analyze allowances are unchanged. Use synthetic fixtures for full
   attribution disclosure testing rather than manufacturing real performance.
7. Export a past, explicit-timezone window with `report --since ... --until ...
   --basis first --unit account --output NEW_FILE.json` (or `.csv`). The command
   performs bounded worker reconciliation first and refuses export when its batch
   budget is exhausted. Report access is read-only, restricted and function-only.
   JSON includes reconciliation freshness and existing coverage limitations;
   CSV is the fixed formula-safe aggregate export, with no new raw columns.
   Files are created with mode 0600 and existing exports are never overwritten.

Reconciliation's final zero records means no new facts were inserted in that
batch, not proof that optional observations never failed. Retained import facts
can predate activation; signup attribution is never reconstructed retroactively.
Reports are aggregate among registered accounts; unknown/unlinked registrations
and verification provenance are separate from eligible campaign-linked accounts.
Already downloaded exports cannot be recalled after withdrawal.

## Readiness

Validation uses a fresh local PostgreSQL cluster on port 58473; all accounts and
data are synthetic. Checks completed:

- 264 frontend tests and lint pass locally, including consent independence,
  unknown revision/retention rejection, privacy signals, storage failure, pending
  touch withdrawal ordering, expired-session handling and honest account status.
- 153 acquisition/funnel/analytics/auth PostgreSQL checks pass locally. Operator
  tests also run from the repository root, matching CI's collection mode.
- Full CI on `da8fa5f`: 1,043 backend checks in self-managed mode; 1,042 checks and
  one provider-specific skip in Yandex mode; frontend tests/lint/build green.
- Standalone package from `c2025db`, workflow38053721548, builds successfully.
  Browser checks on localhost8417/8418 confirm separate Azure rejection/UTM
  acceptance, bounded `fedor` labels without extra email query values, decline,
  public-to-register navigation and successful account withdrawal. PostgreSQL
  confirms withdrawn eligibility and cleared campaign labels. Desktop and390px
  views fit; no simultaneous fixed notices. Account status wording was then
  corrected and covered by the additional frontend regression.

A further signup boundary regression was fixed: a retained HttpOnly acquisition
cookie alone is insufficient to link registration after rejection, storage loss,
new-tab consent loss, privacy signals or a failed cookie-forget. The frontend adds
only a current explicit opt-in boolean to registration. The server accepts only
JSON true for optional linkage; missing, false and truthy malformed values still
allow normal signup with unknown attribution. Failed registration preserves the
active tab choice for a corrected retry; successful registration/login/logout
clears it. Existing authentication, legal acceptance and verification rules do
not change. Additional HTTP/frontend regressions cover both consent paths.

Final PR checks/build must be green on the accepted head before rollout; older
artifact source is validation evidence, not authorization to deploy that archive.
Approval, production deployment, approved reporting access, cleanup schedule and
real-site smoke remain release gates. Production collection has not been enabled.
