"""SEC.9: the hashed requirement locks and the pinned CI actions.

The requirements-*.in files are what a person edits; tools/locks/compile.sh compiles each into the
requirements-*.txt lock that is installed (Vercel installs requirements.txt). These tests check that
every lock still satisfies its source, that every package in a lock carries hashes (so pip and uv
check each file), and that CI pins its actions to commit SHAs and audits every lock.
"""
import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent
LOCKS = {
    "requirements.txt": "requirements.in",
    "requirements-dev.txt": "requirements-dev.in",
    "requirements-e2e.txt": "requirements-e2e.in",
    "requirements-desktop.txt": "requirements-desktop.in",
    "requirements-models.txt": "requirements-models.in",
    "tools/locks/audit.txt": "tools/locks/audit.in",
}
# The models lock is compiled for the Mac app on Apple silicon (compile.sh), so its markers are read there.
MAC_ARM64 = {"sys_platform": "darwin", "platform_machine": "arm64", "platform_system": "Darwin"}


def source_requirements(path: Path):
    """The requirements in a .in file and the files it includes with -r."""
    out = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            out += source_requirements(path.parent / line[3:].strip())
        elif not line.startswith("-"):
            out.append(Requirement(line))
    return out


def lock_entries(path: Path):
    """{name: (version, hashes)} from a compiled lock (one `name==version \\` line, then its hashes)."""
    entries, name = {}, None
    for line in path.read_text().splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?==([^\s;\\]+)", line)
        if m:
            name = canonicalize_name(m.group(1))
            entries[name] = (m.group(3), [])
        elif name and line.strip().startswith("--hash=sha256:"):
            entries[name][1].append(line.strip().split(":", 1)[1].rstrip(" \\"))
    return entries


@pytest.mark.parametrize("lock,source", LOCKS.items())
def test_every_package_in_a_lock_is_pinned_with_hashes(lock, source):
    text = (ROOT / lock).read_text()
    entries = lock_entries(ROOT / lock)
    assert entries, lock
    # Every requirement line is an exact pin: nothing unpinned slips past the hash check.
    reqs = [l for l in text.splitlines() if l and not l[0].isspace() and not l.startswith("#")]
    assert len(reqs) == len(entries), [l for l in reqs if "==" not in l]
    for name, (version, hashes) in entries.items():
        assert hashes and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes), (lock, name)


@pytest.mark.parametrize("lock,source", LOCKS.items())
def test_every_lock_satisfies_its_source(lock, source):
    entries = lock_entries(ROOT / lock)
    env = MAC_ARM64 if lock == "requirements-models.txt" else None
    for req in source_requirements(ROOT / source):
        if req.marker is not None and not req.marker.evaluate(env):
            continue
        name = canonicalize_name(req.name)
        assert name in entries, f"{lock} does not lock {req.name}: run sh tools/locks/compile.sh"
        assert req.specifier.contains(entries[name][0], prereleases=True), \
            f"{lock} has {req.name}=={entries[name][0]}, {source} asks {req.specifier}: run sh tools/locks/compile.sh"


def test_the_hosted_lock_does_not_carry_the_model_packages():
    # The hosted app must never install the Mac app's model runtime (MODEL.1).
    assert not {"torch", "transformers", "demucs", "mlx"} & set(lock_entries(ROOT / "requirements.txt"))


def test_the_environments_built_on_the_hosted_app_lock_its_versions():
    hosted = lock_entries(ROOT / "requirements.txt")
    for lock in ("requirements-dev.txt", "requirements-e2e.txt", "requirements-desktop.txt"):
        entries = lock_entries(ROOT / lock)
        for name, (version, _) in hosted.items():
            if name in entries:
                assert entries[name][0] == version, (lock, name)


def workflow_steps():
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for n, line in enumerate(wf.read_text().splitlines(), 1):
            m = re.match(r"^\s*-?\s*uses:\s*(\S+)", line)
            if m:
                yield wf.name, n, m.group(1), line


def test_every_ci_action_is_pinned_to_a_commit():
    steps = list(workflow_steps())
    assert steps
    for name, n, ref, line in steps:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{name}:{n} {ref} is not pinned to a commit SHA"
        assert re.search(r"#\s*v\d", line), f"{name}:{n} says which release the SHA is"


def test_ci_audits_every_lock_and_installs_the_auditor_from_its_lock():
    text = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    audit = text[text.index("\n  audit:"):text.index("\n  backend:")]
    assert "pip install -r tools/locks/audit.txt" in audit
    for lock in LOCKS:
        if lock.startswith("requirements"):
            assert lock in audit, f"the audit job does not audit {lock}"
    assert "pip_audit" in audit and "--require-hashes" in audit


def test_ci_installs_the_backend_and_e2e_jobs_from_the_locks():
    text = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert "pip install -r requirements-dev.txt" in text
    assert "pip install -r requirements-e2e.txt" in text
