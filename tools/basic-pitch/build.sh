#!/usr/bin/env bash
# Rebuild the self-hosted Basic Pitch bundle and model from the npm registry.
#
#   bash tools/basic-pitch/build.sh          # rebuild vendor/basic-pitch-1.0.1
#   bash tools/basic-pitch/build.sh --check  # rebuild in a temp dir and fail if
#                                            # the committed files differ
#
# npm ci installs exactly the versions in package-lock.json and checks every
# tarball against its recorded sha512 integrity, so the inputs are verified
# before esbuild bundles them. The output files and their SHA-256 hashes are
# committed; tests/test_api.py checks the served bytes against SHA256SUMS.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
dest="$repo/vendor/basic-pitch-1.0.1"
check=0
[ "${1:-}" = "--check" ] && check=1

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp "$here/package.json" "$here/package-lock.json" "$here/entry.mjs" "$work/"
(cd "$work" && npm ci --no-audit --no-fund --ignore-scripts >/dev/null)
# esbuild ships its binary through a postinstall script; run only its own.
(cd "$work" && node node_modules/esbuild/install.js)

out="$work/out"
mkdir -p "$out/model"
(cd "$work" && npx --no-install esbuild entry.mjs --bundle --format=esm --minify \
  --platform=browser --target=es2020 --legal-comments=eof --log-level=error \
  --metafile="$work/meta.json" --outfile="$out/basic-pitch.mjs")
cp "$work/node_modules/@spotify/basic-pitch/model/model.json" \
   "$work/node_modules/@spotify/basic-pitch/model/group1-shard1of1.bin" "$out/model/"
# Every bundled package with its version and license, then the full license
# texts (Apache-2.0 from Basic Pitch also covers TensorFlow.js, which ships no
# LICENSE file in its npm package; its source headers stay in the bundle).
(cd "$work" && node -e '
  // Only packages esbuild actually put into the bundle (from its metafile).
  const fs = require("fs"), path = require("path");
  const meta = JSON.parse(fs.readFileSync("meta.json", "utf8"));
  const dirs = new Set();
  for (const input of Object.keys(meta.inputs)) {
    if (input.startsWith("(disabled):")) continue;  // browser-field stubs, not bundled
    const m = input.match(/^(.*node_modules\/(?:@[^/]+\/)?[^/]+)\//);
    if (m) dirs.add(m[1]);
  }
  const rows = [...dirs].map(d => {
    const pj = JSON.parse(fs.readFileSync(path.join(d, "package.json"), "utf8"));
    return `${pj.name} ${pj.version} ${pj.license || "UNKNOWN"}`;
  });
  console.log("Packages bundled into basic-pitch.mjs (name version license):\n");
  console.log([...new Set(rows)].sort().join("\n"));
' > "$out/LICENSES.txt")
{
  printf '\n\n==== @spotify/basic-pitch LICENSE ====\n\n'; cat "$work/node_modules/@spotify/basic-pitch/LICENSE"
  printf '\n\n==== @tonejs/midi LICENSE.md ====\n\n'; cat "$work/node_modules/@tonejs/midi/LICENSE.md"
} >> "$out/LICENSES.txt"
(cd "$out" && shasum -a 256 basic-pitch.mjs model/model.json model/group1-shard1of1.bin > SHA256SUMS)

if [ "$check" = 1 ]; then
  diff -r "$out" "$dest" && echo "vendor/basic-pitch-1.0.1 matches a fresh build"
else
  rm -rf "$dest"
  mkdir -p "$(dirname "$dest")"
  cp -R "$out" "$dest"
  cat "$dest/SHA256SUMS"
fi
