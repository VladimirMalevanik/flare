# Source provenance

## Frontend

`frontend/` was imported from
[`fedocc/flare-frontend`](https://github.com/fedocc/flare-frontend) at commit
`dd2e65b75ac8ab916db03e8986ce490b0a4d3384`. The import is represented by a
squashed subtree commit so the source revision remains traceable.

The frontend repository did not contain a project-level license at the imported
revision. The bundled Inter font is separately covered by the SIL Open Font
License in `frontend/public/fonts/OFL.txt`. Project owners should agree on and
add a repository license before inviting outside reuse.

## Backend architecture

The backend module layout was adapted from
[`nikepf/startup_insight`](https://github.com/nikepf/startup_insight) at commit
`45057fbd9b5ef427a79659c63a0b06aa57a5c41a`. At that revision the source was an
empty scaffold: all files in `startup_insight/` were zero bytes. No source code,
configuration or secrets were copied from it.

## macOS desktop runtime

The `desktop/` shell is original project code and uses
[`Electron`](https://github.com/electron/electron) under the MIT License for the
packaged runtime. Release artifacts retain Electron's bundled license notices.
[`electron-builder`](https://github.com/electron-userland/electron-builder),
also MIT-licensed, is pinned as a build-time dependency and is not shipped as
application code.

## Voice media inspection

Azure App Service downloads the pinned FFmpeg 7.0.2 `ffprobe` static binary
from [John Van Sickle's build archive](https://johnvansickle.com/ffmpeg/) and
verifies both the archive and executable with cryptographic checksums before
use. The build is licensed under the GNU General Public License version 3;
corresponding build information and source are linked from the archive page.
