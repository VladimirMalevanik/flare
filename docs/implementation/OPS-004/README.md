# OPS-004 — Flare browser visits in Azure Application Insights

Owner requested connection on 6 October 2026. This scope is browser page views,
not authoritative signup/activation reporting. Existing first-party acquisition,
authentication, database, worker and Paddle Sandbox flows stay independent.

## Collection

The pinned official `@microsoft/applicationinsights-web` 3.4.4 SDK is bundled
locally and imported only after separate explicit analytics consent. Accept and
reject have equal visibility. Change the choice in Settings → Data & Privacy or
on `/analytics`. Global Privacy Control / Do Not Track keep collection off.

Only predefined static section routes become page views. A final fail-closed
initializer accepts only `PageviewData`, reconstructs its envelope after SDK
context enrichment, and drops account/workspace identity, content, arbitrary
properties, referrer, query/hash, private paths, document titles and all other
telemetry. AJAX/fetch, errors, promises, automatic routing, page visit timing,
persisted buffers, SDK stats and remote SDK configuration are disabled. CSP
allows only the exact configured commercial Azure ingestion HTTPS origin in
addition to existing Paddle Sandbox origins; no Azure/CDN wildcard is added.

Anonymous IDs belong to separate `ai_user_flare_site_analytics` and
`ai_session_flare_site_analytics` cookies. Browser ID and consent expire in 30
days; sessions expire after 30 minutes of inactivity or 24 hours. Rejection
closes eligibility immediately, clears the paused SDK queue and the two owned
cookies, and leaves authentication, language, billing and acquisition storage
untouched. Already received Azure events are not retroactively removed.

## Actual Azure configuration

- Resource: `flare-dev-insights`, centralus, workspace-based web component.
- Existing workspace: `flare-dev-logs` in `flare-dev`; no extra server/workspace.
- IP masking enabled. Azure still processes connection IP before masking; this
  is not a claim of zero IP processing or zero HTTP Referer. The event's referrer
  is empty; the existing HTTP referrer policy remains unchanged.
- Component cap reduced from default 100 GB to **0.1 GB/day**. Other services and
  the shared workspace cap are unchanged. This is an ingestion safeguard, not a
  strict monetary cap: Azure can overshoot and shared free allowances may be used
  by other resources. See [Azure daily caps](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/daily-cap)
  and [monitoring pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/).
- `AppPageViews` analytics and total retention set to **30 days**, independently
  verified after update. Before changing this table, a restricted aggregate query
  found zero page views over 90 days. Other tables' retention is unchanged.
- No Azure API key, query key, backend SDK, managed-identity grant or billing Live
  configuration is created by this integration.

Public build variables (GitHub Actions repository variables, not server secrets):

```
NEXT_PUBLIC_APPLICATION_INSIGHTS_ENABLED=true
NEXT_PUBLIC_APPLICATION_INSIGHTS_CONNECTION_STRING=<public Azure browser ingestion connection string>
```

Both web build workflows include these variables. Disabled is the default for
local/unconfigured builds. Invalid enabled connection strings fail the build;
the browser fails closed. The actual configuration and existing Paddle public
Sandbox inputs are verified without recording their values in source/evidence.

## Viewing visits

Azure Portal → `flare-dev-insights` → Usage → Users / Sessions / Events.
Use Logs for aggregate counts and page popularity; select the time range.
Visitors are browser IDs, not verified people. Cookie deletion, multiple devices,
privacy signals, consent rejection, blockers and cap pauses affect coverage.
No historical browser traffic is reconstructed before deployment.

In the linked workspace's Logs:

```kusto
AppPageViews
| where TimeGenerated > ago(7d)
| where _ResourceId endswith "/components/flare-dev-insights"
| summarize Views=sum(ItemCount),
    Browsers=dcountif(UserId, isnotempty(UserId)),
    Visits=dcountif(SessionId, isnotempty(SessionId))
    by bin(TimeGenerated, 1d)
| order by TimeGenerated asc
```

```kusto
AppPageViews
| where TimeGenerated > ago(7d)
| where _ResourceId endswith "/components/flare-dev-insights"
| summarize Views=sum(ItemCount) by Name
| order by Views desc
```

App-level Logs expose the equivalent `pageViews` table (`timestamp`, `name`,
`user_Id`, `session_Id`, `itemCount`). These events do not establish account
creation, completed import or successful Analyze; the first-party database
remains authoritative for such facts.

## Release and rollback

Deploy only the Linux standalone **web** package from the reviewed integration
SHA. API/worker/database remain on the accepted compatible schema0021 release.
Keep the prior web ZIP and checksum before replacement. To turn off collection,
set the public enabled build variable to `false`, build and deploy web again;
changing only an App Service runtime variable cannot rewrite an existing browser
bundle. Users can reject immediately without waiting for another deployment.

## Validation

Focused privacy/lifecycle tests: 30/30. Full frontend suite: 212/212, including the separate notice and legacy UI
regression coverage. ESLint, TypeScript and a production build passed. Actual pinned
SDK fake-transport serialization and isolated Chromium wire QA both passed; the
latter verified 19 checks, six sanitized page views, no pre-consent/withdrawn
sends, reload identity, owned-cookie bounds, SPA counts and DNT/GPC. All synthetic
ingestion was intercepted; it is not proof of live Azure receipt.

CI detected that editing the existing Privacy document would break its exact
backend legal-acceptance identity. The reviewed document is restored unchanged;
optional analytics uses a separate `/analytics` notice and explicit browser
choice. Existing legal acceptance and backend remain compatible. Immutable Linux
artifact and live Azure receipt are recorded after release. No checkout or
current test Pro cancellation is part of this task.
