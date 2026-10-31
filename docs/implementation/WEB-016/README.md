# WEB-016 — Team invitation admission and remaining CJM gates

A stalled invitation account lookup could leave the joining screen loading indefinitely. A separate catch treated every HTTP403 as an email-verification problem, including an expired Team license or a missing role.

The account lookup now bounds transport and JSON parsing at12seconds using the existing request helper. Cleanup fences account, capability and preview responses, including transports that ignore abort. A subscription/role rejection retains its public server error. Only `email_verification_required` opens re-verification, using auth resend; renewed legal consent opens the existing terms flow. Invitations still require an explicit sharing acknowledgement. Primary and alternate actions use the existing spaced `team-actions` row.

No backend, generation, role/entitlement rules, schema, dependencies or activation flags change. API-005 remains Vova's task. No real SMTP, provider, AI or payment calls were made.

## Validation

- Twelve new behavioral cases: explicit acceptance, bounded transport/JSON, late results at all three load stages, effect replay, signed-out accounts, distinct subscription/role/verification/legal failures. Seven original failure cases were reproduced before the fix.
- Full frontend run:444cases,443pass; one public example-file test cannot run in the local secret-free sparse checkout. The test was retained for the normal CI checkout. ESLint passed.
- Existing restricted PostgreSQL/HTTP Team, shared-note and source-creator suites:42passed, including a shared scheduled result grounded in two members' notes, one workspace quota, role/expiry guards and private-note isolation. Generated results in these tests use explicit synthetic analyzers; they do not establish production analysis quality.
- Browser acceptance and final CI evidence are recorded with the task/PR; external delivery and deployment remain separate.

## Public production observation ·31October2026

Bounded unauthenticated GETs returned200 for public API health/readiness and worker readiness. `/login` and `/register` returned200 without the newly implemented password-eye control. `/forgot-password` returned404. This establishes that the new recovery UI is not served; it does not identify the private deployed API/worker commit or prove schema0028.

Public DNS contains Cloudflare Email Routing MX records and routing SPF; DMARC is present in monitoring mode. This does not prove that `support@flare4u.tech` forwards to an owned, verified destination or that replies reach users.

See [handoff.md](handoff.md) for the remaining work, required access and acceptance evidence. Passing readiness is distinct from accepting a complete user journey.
