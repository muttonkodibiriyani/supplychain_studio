"""Build a source-only handoff archive; exclude session metadata and invoice data."""
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import base64
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "public" / "invoice-studio-source.zip"
PACKAGE_JSON = ROOT / "public" / "source-package.json"
FILES = ["README.md", "package.json", "package-lock.json", "tsconfig.json", "vite.config.ts",
         "playwright.config.ts", "index.html", "requirements.txt", "requirements.lock.txt",
         "Dockerfile", "compose.yaml", ".gitignore", ".dockerignore", ".env.preview",
         ".env.example", "Start-InvoiceStudio.ps1", "Start-InvoiceStudio.command", "start.sh"]
DIRECTORIES = ["src", "backend", "tests", "scripts", "public/templates"]
# docs/ is NOT packaged wholesale. Only documents a recipient installs or operates
# from are shipped; measurement records of customer data and of our own process
# (acceptance, corpus evaluation, volume results, release validation, verification)
# stay out of the archive by construction. A new docs file is excluded until named.
DOCUMENTATION = ["docs/MAC_SETUP.md", "docs/WINDOWS_SETUP.md", "docs/OPERATOR_TRAINING.md",
                 "docs/DELIVERY.md", "docs/OPEN_SOURCE.md", "docs/EXTRACTION.md"]
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".css", ".md", ".txt", ".html", ".svg", ".ps1"}
SYNTHETIC_FIXTURES = {"public/templates/invoice.csv", "public/templates/rms-item-master.csv",
                      "tests/fixtures/sample_invoice.csv", "tests/fixtures/sample_catalog.json"}

def allowed(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    return not path.is_symlink() and not any(part in {"__pycache__", ".pytest_cache", "node_modules"} for part in path.parts) and (
        path.suffix.lower() in SOURCE_SUFFIXES or relative in SYNTHETIC_FIXTURES
    )

def selected_files() -> list[Path]:
    paths = [ROOT / filename for filename in FILES]
    paths.extend([ROOT / "public/favicon.svg", ROOT / "public/THIRD_PARTY_NOTICES.txt"])
    paths.extend(ROOT / name for name in DOCUMENTATION)
    for dirname in DIRECTORIES:
        paths.extend(p for p in (ROOT / dirname).rglob("*") if p.is_file() and allowed(p))
    return sorted(set(paths))

# Secrets, coordination ids, and the identifier/capability class: a share link or a
# user id is private regardless of what it describes, and a home-directory path names
# an operator. Numeral forms (counts, sizes) are deliberately NOT listed: a numeral
# denylist false-positives inside ids and goes stale silently; the docs allowlist above
# handles that class by construction instead.
PRIVATE_CONTENT_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b01a0[0-9a-f]{4}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b"),
    re.compile(r"(?:docs|drive|sheets)\.google\.com/", re.IGNORECASE),
    re.compile(r"[?&](?:usp=sharing|ouid=|userId=|resourcekey=)", re.IGNORECASE),
    re.compile(r"(?<![\w.])/home/(?!your-name\b|<)[A-Za-z0-9._-]+/"),
    re.compile(r"(?<![\w.])/Users/(?!your-name\b|<)[A-Za-z0-9._-]+/"),
    re.compile(r"[A-Za-z]:\\Users\\(?!your-name\\|<)[A-Za-z0-9._-]+\\"),
]


def validate_source(paths: list[Path]) -> None:
    """Reject high-confidence secret/coordination leaks without printing their values.

    This supplements the file selection; review of customer-specific material is still
    required before publishing a release.
    """
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise SystemExit("Source package contains a symlink or an external path")
        content = path.read_text(encoding="utf-8")
        if any(pattern.search(content) for pattern in PRIVATE_CONTENT_PATTERNS):
            raise SystemExit(f"Potential private content in {path.relative_to(ROOT)}; inspect locally before publication")


# Directories never scanned when the tree is not a git checkout (an unzipped package,
# or a test root). In a checkout, git's own ignore rules decide instead.
UNSCANNED_DIRECTORIES = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache",
                         "dist", "data", ".runtime", "test-results", "playwright-report"}


def repository_text_files(root: Path = ROOT) -> list[Path]:
    """Every text file the repository would publish: tracked plus untracked-not-ignored.

    The archive allowlist decides what ships in the zip; GitHub publishes the whole
    tree. Outside a git checkout every regular file under root is a candidate.
    """
    try:
        listing = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=True,
        ).stdout.decode("utf-8", errors="surrogateescape")
        candidates = [root / name for name in listing.split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        candidates = [
            path for path in root.rglob("*")
            if not any(part in UNSCANNED_DIRECTORIES for part in path.relative_to(root).parts)
        ]
    text_files = []
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as handle:
            if b"\0" in handle.read(8192):
                continue  # binary: images, archives, workbooks; the allowlist keeps them out of the zip
        text_files.append(path)
    return sorted(text_files)


def validate_repository(root: Path = ROOT) -> None:
    """Fail closed on a private-pattern hit anywhere in the tree, not only in the archive.

    validate_source() checks the files the zip is written from. A file the allowlist
    excludes from the zip is still published by git, so it gets the same check here.
    The error names the file, never the matched value.
    """
    offending = []
    for path in repository_text_files(root):
        content = path.read_bytes().decode("utf-8", errors="replace")
        if any(pattern.search(content) for pattern in PRIVATE_CONTENT_PATTERNS):
            offending.append(path.relative_to(root).as_posix())
    if offending:
        raise SystemExit(
            "Potential private content in the repository tree (not necessarily in the package): "
            + ", ".join(offending) + "; inspect locally before publication"
        )

# --- Push range mode: scan the commits a push carries, not only the working tree.

ZERO_SHA = re.compile(r"^0{40,64}$")
REGULAR_BLOB_MODES = {"100644", "100755", "120000"}


def _git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True, input=stdin).stdout


def commits_in_push(root: Path, local_sha: str, remote_sha: str, remote: str = "origin") -> tuple[list[str], bool]:
    """Commits the remote will receive, and whether the all-history fallback was used.

    remote..local normally; for a new branch (remote sha all zeros) everything the named remote
    lacks, and if that yields nothing, every commit reachable from local."""
    if ZERO_SHA.match(remote_sha):
        commits = _git(root, "rev-list", local_sha, "--not", f"--remotes={remote}").decode().split()
        if commits:
            return commits, False
        return _git(root, "rev-list", local_sha).decode().split(), True
    return _git(root, "rev-list", f"{remote_sha}..{local_sha}").decode().split(), False


def blobs_introduced(root: Path, commits: list[str]) -> list[tuple[str, str, str]]:
    """(blob sha, path, commit) for every distinct file version any commit in the range adds or changes.

    Each commit is diffed against each of its parents (-m, --root), so a file added in one
    commit and deleted in a later one is still listed: deleting it from the tip does not
    remove it from what the push carries. A blob reintroduced in several commits is listed once."""
    seen: set[tuple[str, str]] = set()
    found = []
    for commit in commits:
        raw = _git(root, "diff-tree", "-r", "-m", "--root", "--no-commit-id", "-z", commit).decode("utf-8", errors="replace")
        fields = raw.split("\0")
        index = 0
        while index + 1 < len(fields) and fields[index]:
            meta, path = fields[index], fields[index + 1]
            index += 2
            _src_mode, dst_mode, _src_sha, dst_sha, status = meta.lstrip(":").split(" ")[:5]
            if status.startswith("D") or ZERO_SHA.match(dst_sha) or dst_mode not in REGULAR_BLOB_MODES:
                continue
            if (dst_sha, path) not in seen:
                seen.add((dst_sha, path))
                found.append((dst_sha, path, commit))
    return found


def scan_blobs(root: Path, blobs: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """(path, commit) for every file version whose content or path matches a listed pattern."""
    offending = []
    for blob_sha, path, commit in blobs:
        if any(pattern.search(path) for pattern in PRIVATE_CONTENT_PATTERNS):
            offending.append((path + " (in its path)", commit))
            continue
        content = _git(root, "cat-file", "blob", blob_sha)
        if b"\0" in content[:8192]:
            continue
        if any(pattern.search(content.decode("utf-8", errors="replace")) for pattern in PRIVATE_CONTENT_PATTERNS):
            offending.append((path, commit))
    return offending


def _published_commits(root: Path) -> set[str]:
    """Commits reachable from any remote-tracking ref: already off this machine."""
    return set(_git(root, "rev-list", "--remotes").decode().split())


def refusal_message(root: Path, offending: list[tuple[str, str]]) -> str:
    """Name the commit, the file and the exact remedy, so nobody has to guess or unset the hook.

    A hit in a commit already reachable from a remote-tracking ref is history that left this
    machine earlier (the new-branch scan reaches it); only a history rewrite removes it."""
    published = _published_commits(root)
    lines = ["Push privacy guard refused this push."]
    for path, commit in offending:
        short = commit[:12]
        if commit in published:
            lines.append(
                f"- the history of this repository carries previously removed content at {short} ({path}): "
                "the repository owner must rewrite history before this push; do not bypass the hook"
            )
        else:
            lines.append(
                f"- commit {short} introduces {path}, which matches a listed private-content pattern: "
                f"remove it from that commit (git rebase -i {short}~1 and edit, or git reset --soft {short}~1 "
                "and recommit without it), then push again; deleting the file in a later commit does not "
                "remove it from the push; do not bypass the hook"
            )
    return "\n".join(lines)


def validate_push(root: Path, ref_lines: list[str], remote: str = "origin") -> tuple[int, int]:
    """Fail closed on any listed pattern in the pushed commits, and on any error at all.

    Returns (distinct commits, distinct file versions) scanned."""
    commits: list[str] = []
    try:
        for line in ref_lines:
            parts = line.split()
            if len(parts) != 4:
                continue
            _local_ref, local_sha, _remote_ref, remote_sha = parts
            if ZERO_SHA.match(local_sha):
                continue  # branch deletion carries no content
            found, _all_history = commits_in_push(root, local_sha, remote_sha, remote)
            commits.extend(c for c in found if c not in commits)
        blobs = blobs_introduced(root, commits)
        offending = scan_blobs(root, blobs)
        if offending:
            raise SystemExit(refusal_message(root, offending))
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, ValueError) as error:
        raise SystemExit("Push privacy guard could not inspect the commits being pushed and refused the push: "
                         + type(error).__name__ + "; fix the repository state (or install git) and push again; "
                         "do not bypass the hook") from error
    return len(commits), len(blobs)


def pre_push(root: Path = ROOT, remote: str = "origin", stream=None) -> int:
    ref_lines = [line for line in (stream or sys.stdin).read().splitlines() if line.strip()]
    commit_count, blob_count = validate_push(root, ref_lines, remote)
    print(f"Push privacy guard: {commit_count} distinct commits, {blob_count} distinct file versions scanned, "
          "no listed pattern found")
    return 0


def pending_push_ref_line(root: Path, explicit_range: str | None = None) -> tuple[str, str] | None:
    """The ref line the next `git push` would hand the hook, and the remote name; None outside a checkout.

    Default: HEAD against its upstream, else against origin/<branch>, else a new branch (all zeros)
    with the same fallbacks as the push path. An explicit "<remote sha>..<local sha>" overrides it."""
    inside = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    if explicit_range:
        remote_sha, _, local_sha = explicit_range.partition("..")
        local_sha = _git(root, "rev-parse", local_sha or "HEAD").decode().strip()
        remote_sha = remote_sha if ZERO_SHA.match(remote_sha) else _git(root, "rev-parse", remote_sha).decode().strip()
        return f"refs/heads/HEAD {local_sha} refs/heads/HEAD {remote_sha}", "origin"
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    branch = subprocess.run(["git", "-C", str(root), "symbolic-ref", "--short", "-q", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    remote = subprocess.run(["git", "-C", str(root), "config", f"branch.{branch}.remote"],
                            capture_output=True, text=True).stdout.strip() or "origin" if branch else "origin"
    for candidate in ([f"{branch}@{{upstream}}", f"refs/remotes/{remote}/{branch}"] if branch else []):
        probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "-q", candidate + "^{commit}"],
                               capture_output=True, text=True)
        if probe.returncode == 0:
            remote_sha = probe.stdout.strip()
            break
    else:
        remote_sha = "0" * 40
    ref = f"refs/heads/{branch or 'HEAD'}"
    return f"{ref} {head} {ref} {remote_sha}", remote


def check_only(root: Path = ROOT, explicit_range: str | None = None) -> int:
    """Entry point for CI and pre-flight: the tree guard, then the same range scan the push hook runs."""
    validate_repository(root)
    print(f"Repository privacy guard: {len(repository_text_files(root))} text files scanned, no listed pattern found")
    pending = pending_push_ref_line(root, explicit_range)
    if pending is None:
        print("Push range not covered: not inside a git checkout, so there is nothing to push from here")
        return 0
    ref_line, remote = pending
    commit_count, blob_count = validate_push(root, [ref_line], remote)
    _local_ref, local_sha, _remote_ref, remote_sha = ref_line.split()
    print(f"Push privacy guard (pre-flight, {remote_sha[:12]}..{local_sha[:12]}): {commit_count} distinct commits, "
          f"{blob_count} distinct file versions scanned, no listed pattern found")
    return 0


def main() -> None:
    arguments = sys.argv[1:]
    if "--check-only" in arguments:
        # Optional: --range <remote sha>..<local sha> (CI passes the event's before..after pair).
        explicit_range = arguments[arguments.index("--range") + 1] if "--range" in arguments else None
        raise SystemExit(check_only(ROOT, explicit_range))
    if "--pre-push" in arguments:
        # git pre-push hook: argv is (remote name, remote url); ref lines arrive on stdin.
        after = arguments[arguments.index("--pre-push") + 1:]
        raise SystemExit(pre_push(ROOT, after[0] if after else "origin"))
    validate_repository(ROOT)
    for template in (ROOT / "public/templates").glob("*.csv"):
        template.with_suffix(".csv.txt").write_bytes(template.read_bytes())
    paths = selected_files()
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise SystemExit(f"Required package files missing: {', '.join(missing)}")
    validate_source(paths)
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(set(paths)):
            entry = ZipInfo(str(Path("invoice-studio") / path.relative_to(ROOT)), (2026, 9, 24, 0, 0, 0))
            entry.external_attr = (path.stat().st_mode & 0xFFFF) << 16
            archive.writestr(entry, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
    with ZipFile(OUTPUT) as archive:
        names = set(archive.namelist())
        required = {f"invoice-studio/{name}" for name in [
            "public/THIRD_PARTY_NOTICES.txt", "backend/app.py", "backend/extraction.py",
            "src/App.tsx", "compose.yaml", "requirements.lock.txt", "docs/MAC_SETUP.md",
            "docs/WINDOWS_SETUP.md", "start.sh", "Start-InvoiceStudio.command",
            "Start-InvoiceStudio.ps1",
        ]}
        if not required.issubset(names):
            raise SystemExit(f"Package missing required entries: {required - names}")
        if any("task-context" in name or "/data/" in name or "/.runtime/" in name for name in names):
            raise SystemExit("Package contains session metadata or runtime data")
        if archive.testzip() is not None:
            raise SystemExit("Archive integrity check failed")
    print(f"Packaged {len(set(paths))} files: {OUTPUT.name} ({OUTPUT.stat().st_size:,} bytes)")
    # The tm8 static bundle accepts JSON assets. Supply a client-downloadable
    # package as data; the original ZIP is also attached to the task separately.
    data = OUTPUT.read_bytes()
    PACKAGE_JSON.write_text(json.dumps({
        "filename": OUTPUT.name, "mime": "application/zip",
        "sha256": hashlib.sha256(data).hexdigest(),
        "base64": base64.b64encode(data).decode("ascii"),
    }))

if __name__ == "__main__":
    main()
