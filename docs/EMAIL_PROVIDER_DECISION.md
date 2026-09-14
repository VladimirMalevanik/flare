# Flare Transactional Email Provider Decision

**Status:** recommendation only; Vova/infrastructure must make and implement the provider decision.
**Reviewed:** 2026-09-14 against current official provider documentation.

Flare already uses a provider-neutral SMTP boundary. Both email verification and
scheduled Flare notifications use `SmtpEmailSender`; switching providers changes
`SMTP_URL` and `EMAIL_FROM`, with no provider SDK or application rewrite.

## Free-tier comparison

| | Resend | Brevo |
| --- | --- | --- |
| Current free allowance | 3,000 transactional emails/month, capped at 100/day | 300 email sends/day; unused sends do not roll over |
| SMTP | Included; standard SMTP/SMTPS relay | Included; standard SMTP relay |
| Custom domain | Free plan supports up to 3 domains | Owned domains can be authenticated; transactional email is included on Free |
| Domain authentication | Domain verification requires provider-supplied SPF and DKIM records; DMARC is optional but recommended | Manual authentication uses provider-supplied Brevo-code, DKIM, and DMARC records. Shared-IP SPF uses Brevo infrastructure; a branded subdomain adds SPF alignment |
| Free-tier caveat | Hard 100/day limit and no free overage | 300/day limit; excess transactional messages may queue, and free-plan email carries Brevo branding |
| Flare integration impact | Configure an SMTP URL and verified sender only | Configure an SMTP URL and verified sender only |

Sources: [Resend pricing](https://resend.com/docs/knowledge-base/what-is-resend-pricing),
[Resend SMTP](https://resend.com/docs/send-with-smtp),
[Resend domain verification](https://resend.com/docs/dashboard/domains/introduction),
[Resend production access](https://resend.com/docs/knowledge-base/does-resend-require-production-approval),
[Brevo free-plan limits](https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan),
[Brevo transactional SMTP](https://www.brevo.com/products/transactional-email/), and
[Brevo domain authentication](https://help.brevo.com/hc/en-us/articles/12163873383186-Authenticate-your-domain-with-Brevo-Brevo-code-DKIM-DMARC), plus its
[deliverability setup](https://help.brevo.com/hc/en-us/articles/35852083084178-Domain-setup-for-better-email-deliverability).

## Recommendation for the 10–20 user MVP

**Recommendation only: start with Resend Free**, provided the release owner confirms
that 100 messages/day covers verification spikes plus at most one scheduled-result
email per enabled user/workspace day. Its SMTP path fits the current code directly,
its custom-domain setup is compact, and free accounts have immediate production
access according to Resend's current documentation.

Brevo is the stronger fallback when 100/day is too tight: its free daily allowance
is 300, and it also supports the existing SMTP implementation. Before choosing it,
the release owner should accept its free-tier branding and complete any account
sending review. Neither provider has been selected or configured in this repository.

Recheck pricing, quotas, branding, data-processing terms, and account eligibility on
the decision date; free plans can change.
