# WEB-002 — Settings subscription and Paddle Sandbox Checkout

This change adds a Subscription section to authenticated Settings with Free,
Pro, and Team cards. Free is always marked **Current**. Pro opens Paddle Billing
Sandbox Checkout for one unit of `pri_01m3y1nvmgw2avt60bz87161c2`, prefills the
signed-in user's email, and sends their Flare user ID as `customData.userId`.
Team has no price or checkout; its button explains that a separate Team price
is required.

This is a checkout integration only. A successful test purchase does not change
the current plan, grant entitlements, raise limits, or persist subscription state.
There are no billing API endpoints, migrations, webhooks, cancellation flows,
customer portal links, or live payments in this stage. Pro and Team benefits are
shown as planned benefits. The backend remains the authority for future access.

## Configuration

Only these public frontend values are used:

| Variable | Value |
| --- | --- |
| `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN` | A client-side token from the **Sandbox** account, starting with `test_` |
| `NEXT_PUBLIC_PADDLE_PRO_PRICE_ID` | `pri_01m3y1nvmgw2avt60bz87161c2` |

No token has been supplied or committed. Checkout with the real Sandbox account
has not been verified. A missing token produces a configuration message; a
`live_` token or another unsupported token format is rejected before SDK loading.
Do not place a Paddle server API key or webhook secret in either variable. Paddle
client-side tokens are designed to be public; Sandbox and live credentials and
catalogs are separate. See [client-side tokens][tokens] and [Sandbox][sandbox].

For local Next.js development, create an untracked `frontend/.env.local` with
these entries and replace the token placeholder with a Sandbox client-side token:

```dotenv
NEXT_PUBLIC_PADDLE_CLIENT_TOKEN=<your Sandbox test_ client-side token>
NEXT_PUBLIC_PADDLE_PRO_PRICE_ID=pri_01m3y1nvmgw2avt60bz87161c2
```

Restart the development server after changing these values. For a production
artifact or Docker image, set them **before** `next build` and rebuild after any
change. `NEXT_PUBLIC_*` values are compiled into the browser bundle; changing
App Service or container runtime settings cannot update a previously built
bundle. See [Next.js public environment variables][next-env].

For the GitHub web build workflows, add the same two names under repository
**Settings → Secrets and variables → Actions → Variables**. Both
`azure-web-artifact.yml` and the web job in `azure-appservice-release.yml` read
them through the `vars` context. The price variable falls back to the approved
Pro price; the token has no fallback. These are repository configuration
variables for public browser values, not server API keys. Setting them does not
itself publish or deploy anything. See [GitHub configuration variables][gh-vars].

`frontend/Dockerfile` accepts both names as build arguments. Pass them to the
image build, for example from an environment where the two public values are
already set:

```sh
docker build --build-arg NEXT_PUBLIC_PADDLE_CLIENT_TOKEN \
  --build-arg NEXT_PUBLIC_PADDLE_PRO_PRICE_ID \
  -t flare-frontend-sandbox ./frontend
```

For the existing Compose setup, pass these arguments explicitly to its frontend
build, then recreate the service using the resulting image:

```sh
docker compose build --build-arg NEXT_PUBLIC_PADDLE_CLIENT_TOKEN \
  --build-arg NEXT_PUBLIC_PADDLE_PRO_PRICE_ID frontend
docker compose up -d --no-build frontend
```

The two public variables must be exported in the shell used for the build.
Runtime `frontend.environment` entries alone are insufficient. The root
`.env.example` and `frontend/.env.example` contain blank-token examples.

## Paddle Sandbox dashboard setup

1. Use the separate Sandbox account and create a **client-side token** under
   Developer tools → Authentication. Do not use a live account token.
2. Confirm `pri_01m3y1nvmgw2avt60bz87161c2` belongs to the intended Pro product
   in that same account and is an active recurring price.
3. Configure its free trial to **30 days** in Paddle: the price's `trial_period`
   uses `interval: "day"` and `frequency: 30`, without a paid trial unit price.
   The frontend displays “30-day free trial” but does not create or override the
   trial. The actual offer, renewal price, and billing interval come from Paddle.
   See [create a subscription in trial][trial].
4. Set a default payment link under Checkout → Checkout settings, using the
   intended local or deployed Settings URL, such as
   `http://localhost:3000/settings` for local testing. Sandbox permits an
   unverified domain. The payment-link configuration is still required for
   checkout to work. See [quickstart troubleshooting][quickstart] and
   [Sandbox behavior][sandbox].

No Team price is available in this change. Do not substitute the Pro price for
Team or add a live environment switch.

## Implementation and boundaries

- [Subscription section](../../../frontend/src/features/subscription/subscription-section.tsx)
  reads the existing `useSession().user` and locale. It never reads browser
  profile storage for billing identity and never changes authentication.
- [Localized copy](../../../frontend/src/features/subscription/subscription-copy.ts)
  and [CSS module](../../../frontend/src/features/subscription/subscription-section.module.css)
  keep Subscription changes isolated from shared dictionaries and global styles.
- [Checkout controller](../../../frontend/src/lib/billing/checkout-controller.ts)
  owns the initialization promise, observable state, synchronous click lock,
  load/open timeouts, and checkout event handling. The
  [Sandbox singleton](../../../frontend/src/lib/billing/paddle-sandbox.ts)
  lazily imports `@paddle/paddle-js` 1.6.5 and always initializes with
  `environment: "sandbox"`.
- [Settings route](../../../frontend/src/app/(flare)/settings/page.tsx) injects
  the section through an optional `subscription?: ReactNode` prop in
  [SettingsPage](../../../frontend/src/features/settings/settings-page.tsx).
  Existing callers can omit the prop. This keeps integration edits small for
  independent Settings work, including PR #31; it does not guarantee a
  conflict-free merge against a moving branch.
- [Next configuration](../../../frontend/next.config.ts) adds exact Paddle
  Sandbox CSP sources to every document response: the public SDK on `cdn.paddle.com`, Sandbox
  styles/images/error frame on `sandbox-cdn.paddle.com`, checkout frame on
  `sandbox-buy.paddle.com`, and Sandbox API on `sandbox-api.paddle.com`. This
  preserves checkout when Next.js client navigation reaches Settings from
  another route while keeping the initial document's CSP. Existing directives
  and other security headers remain. No live checkout/API origins or wildcards
  are added, and the SDK still loads only after a Pro purchase click.
- [Frontend package](../../../frontend/package.json),
  [Dockerfile](../../../frontend/Dockerfile),
  [web artifact workflow](../../../.github/workflows/azure-web-artifact.yml), and
  [release-package workflow](../../../.github/workflows/azure-appservice-release.yml)
  supply the SDK dependency and public build configuration.

The lock lasts while loading, while the overlay is open, and while its success
screen is visible. `checkout.closed` releases it. `checkout.completed` displays
a test-completion message and leaves Free current. Payment failures leave the
overlay available for retry; checkout-open failures close it and show an error.
Checkout event payloads are not logged or persisted.

Leaving Settings while the SDK or checkout frame is still loading cancels the
pending attempt. Late SDK resolution cannot open checkout on the destination
route, and a new attempt reuses the same initialization promise. An already
loaded overlay keeps its lock until it closes.

The payload is:

```ts
{
  items: [{ priceId: "pri_01m3y1nvmgw2avt60bz87161c2", quantity: 1 }],
  customer: { email: currentUser.email },
  customData: { userId: currentUser.id },
  settings: { displayMode: "overlay", allowLogout: false, locale, theme }
}
```

Paddle's wrapper caches its script-loading promise. If loading rejects, restoring
the connection and clicking again may keep returning that rejection; reload the
page before retrying. The controller's initialization check and timeouts handle
unavailable SDK results, but they do not verify the dashboard catalog, trial,
token validity, or actual payment success. See the [official wrapper][wrapper],
[loader implementation][loader], and [checkout events][events].

## Manual Sandbox verification

Run these checks only after adding the public Sandbox token and rebuilding or
restarting as appropriate. Record actual outcomes without copying credentials
or full customer/payment payloads into logs or this document.

1. Sign in with a real Flare account and open Settings. Confirm Free is Current,
   all three cards are present, and Pro/Team benefits are labeled as planned.
   Check English and Spanish, light/dark themes, and a narrow viewport.
2. Click Team. Confirm it explains the missing Team price and opens no Paddle
   checkout. Free remains Current.
3. Click Pro. Confirm a Paddle **Test Mode** overlay appears, the intended Pro
   product and quantity 1 are shown, the signed-in email is prefilled, and the
   offer explicitly includes the configured 30-day free trial and expected
   renewal terms. Stop the trial test if the offer differs; correct the Sandbox
   price configuration before continuing.
4. Close checkout. Confirm Pro can reopen it and Free stays Current. Rapidly
   click Pro twice and confirm only one overlay and one checkout request are
   created. The purchase buttons remain disabled until the overlay closes.
5. Complete a Sandbox checkout with an official test card, for example
   `4242 4242 4242 4242`, any cardholder name, a valid future expiry, and security
   code `100`. Confirm the test-completion message and no Free/entitlement
   change. Close the success overlay and confirm the buttons recover.
6. In the Sandbox dashboard, inspect the resulting transaction/subscription.
   Confirm the Pro price, quantity 1, trial dates/status, customer email, and
   `custom_data.userId` matching the signed-in Flare user. Paddle copies checkout
   custom data to the subscription for recurring items. See [Checkout.open][open].
7. Test a declined Sandbox card (`4000 0000 0000 0002`), then retry or close.
   Confirm a clear failure message, no entitlement change, and no second overlay
   replacing the first. Use [official Sandbox test cards][sandbox].
8. Block the SDK request or take the browser offline before opening Pro. Confirm
   loading ends with an error rather than an endless spinner. Reload after
   restoring the connection. Also test a checkout-frame load failure and verify
   timeout cleanup permits a fresh attempt.
9. In separate local configurations, test a missing token, a non-Sandbox token,
   and an invalid price. Confirm an error appears before checkout and no live
   purchase can start. Restore the intended Sandbox build values afterward.
10. Verify the HTTP CSP permits the listed Sandbox resources on Settings and
    other document entry routes. Check the browser console
    for blocked Paddle stylesheet/frame requests. SDK mocks cannot establish
    this network behavior. Test both a direct Settings load and navigation from
    Vault to Settings through the app's profile link: Next.js client navigation
    keeps the original document and its CSP. The shared policy covers both paths;
    the SDK must still load only on Buy. See [Next.js Link navigation][next-link].

## Validation evidence

Verified on 2026-10-02 in an isolated WEB-002 worktree, after a fresh `npm ci`:

| Check | Result |
| --- | --- |
| `npm ci` | Passed using the existing lockfile plus the one Paddle package |
| `npm test` | 107 passed, including 23 new checkout/Subscription tests |
| `npm run lint` | Passed |
| `npx tsc --noEmit` | Passed |
| `npm run build` | Passed; all existing routes retained |
| `git diff --check` | Passed |

Tests cover Sandbox-only admission, minimal identity payload, initialization and
double-click races, opening/payment errors, deadlines and late SDK results,
unmount cancellation, success without entitlements, Team behavior, English and
Spanish, lazy SDK loading, exact CSP origins, and public build configuration.
Existing auth, voice, Sources, Vault, Analyze and landing regression tests pass.
SDK mocks are used for payment flow tests; they do not prove account-level
catalog, token, trial or payment behavior.

Browser UI verification used the standalone local demo at port 3112 with no
Paddle token and synthetic seeded workspace data. Navigation from Flares to
Settings rendered all three cards. Missing-config Pro and unconfigured Team
messages were verified. At 390×844, cards stack without horizontal overflow;
Buy uses `rgb(0, 113, 227)` in light mode and Current is disabled and grey.
Light/dark themes and Spanish labels/Team feedback were checked, then locale,
theme and viewport were restored. Screenshots:
[desktop](screenshots/subscription-desktop.jpg),
[mobile](screenshots/subscription-mobile.jpg),
[dark](screenshots/subscription-dark.jpg).

**Not verified:** real Paddle overlay/product/trial/customer/custom-data and test
payment against the user's Sandbox account, because no client-side token was
provided. No Live environment, real card, backend/DB change, cloud mutation,
deployment or paid-access grant was performed. Complete the manual Sandbox
verification above after supplying the public token.

Changed files are the two Settings files, three new Subscription files, two new
billing files, `frontend/tests/paddle-sandbox.test.cjs`, `frontend/next.config.ts`,
`frontend/package.json`, `frontend/package-lock.json`, `frontend/Dockerfile`, both
`.env.example` files, the two web build workflows, and this README/screenshots.

## Primary references

- [Include and initialize Paddle.js][include]
- [Paddle.Initialize][initialize] and [Checkout.open][open]
- [Checkout events][events] and [handle checkout success][success]
- [Client-side tokens][tokens], [Sandbox][sandbox], and [trial configuration][trial]
- [Official Paddle.js wrapper][wrapper] and [current public SDK source][cdn]
- [Next.js public environment variables][next-env]
- [GitHub Actions configuration variables][gh-vars]

[tokens]: https://developer.paddle.com/paddle-js/about/client-side-tokens/
[sandbox]: https://developer.paddle.com/sdks/sandbox/
[trial]: https://developer.paddle.com/build/trials/create-trial/
[quickstart]: https://developer.paddle.com/get-started/quickstart/
[include]: https://developer.paddle.com/paddle-js/about/include-paddlejs/
[initialize]: https://developer.paddle.com/paddle-js/methods/paddle-initialize/
[open]: https://developer.paddle.com/paddle-js/methods/paddle-checkout-open/
[events]: https://developer.paddle.com/paddle-js/events/
[success]: https://developer.paddle.com/build/checkout/handle-success-post-checkout/
[wrapper]: https://github.com/PaddleHQ/paddle-js-wrapper
[loader]: https://github.com/PaddleHQ/paddle-js-wrapper/blob/main/src/utils/shared.ts
[cdn]: https://cdn.paddle.com/paddle/v2/paddle.js
[next-env]: https://nextjs.org/docs/pages/guides/environment-variables#bundling-environment-variables-for-the-browser
[gh-vars]: https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables
[next-link]: https://nextjs.org/docs/app/api-reference/components/link
