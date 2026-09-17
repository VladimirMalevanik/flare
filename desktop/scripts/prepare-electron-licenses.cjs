"use strict";

const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { downloadArtifact } = require("@electron/get");
const packageJson = require("../package.json");

const SUPPORTED_ARCHITECTURES = new Set(["arm64", "x64"]);
const MAX_LICENSE_BYTES = 32 * 1024 * 1024;

async function main() {
  const architecture = process.argv[2] || process.arch;
  if (!SUPPORTED_ARCHITECTURES.has(architecture)) {
    throw new Error(`Unsupported Electron license architecture: ${architecture}`);
  }

  const archive = await downloadArtifact({
    version: packageJson.devDependencies.electron,
    artifactName: "electron",
    platform: "darwin",
    arch: architecture,
  });
  const destination = path.join(__dirname, "..", "generated-licenses");
  fs.mkdirSync(destination, { recursive: true });

  extract(archive, "LICENSE", path.join(destination, "LICENSE.electron.txt"));
  extract(
    archive,
    "LICENSES.chromium.html",
    path.join(destination, "LICENSES.chromium.html"),
  );
}

function extract(archive, member, destination) {
  const contents = execFileSync("unzip", ["-p", archive, member], {
    encoding: "buffer",
    maxBuffer: MAX_LICENSE_BYTES,
  });
  if (contents.length === 0 || contents.length > MAX_LICENSE_BYTES) {
    throw new Error(`Electron license ${member} is missing or too large`);
  }
  fs.writeFileSync(destination, contents, { mode: 0o644 });
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
