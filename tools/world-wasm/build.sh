#!/usr/bin/env bash
# Build the WORLD vocoder as WebAssembly for on-device pitch correction (VOX.4).
#
#   bash tools/world-wasm/build.sh          # rebuild vendor/world-d625e76-1
#   bash tools/world-wasm/build.sh --check  # rebuild in a temp dir and fail if
#                                           # the committed files differ
#
# WORLD (modified BSD, https://github.com/mmorise/World) is downloaded at commit
# d625e76, the commit pyworld 0.3.6 (the server's pyworld-prebuilt) is built from,
# and the tarball is checked against its SHA-256 before it is compiled. Needs
# Emscripten (brew install emscripten); the version used is recorded in
# LICENSES.txt, and --check needs the same version, because another compiler
# writes other bytes. The output files and their SHA-256 hashes are committed;
# tests/test_api.py checks the served bytes against SHA256SUMS.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
dest="$repo/vendor/world-d625e76-1"
commit="d625e7608ca23a870018f01e7c562ac683d9847f"
tarball_sha256="4df012b972586b0579ef47ecc7f6b2841b420829e41585498c8cf64d41bddfa8"
emcc_version="7.0.0"
check=0
[ "${1:-}" = "--check" ] && check=1

have="$(emcc --version | head -1 | sed -E 's/.* ([0-9]+\.[0-9]+\.[0-9]+).*/\1/')"
if [ "$have" != "$emcc_version" ]; then
  echo "build.sh: Emscripten $emcc_version is required (found ${have:-none})" >&2
  exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
curl -sSfL -o "$work/world.tar.gz" "https://codeload.github.com/mmorise/World/tar.gz/$commit"
echo "$tarball_sha256  $work/world.tar.gz" | shasum -a 256 -c - >/dev/null
tar xzf "$work/world.tar.gz" -C "$work"
src="$work/World-$commit/src"

out="$work/out"
mkdir -p "$out"
# Only the files the five calls need. -ffp-contract=off keeps a*b+c from being fused, which
# would round differently from the server's build.
(cd "$work" && em++ -O3 -ffp-contract=off -I"$src" \
  "$src/dio.cpp" "$src/stonemask.cpp" "$src/cheaptrick.cpp" "$src/d4c.cpp" "$src/synthesis.cpp" \
  "$src/common.cpp" "$src/fft.cpp" "$src/matlabfunctions.cpp" "$here/tandem_world.cpp" \
  -sMODULARIZE=1 -sEXPORT_ES6=1 -sEXPORT_NAME=createWorld -sENVIRONMENT=web,worker,node \
  -sALLOW_MEMORY_GROWTH=1 -sMAXIMUM_MEMORY=2GB -sFILESYSTEM=0 -sINITIAL_MEMORY=32MB \
  -sEXPORTED_FUNCTIONS=_tw_frames,_tw_f0,_tw_resynth,_malloc,_free \
  -sEXPORTED_RUNTIME_METHODS=HEAPF64 \
  -o "$out/world.mjs")
{
  echo "world.mjs and world.wasm: the WORLD vocoder (https://github.com/mmorise/World),"
  echo "commit $commit, with tools/world-wasm/tandem_world.cpp, compiled by"
  echo "Emscripten $emcc_version (whose runtime is MIT-licensed) with tools/world-wasm/build.sh."
  echo
  echo "=== WORLD: LICENSE.txt ==="
  cat "$work/World-$commit/LICENSE.txt"
} > "$out/LICENSES.txt"
(cd "$out" && shasum -a 256 LICENSES.txt world.mjs world.wasm > SHA256SUMS)

if [ "$check" = 1 ]; then
  diff -r "$out" "$dest" && echo "vendor/world-d625e76-1 matches a fresh build"
else
  rm -rf "$dest"
  mkdir -p "$dest"
  cp "$out"/* "$dest/"
  cat "$dest/SHA256SUMS"
fi
