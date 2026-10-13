# API-006 — Team projects

Implementation started 12 October 2026; review record updated 13 October (Moscow).
The first interface interpreted Team as a task manager. The owner clarified on
13 October that Team collects participants' notes and produces shared Flares.
[API-008](../API-008/README.md) supersedes that task-oriented interface and its
product acceptance flow. The technical/validation history below is retained for
the existing membership, billing, schema and compatibility contracts. No real
invitations, paid resources or production credentials were used by this work.

## Delivered behavior

- One additional, empty team project per active Team license by default. The
  paying user's initial personal workspace sponsors the license; personal content
  is never automatically copied or shared. Invited colleagues need individual
  verified Flare accounts, not individual subscriptions.
- Projects are selected explicitly per browser tab through `?project=<uuid>`.
  API requests carry a checked workspace parameter. Authentication cookies stay
  unchanged. Server authorization checks membership again; client headers and
  cached roles do not authorize access.
- Existing shared memberships are preserved as legacy shared workspaces. They
  do not acquire Team administration or invitations automatically.
- Owner/editor/viewer roles. Owners manage invites and roles, rename the project
  and transfer ownership. Editors add/edit materials and tasks. Viewers read.
  Removing or leaving a project preserves the account and personal workspace.
  The last owner must transfer ownership before leaving.
- Email-bound, hashed, one-use invitations, seven-day expiry, explicit sharing
  acknowledgement and explicit acceptance. Wrong account, canceled/expired
  token and obsolete owner's invitations fail. Resends replace the old token.
  Pending invitations reserve seats. SMTP failures cancel the token and return
  a redacted, recoverable error. No automatic repeat mail sends.
- Existing accounts whose email verification was bypassed must actually verify
  their email before creating or joining Team. This does not weaken normal auth.
- Invitation links use URL fragments. The receiving tab retains an invitation
  for at most 30 minutes through login, registration and verification; it clears
  it after joining or choosing “Not now”. Logged-in users see the project, sender
  and role before accepting. The preview is bound to the recipient's email.
- Tasks have title, description, status, optional member assignee and immutable
  server-authored creator ID/name/time. History records who changed which fields.
  Optimistic version checks preserve a conflicting draft. New-task and project
  creation use stable request UUIDs to recover an uncertain response.
- Task lists use bounded keyset pages; single-task reload does not depend on the
  first page. JSON task export preserves authors and remains available to project
  members after subscription expiry. The existing Vault export remains separate.
- Task changes never enqueue AI. The established scheduled-only analysis and
  daily workspace quota remain; seats do not multiply the daily allowance.
- Expired/paused/canceled/past-due/conflicting billing makes Team read-only while
  retaining read/export access. Owners can still manage membership/privacy.
  Scheduler admission and job evidence checks reject inactive Team projects,
  without rejecting unrelated personal-workspace queues or resetting quotas.
- OAuth callbacks recover a team workspace only from the caller-bound, unexpired
  provider state, not an arbitrary workspace argument. Trusted app redirects
  preserve the project selection.

## Limits and database design

`team_policy` is administrator-only deployment configuration. It ships disabled
with no Team price. Defaults are a bounded pilot, not a public pricing promise:

| Resource | Default | Enforcement |
| --- | --- | --- |
| Team projects per license | 1 | Serialized license row + atomic count |
| Members | 10, owner included | Members plus unexpired pending invitations |
| Active tasks | 1,000 | Serialized project write |
| Task rows including deletion window | 2,000 | Hard storage cap; prevents deletion churn |
| Deleted-task retention | 30 days | Retired before subsequent task creation; history cascades |
| Task description | 10,000 UTF-8 bytes | API and database validation |
| Recent history per task | 50 entries | Pruned after edits and unassignment |
| Invitation attempts | 20 per rolling 24 hours | Includes resends and canceled attempts |
| Same recipient resend | At least 60 seconds | Serialized project checks |
| Invitation history | 30 days; UI last 100 | Bounded retirement on subsequent invite |
| Membership audit | Last 1,000 events per project | Pruned on membership changes |
| Material documents | 5,000, retained documents included | Database trigger and project counter |
| Material text storage | 100 MiB, retained versions included | UTF-8 counter guarded by project lock |
| Memberships per account | At most 100 | Join admission |
| Task list page | 100 plus one lookahead | Complete timestamp/UUID cursor |
| Team request JSON | 64 KiB / 3 seconds | ASGI guard, including chunked bodies |
| Browser Team requests | 12 seconds including JSON parsing | Late/ignored-abort results fenced |

Tables: `team_policy`, `team_projects`, `team_invitations`, `team_tasks`,
`team_task_history`, `team_member_events`. They use FORCE RLS and have no direct
API/worker table access. Task actor snapshots survive member departure. Assignees
must belong to the project; removal clears assignment and increments its version.
Mutations serialize through the project row; ready document-version rules remain.
Document and byte counters update in the same publication transaction, so an
over-quota publication rolls back its document and counters together. They avoid
re-reading all saved text on every imported chunk. Operator restore/imports that
disable triggers must recompute these counters before enabling Team writes.

Self-managed PostgreSQL uses an inert, private `flare_team_executor` role, never
a runtime admin connection. Its column UPDATE grants on workspace name and
billing status allow row locks; public Team functions do not modify billing rows.
Migration checks reject unsafe role attributes/memberships and retire temporary
ownership authority.

Managed PostgreSQL retains the established `flare_owner` function owner. An empty,
private `flare_team_scope` schema marks the Team function family's pinned
`search_path=pg_catalog,public,flare_team_scope,pg_temp`. Other owner capabilities
retain their existing hardened search paths without that schema. A forged caller
search path therefore cannot carry the broader membership view into another
security-definer capability. Readiness verifies both pins, the empty marker schema,
private grants, 25 exact Team functions and worker admission guards. This requires
no new managed-cloud role, superuser custom-GUC privileges or changes to worker
application names/monitoring. Function-local search paths restore prior settings;
see [PostgreSQL CREATE FUNCTION](https://www.postgresql.org/docs/17/sql-createfunction.html).

Both profiles need normal migration ownership; application and worker roles cannot
run this migration. Forward-only migration: restore a reviewed backup instead of
dropping team membership or authorship history.

## Integration with DATA-003 / PR57

Sources PR57 is accepted into main. Team now follows schema0023 with revision0024;
there is one0022→0023→0024 migration line. API-007 records the current combined
validation and rollout handoff. Historical Team-only results stay in validation.md.

When0023 is present before0024, migration installs source integration hooks:
removal/downgrade immediately clears that user's protected credentials, callback
states and unfinished draft cursors, cancels leases and preserves published Vault
snapshots. Source worker admission retires inactive Team connections and stops
their jobs; renewing Team requires reconnecting a source whose authorization was
retired. Source publication still observes immutable snapshots and conflict guards.
An integration failure rolls the transaction back and returns a bounded error;
it never reports membership removal while leaving a partial committed mutation.

## Billing and activation boundary

Team entitlement comes only from stored, authenticated Paddle Sandbox snapshots
with the configured Team price, quantity1, finite active/trial period and no
expired scheduled pause/cancel or watermark conflict. Team extends the existing
bounded entitlement calculator; browser checkout completion never grants access.
The public SDK and one checkout lock are shared with Pro. The server issues a
Team-specific checkout intent; the Team price can come from that intent, so an
additional frontend price variable is not required. All existing Pro behavior
and Sandbox-only rejection of Live tokens remain.

Fresh Team checkout is available to an eligible verified owner with no active
paid subscription in their paying personal workspace. **Self-service Pro-to-Team
proration/upgrade is not implemented**: it would require provider-side API setup
and a reviewed billing change. Existing provider-driven price-change events can
confirm Team on the same bound subscription. The UI must not start a second
subscription while Pro or Team is already active. No Team price or trial duration
was invented and no actual Paddle entity was created by this task.

Vova activation checklist after owner acceptance:

1. Verify the resolved0023→0024 lineage, backup/restore, restricted
   roles, preserved-data upgrades and exact API/web source.
2. Create/select a distinct existing-account Paddle **Sandbox** Team recurring
   price. Review the public offer and pilot limits; no Live switch is included.
3. Configure server `PADDLE_TEAM_PRICE_ID` and `TEAM_ENABLED=true`, retaining the
   existing signed webhook destination and secret mechanism. Never put the secret
   in source or a browser variable.
4. Set the same public price on administrator-owned `team_policy`, explicitly
   review numeric limits and set `enabled=true`. Runtime cannot edit this row.
5. Configure/verify existing `APP_PUBLIC_URL`, `SMTP_URL`, `EMAIL_FROM`; production
   requires HTTPS and SMTP even if legacy email verification was disabled. Ensure
   real email verification is possible for bypassed accounts.
6. Deploy only reviewed existing-resource API/web packages. Verify readiness and
   one real Sandbox subscription → empty project → two consenting accounts →
   invite/join → notes/tasks → role removal → subscription expiry/read/export.
   Test provider callbacks and source retirement only with consenting accounts.
7. Record operational storage/CPU/queue capacity, daily provider budget, retention
   maintenance and rollback boundaries before enabling Team in production.

Leave Team disabled if these gates are incomplete. No background worker was
started against production and no actual customer account was connected.

## Design references and checks

Primary visual reference: existing Flare application. Preserve Inter, light/dark
canvas and surface tokens, blue actions, existing Select/popover and Dialog,
sidebar proportions and understated borders. Borrow only the members/invitations
placement from [Linear](https://linear.app/docs/invite-members) and
[Notion](https://www.notion.com/help/add-members-admins-guests-and-groups).
No new display font, decorative gradient, invented icon system or landing edits.
Creator, assignee and time appear together under each task; compact inline usage
shows the limits relevant to the user's next action. Refero craft references and
frontend-design guided focus, keyboard and narrow-screen behavior. Screenshots,
browser evidence and exact final test results belong in validation.md.
