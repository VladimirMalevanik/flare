# WEB-004 — Approved link cover and service registry

Assigned by Fedor on 2026-10-04. YouGile `MAR-64`: the prepared 1200 × 630 JPEG
was explicitly approved and requested as the link cover. Fedor also selected
free personal Gmail and requested a service registry.

## Change

- Install the approved JPEG unchanged at `frontend/public/brand/flare-link-cover.jpg`.
- Provide server-rendered Open Graph and Twitter large-image metadata in the root
  layout. Resolve the image against the public HTTPS origin, so crawler metadata
  never points at localhost. Preserve document title/description, landing copy,
  authentication and acquisition behavior.
- Add [the service registry](../../SERVICE_REGISTRY.md): repository evidence,
  unverified registration emails/owners, planned services, the free Gmail decision,
  next steps and the remaining Fedor tasks.

The root metadata is a brand fallback pointing to the public homepage. No HTML
canonical URL is forced onto private or legal routes. No workspace content is
used as a social preview. The image is a public static brand asset.

## Evidence and validation

Product baseline: `1fd54917252539bb8651041d3185ddae97d995e2` (main at the claim).
Declared product paths are the root layout and cover JPEG; other paths are this
report and the service registry. Task state is published separately through
task-sync. No active tasks overlapped at scope declaration.

The design uses the existing Flare mark, palette, original headline and product
description. The human reviewed it before implementation. Authoring evidence is
retained outside the repository in the dated YouGile research artifacts. The
installed checksum and production-build checks are recorded in `validation.json`.

Current Next.js metadata documentation was resolved and fetched through Context7
before implementation: `/vercel/next.js/v16.1.6`.

- [Next.js metadata fields](https://github.com/vercel/next.js/blob/v16.1.6/docs/01-app/03-api-reference/04-functions/generate-metadata.mdx)
- [Next.js metadata and OG images](https://github.com/vercel/next.js/blob/v16.1.6/docs/01-app/01-getting-started/14-metadata-and-og-images.mdx)
- [Open Graph protocol](https://ogp.me/)
- [Google Gmail delegation](https://support.google.com/mail/answer/138350?hl=en)

## Delivery boundary

Source and the isolated local preview can be verified without production
credentials. The public `https://flare4u.tech` preview changes only after the
release owner deploys this version; messenger caches may need a fresh crawl.
No deployment, account creation, credential-store access, access grants, mail
provider change, analytics enablement, paid action or foreign task modification
is part of this delivery. The mail task remains unfinished until the mailbox and
required service access are configured and checked.
