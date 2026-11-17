#!/bin/sh
# SEC.9: compile the hashed requirement locks from the *.in sources. Run from the repository root
# after changing a requirements-*.in file (needs uv: https://docs.astral.sh/uv/):
#   sh tools/locks/compile.sh            # keep the locked versions where the sources allow
#   sh tools/locks/compile.sh --upgrade  # take the newest versions the sources allow
# Each lock is compiled against the one it builds on (-c), so every environment gets the hosted app's
# versions, except the models lock: magenta-rt needs numpy below 2.4, so it resolves on its own. requirements.txt is what Vercel installs; pip and uv check every hash, so a changed or
# replaced file on the index fails the install. The hosted, dev and e2e locks are universal (any OS,
# CPython 3.12); the desktop lock is universal too; the models lock is for the Mac app on Apple
# silicon only (torch has no Intel macOS wheel and MLX is Apple silicon only), macOS 14 or later as torch's wheels need.
set -eu
cd "$(dirname "$0")/../.."
compile() { uv pip compile --quiet --python-version 3.12 --generate-hashes --no-header "$@"; }
compile ${1:-} --universal requirements.in -o requirements.txt
# e2e first: pytest-playwright caps pytest, and the dev lock must use the same pytest.
compile ${1:-} --universal requirements-e2e.in -c requirements.txt -o requirements-e2e.txt
compile ${1:-} --universal requirements-dev.in -c requirements-e2e.txt -o requirements-dev.txt
compile ${1:-} --universal requirements-desktop.in -c requirements.txt -o requirements-desktop.txt
MACOSX_DEPLOYMENT_TARGET=14.0 compile ${1:-} --python-platform aarch64-apple-darwin requirements-models.in -o requirements-models.txt
compile ${1:-} --universal tools/locks/audit.in -o tools/locks/audit.txt
