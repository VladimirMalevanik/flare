# Release-owner handoff — Vova

Use the accepted integrated main source, not the old individual PR archives.
No credentials, recipient lists, provider settings or live data were accessed
by API-007. Required configuration names and scripts already exist in the repo.

1. Confirm current running source and backup/restore boundary. Pause old workers,
   apply the single 0023→0024 migration line with migration-owner privileges, deploy
   matching API/web/worker packages on existing resources and verify readiness.
2. Sources: configure provider apps/callbacks, server SOURCE_* variables and
   encrypted token keys, corresponding API/worker configuration, restricted
   worker and heartbeat. Follow DATA-003/README.md. Test one consenting account
   per provider, explicit selection/sharing, Vault content/provenance, dedupe,
   cancellation and disconnect before enabling SOURCES_ENABLED.
3. Team: select a distinct Paddle Sandbox Team price, configure server and matching
   administrator team_policy, genuine SMTP/HTTPS origin and verification. Follow
   API-006/README.md for configuration and API-008/README.md for the corrected
   shared-notes product flow. Test checkout/webhook→empty shared project→verified
   invite→notes from two members→one shared scheduled Flare with both sources,
   private-Vault isolation, removal and expiry/read/export. Enable TEAM_ENABLED and policy only after these
   checks. Pro-to-Team provider upgrade/proration remains a separate approved flow.
4. UTM: approve the existing proposed policy/retention/disclosure values, configure
   function-only reporting access and bounded cleanup in the existing scheduler,
   then use backend scripts.growth_ops to activate/report. Follow GROWTH-003/README.md;
   never claim all clicks or all-visitor conversion from registered-account data.
   Test fedor/ilyas/flare link opt-in, registration and scheduled product outcomes;
   rejection/withdrawal must preserve product use. Keep real daily quotas intact.
5. Developer mail: configure API-only DEVELOPER_MAIL_ACCOUNTS using verified
   existing account IDs, SMTP_URL and EMAIL_FROM. Follow WEB-007/README.md. Verify
   allowed/ordinary users, one owner-approved recipient, delivered From/authentication
   and reply handling; do not expose the private six-account map in a public file.
6. Remaining human acceptance: restart the owner's browser and verify persistent
   session; confirm existing ZIP import remains functional; finish Sandbox lifecycle
   cancellation acceptance. These board reviews do not imply a new code defect.
7. API-005 empty-analysis investigation remains owned by Vova. Keep generation,
   provider budget and rollout decisions in that task. ARCH-002 automatic memory
   enrichment remains waiting for its approved budget owner/limits.

Record source, provider approvals, readiness, evidence and rollback boundaries.
An enabled flag is not proof of actual provider access, mail delivery or billing.
No new paid resource, Live payment or personal-account permission is implied.
