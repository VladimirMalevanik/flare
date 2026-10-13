# Flare service register and common mailbox

Prepared 13 October 2026 (Moscow). This is a verified-code inventory plus explicit
unknown account fields. It is not an audit of private service registrations.
No private login email, password, token or recovery setting was read.

| Service | Confirmed use | Operator / actual registration email | Next action |
| --- | --- | --- | --- |
| GitHub |VladimirMalevanik/flare repository, PRs and existing CI |Repo access exists; registration email unverified |Keep individual team permissions; confirm owner/contact |
| Azure / database / storage |Existing Flare hosting and runtime; Vova release role |Vova; registration email unverified |Record exact resource owners and integrated release |
| Paddle |Sandbox checkout, signed events and server billing |Vova; registration email unverified |Confirm existing account and Team price; no Live change |
| Groq |Existing transcription and scheduled analysis provider |Provider owner/email unverified |Record owner and existing limits; API-005 separate |
| Application Insights |Optional anonymous website analytics code |Azure operator; registration email unverified |Verify existing collection/report access |
| SMTP / developer mail |Existing SMTP sender and restricted site composer |Vova; provider/email unverified |Verify delivery, sender and allowed account map privately |
| Slack app |Selected public-channel source implementation |App owner/email unverified |Register/approve read-only scopes and callbacks |
| Google OAuth |Gmail and Drive selected sources |App owner/email unverified |Approve scopes/testing vs public verification and callbacks |
| Notion integration |Selected-page source implementation |Integration owner/email unverified |Approve read-content integration and callbacks |
| GitHub App |Existing selected-repository authorization |App owner/email unverified |Confirm required read permissions with account owners |
| Domain/DNS |Public flare4u.tech origin in code |Registrar/email unverified |Record owner/recovery and sender DNS separately |
| Common Gmail |No created mailbox confirmed |Fedor: owner creation/verification pending |Create free account, then delegate inbox access |

For each existing service the owner fills the actual registration email and
account owner in a private team register. Change its contact/recovery email only
inside the verified existing account, then test recovery and invite individual
teammates through that service's own roles. No account migration is performed here.

## Free common Gmail — owner steps

Candidate name: flare4uteam@gmail.com; fallback flare4uhq@gmail.com. These are
suggestions, not confirmed available or registered addresses. The owner creates
and verifies the Google account, accepts its terms and sets recovery/2-step protection.

On desktop Gmail: Settings → See all settings → Accounts and Import → Grant access
to your account → Add another account. Add each consenting teammate's own address;
each accepts the invitation within seven days. Personal Gmail supports up to ten
delegates. They can manage mail; delegation does not grant other Google/service
account administration. Keep sign-in credentials with the mailbox owner.
[Google's delegation instructions](https://support.google.com/mail/answer/138350).

After acceptance, test receiving and replying through each teammate's delegated
inbox. Actual recipient addresses, account verification and access grants require
the owner; they were not guessed or sent by this implementation task.
