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
# Every bundled package with its version and license, then each package's own
# license and notice files. Packages that ship no license file:
# - Apache-2.0 TensorFlow.js packages: covered by the Apache-2.0 text from
#   Basic Pitch; their @license source headers stay in the bundle
#   (--legal-comments=eof).
# - seedrandom: its MIT text and copyright are in its README; extracted here.
# - @tensorflow/tfjs-layers (Apache-2.0 AND MIT): its MIT @license header
#   points at https://opensource.org/licenses/MIT; the header and that text
#   are reproduced here.
# Any other bundled package without a license file fails the build.
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
  const pkgs = new Map();
  for (const d of dirs) {
    const pj = JSON.parse(fs.readFileSync(path.join(d, "package.json"), "utf8"));
    pkgs.set(`${pj.name} ${pj.version} ${pj.license || "UNKNOWN"}`, { dir: d, pj });
  }
  const rows = [...pkgs.keys()].sort();
  console.log("Packages bundled into basic-pitch.mjs (name version license):\n");
  console.log(rows.join("\n"));
  const mitText = [
    "Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the \"Software\"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:",
    "The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.",
    "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE."
  ].join("\n\n");
  const fromSource = {
    "seedrandom": dir => {
      const readme = fs.readFileSync(path.join(dir, "README.md"), "utf8");
      const at = readme.indexOf("LICENSE (MIT)");
      if (at < 0) throw Error("seedrandom README has no LICENSE (MIT) section");
      return ["README.md LICENSE section", readme.slice(at).trimEnd()];
    },
    "@tensorflow/tfjs-layers": dir => {
      const src = fs.readFileSync(path.join(dir, "dist", "activations.js"), "utf8");
      const header = src.match(/^\/\*\*[\s\S]*?\*\//);
      if (!header || !header[0].includes("opensource.org/licenses/MIT")) throw Error("tfjs-layers MIT header not found");
      return ["MIT @license header (dist/activations.js) and the text it references", header[0] + "\n\nMIT License (https://opensource.org/licenses/MIT)\n\n" + mitText];
    },
  };
  const missing = [];
  for (const row of rows) {
    const { dir, pj } = pkgs.get(row);
    const files = fs.readdirSync(dir).filter(f => /^(licen[cs]e|notice|copying)/i.test(f)).sort();
    if (!files.length) {
      if (fromSource[pj.name]) {
        const [label, text] = fromSource[pj.name](dir);
        console.log(`\n\n==== ${pj.name} ${pj.version} ${label} ====\n`);
        console.log(text);
      } else if (!(pj.name.startsWith("@tensorflow/") && pj.license === "Apache-2.0")) missing.push(row);
      continue;
    }
    for (const f of files) {
      console.log(`\n\n==== ${pj.name} ${pj.version} ${f} ====\n`);
      console.log(fs.readFileSync(path.join(dir, f), "utf8").trimEnd());
    }
  }
  if (missing.length) { console.error("No license file shipped for: " + missing.join(", ")); process.exit(1); }
' > "$out/LICENSES.txt")
(cd "$out" && shasum -a 256 basic-pitch.mjs model/model.json model/group1-shard1of1.bin > SHA256SUMS)

if [ "$check" = 1 ]; then
  diff -r "$out" "$dest" && echo "vendor/basic-pitch-1.0.1 matches a fresh build"
else
  rm -rf "$dest"
  mkdir -p "$(dirname "$dest")"
  cp -R "$out" "$dest"
  cat "$dest/SHA256SUMS"
fi
