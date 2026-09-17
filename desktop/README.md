# Flare for macOS

This directory contains a small Electron shell for the production Flare web app.
It loads `https://flare4u.tech` as a top-level page, so authentication cookies,
the `/api` proxy, GitHub App redirects, and the browser voice recorder keep the
same origin as the public product.

The shell does not expose Node.js to remote content. Navigation is limited to
Flare and the GitHub authorization flow; unrelated HTTPS and `mailto:` links are
opened by macOS. Microphone access is permitted only for a Flare origin and only
for audio capture.

## Local development

Node.js 22.12 or newer and pnpm 11.19.0 are required.

```sh
pnpm install --frozen-lockfile
pnpm test
pnpm start
```

To point an unpackaged development build at a local frontend:

```sh
FLARE_APP_URL=http://localhost:3000 pnpm start
```

An insecure URL is accepted only for a loopback host and only while Electron is
unpackaged. Packaged applications require HTTPS.

## Build

```sh
pnpm dist:mac:arm64
pnpm dist:mac:x64
```

Outputs are written to `desktop/dist/`. The GitHub Actions workflow builds both
architectures. Tags matching `desktop-v*` also publish the stable filenames
`Flare-macOS-arm64.dmg` and `Flare-macOS-x64.dmg` to a GitHub Release.

The current release uses only an ad-hoc local signature; it has no Apple
Developer ID signature and is not notarized. macOS may ask the user to open
System Settings → Privacy & Security and choose **Open Anyway** after the first
launch. Developer ID signing and notarization should be enabled before broad
public distribution.
