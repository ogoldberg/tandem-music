#!/usr/bin/env bash
# FX.0: build the MPC Plugin SDK's StereoDelay port (stereo_delay.cpp) as WebAssembly and natively.
#
#   bash tools/fx-spike/build.sh <out-dir>
#
# The SDK (MIT, https://github.com/inmusic-software/mpc-plugin-builder-sdk) is downloaded at commit
# febd2ca and checked against its SHA-256; only its framework/dsp/ headers are used. Writes
# <out-dir>/delay.wasm (standalone, no Emscripten JS glue, so an AudioWorklet can instantiate it from
# its bytes) and <out-dir>/fx-native. Both are built with -O3 -ffp-contract=off, so neither compiler
# fuses a*b+c and both round every float operation the same way. Needs Emscripten 7.0.0 (the VOX.4
# setup, brew install emscripten) and a host clang++. Nothing in Tandem uses the output.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
out="${1:?usage: build.sh <out-dir>}"
commit="febd2ca5bd9eb16c4a412837196e145566bc981b"
tarball_sha256="b3e71b1f1ec84ff272a240f25de633d285710d07a9b39760b932dda4334e7b8b"
emcc_version="7.0.0"

have="$(emcc --version | head -1 | sed -E 's/.* ([0-9]+\.[0-9]+\.[0-9]+).*/\1/')"
if [ "$have" != "$emcc_version" ]; then
  echo "build.sh: Emscripten $emcc_version is required (found ${have:-none})" >&2
  exit 1
fi

mkdir -p "$out"
out="$(cd "$out" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
curl -sSfL -o "$work/sdk.tar.gz" "https://codeload.github.com/inmusic-software/mpc-plugin-builder-sdk/tar.gz/$commit"
echo "$tarball_sha256  $work/sdk.tar.gz" | shasum -a 256 -c - >/dev/null
tar xzf "$work/sdk.tar.gz" -C "$work"
sdk="$work/mpc-plugin-builder-sdk-$commit/framework"

(cd "$work" && em++ -O3 -ffp-contract=off -std=c++17 -I"$sdk" "$here/stereo_delay.cpp" \
  -sSTANDALONE_WASM=1 --no-entry -sALLOW_MEMORY_GROWTH=0 -sINITIAL_MEMORY=16MB -sFILESYSTEM=0 \
  -sEXPORTED_FUNCTIONS=_fx_create,_fx_set,_fx_reset,_fx_in,_fx_out,_fx_process,_fx_destroy \
  -o "$out/delay.wasm")
clang++ -O3 -ffp-contract=off -std=c++17 -I"$sdk" "$here/stereo_delay.cpp" "$here/native_main.cpp" \
  -o "$out/fx-native"
cp "$work/mpc-plugin-builder-sdk-$commit/LICENSE" "$out/MPC-SDK-LICENSE.txt"
(cd "$out" && shasum -a 256 delay.wasm fx-native)
