# Paddle Sandbox workspace subscriptions

API-001 adds signed webhooks, durable subscription state and server-side Pro
entitlement for the **entire workspace**. Only the workspace owner starts checkout;
all current members can read the workspace's subscription status. No Live Paddle
endpoint, API key, billing portal or cancellation action is implemented.

## Implemented contract

- `GET /billing/status` uses the existing verified cookie session and returns the
  authoritative workspace plan. Missing setup disables checkout; an unavailable
  database returns an error rather than inventing a plan.
- `POST /billing/checkout-intents` issues a random, expiring, single-use intent
  bound to the authenticated owner, workspace and server-configured Pro price.
  Only its hash is stored. It accepts no browser-provided identity or price.
- Paddle.js remains Sandbox-only. The existing official overlay uses the server
  response's email, price, quantity and opaque intent. Browser `checkout.completed`
  triggers bounded status refresh; it never grants access itself.
- `POST /billing/paddle/webhook` verifies HMAC-SHA256 over the **unchanged body**
  before parsing JSON. Signature timestamps must be within five seconds in either
  direction. Size/time limits, duplicate-key rejection and generic errors apply.
  Only this exact POST route bypasses browser Origin validation.
- A PostgreSQL transaction records the event and updates the subscription together.
  `event_id` deduplication, subscription-specific time ordering and immutable
  customer/workspace binding prevent duplicate or stale updates. Previously
  received unlinked snapshots are considered when `subscription.created` binds
  the intent, so a delayed creation event cannot resurrect canceled access.
- `trialing` and `active`, the configured Pro price, quantity one and a valid
  current trial/billing period grant Pro. Access ends at the period/trial deadline
  or an earlier scheduled pause/cancellation, even if a webhook is delayed.
  `past_due`, `paused`, `canceled`, unsupported and ambiguous states fall back to
  Free. A newer valid subscription can still grant Pro independently of an older
  canceled one. No additional paid capacity or AI budget is invented.
- `require_pro` is the backend dependency for future Pro-only features. Existing
  Free features and the one manual **or** scheduled Analyze per workspace local
  day remain unchanged. Planned extra limits on the cards remain labelled planned.
- Billing logs contain only a fixed outcome enum. No signature, secret, raw body,
  email, card details or checkout token is logged. The private ledger retains
  minimal normalized snapshots and hashes, not full Paddle payloads.

## Backend environment

```dotenv
PADDLE_ENVIRONMENT=sandbox
PADDLE_PRO_PRICE_ID=pri_01m3y1nvmgw2avt60bz87161c2
PADDLE_WEBHOOK_SECRET=
```

`PADDLE_WEBHOOK_SECRET` is the **Sandbox notification destination endpoint secret**,
not the existing public `test_` client token and not an API key. Store it through
the approved API secret mechanism; never put it in a `NEXT_PUBLIC_*` variable,
GitHub source, committed `.env`, frontend bundle, issue or log. An empty secret
leaves checkout and webhook processing disabled without changing authorization.

The frontend keeps its already configured public variables:

```dotenv
NEXT_PUBLIC_PADDLE_CLIENT_TOKEN=
NEXT_PUBLIC_PADDLE_PRO_PRICE_ID=pri_01m3y1nvmgw2avt60bz87161c2
```

The existing price defines Flare Pro's 30-day trial in Paddle. Flare neither sets
another trial length in the browser nor adds 30 days on each event.

## Sandbox activation after review

1. Review and integrate this branch with the accepted `0020` schema. Migration
   `0021` is forward-only; back up first. Use the existing administrator migration
   job to run `alembic -c backend/alembic.ini upgrade head`. The API continues to
   use the restricted `flare_app` credential, never the migration credential.
2. Deploy matching API and web releases. Schema readiness expects `0021`; do not
   send the new frontend to an API that lacks the billing routes.
3. In **Paddle Sandbox**, create one notification destination for:
   `https://flare-api-vm-260914.azurewebsites.net/billing/paddle/webhook`.
   Use **platform events only**, not simulator/all traffic. Subscribe to:
   `subscription.created`, `subscription.updated`, `subscription.trialing`,
   `subscription.activated`, `subscription.past_due`, `subscription.paused`,
   `subscription.resumed`, `subscription.canceled`.
4. Save that destination's endpoint secret in the approved backend secret store,
   set the three backend variables above and restart the API. Confirm all
   billing environments and the frontend client token are Sandbox.
5. As a verified workspace owner, open Settings → Subscription → Pro Buy. Use
   Paddle's documented Sandbox test payment details. Verify a successful
   `subscription.created` delivery and Pro Current in Settings, then reload.
   Sign in as another member of the same workspace and verify the same Pro plan.
6. Retry the same notification: state must not duplicate. Change/cancel the
   subscription in the **Sandbox dashboard** and verify status/period behavior.
   A new signed-in HTTP request must derive access from persisted subscriptions.
   An unrelated workspace must remain Free.

Legacy checkouts created before server-issued intents are deliberately unlinked.
Reconciliation of those historical subscriptions is separate reviewed work;
email or client `userId` alone is insufficient ownership proof. The bounded intent
window also means exceptionally delayed first-created delivery may require
operator reconciliation. Review `unlinked`/`conflict` outcomes and Paddle delivery
history rather than replaying a purchase or editing a plan by hand.

The ledger's retention/reconciliation policy should be reviewed before Live or
large-scale billing. No Live rollout is authorized by this implementation.

## Verification and release boundaries

Detailed measured checks are recorded in `validation.json`. This delivery is
application code and a migration, not a claim that Azure or the Paddle dashboard
has already been configured. A real Sandbox lifecycle smoke test requires the
destination secret and coordinated deployment above.

Primary references:

- [Signature verification](https://developer.paddle.com/webhooks/about/signature-verification/)
- [Provision access from subscription webhooks](https://developer.paddle.com/build/subscriptions/provision-access-webhooks/)
- [Webhook ordering and delivery](https://developer.paddle.com/webhooks/about/how-webhooks-work/)
- [Acknowledgment and retry behavior](https://developer.paddle.com/webhooks/about/respond-to-webhooks/)
- [Notification destination traffic source](https://developer.paddle.com/api-reference/notification-settings/create-notification-setting/)
- [Subscription creation and binding](https://developer.paddle.com/webhooks/subscriptions/subscription-created/)
