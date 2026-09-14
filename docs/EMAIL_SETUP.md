# Flare Email Setup

This document records the intended external setup. It does not authorize DNS,
nameserver, Cloudflare, provider, Azure, or production changes.

## Intended mail flow

**Inbound support**

```text
support@flare4u.tech
→ Cloudflare Email Routing
→ existing verified destination inbox
```

The frontend receives the public address at runtime through:

```text
SUPPORT_EMAIL=support@flare4u.tech
```

Settings uses this one mailbox for separate **Get help** and **Send feedback**
mailto actions with distinct subjects. If the variable is missing or invalid, no
mailto link is rendered.

**Outbound application email**

```text
no-reply-style sender on flare4u.tech
→ selected transactional SMTP provider
→ verification emails and scheduled Flare notifications
```

The API sends verification mail. The worker sends one titles-and-links-only email
after a successful scheduled run creates at least one Flare. Both use the same
provider-neutral configuration:

| Variable | Purpose | Process |
| --- | --- | --- |
| `APP_PUBLIC_URL` | Exact public HTTPS app origin used in verification and Flare links | API and worker |
| `SMTP_URL` | Secret `smtp://` or `smtps://` connection URL, including percent-encoded credentials when required | API and worker |
| `EMAIL_FROM` | Provider-verified no-reply-style Flare sender | API and worker |
| `SUPPORT_EMAIL` | Public inbound support/feedback address | Frontend runtime |

Do not expose `SMTP_URL` through a `NEXT_PUBLIC_*` variable or commit it. `EMAIL_FROM`
must match the domain/sender verified with the chosen provider.

## Infrastructure-owned setup checklist

- [ ] Vova decides whether and when `flare4u.tech` moves from its current REG.RU
  nameservers to Cloudflare DNS. Cloudflare Email Routing requires Cloudflare DNS.
- [ ] In Cloudflare, add and verify the existing destination inbox.
- [ ] Create the `support@flare4u.tech` inbound route to that verified inbox.
- [ ] Choose Resend or Brevo after reviewing
  [the provider comparison](EMAIL_PROVIDER_DECISION.md).
- [ ] In the selected transactional provider, add and verify the chosen sending
  domain or subdomain and create the no-reply-style sender.
- [ ] Add only the exact MX/TXT/CNAME/DKIM/SPF/DMARC values shown by Cloudflare and
  the selected provider. Do not copy example values from documentation.
- [ ] Resolve any SPF or MX interaction between inbound routing and outbound sending
  using the live provider instructions; keep a single valid SPF policy per hostname.
- [ ] Inject `APP_PUBLIC_URL`, `SMTP_URL`, and `EMAIL_FROM` into both API and worker,
  and `SUPPORT_EMAIL` into the frontend runtime.
- [ ] Send live verification and scheduled-notification smoke emails, then confirm
  SPF, DKIM, and DMARC results from the received headers.
- [ ] Confirm inbound support and feedback messages reach the verified destination.

Cloudflare documents that Email Routing forwards custom addresses to verified
destinations and requires Cloudflare DNS. It also warns that provider-specific DNS
values must come from the active provider. See
[Email Routing addresses](https://developers.cloudflare.com/email-service/configuration/email-routing-addresses/),
[routing setup](https://developers.cloudflare.com/email-service/get-started/route-emails/),
and [email DNS guidance](https://developers.cloudflare.com/dns/manage-dns-records/how-to/email-records/).
