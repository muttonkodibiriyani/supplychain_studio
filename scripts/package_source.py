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


def commits_in_push(root: Path, local_sha: str, remote_sha: str, remote: str = "origin") -> list[str]:
    """Commits the remote will receive: remote..local, or for a new branch everything the remote lacks."""
    if ZERO_SHA.match(remote_sha):
        commits = _git(root, "rev-list", local_sha, "--not", f"--remotes={remote}").decode().split()
        if not commits:
            commits = _git(root, "rev-list", local_sha).decode().split()
        return commits
    return _git(root, "rev-list", f"{remote_sha}..{local_sha}").decode().split()


def blobs_introduced(root: Path, commits: list[str]) -> list[tuple[str, str, str]]:
    """(blob sha, path, commit) for every file version any commit in the range adds or changes.

    Each commit is diffed against each of its parents (-m, --root), so a file added in one
    commit and deleted in a later one is still listed: deleting it from the tip does not
    remove it from what the push carries."""
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


def scan_blobs(root: Path, blobs: list[tuple[str, str, str]]) -> list[str]:
    """Names of files (with their commit) whose content or path matches a listed pattern."""
    offending = []
    for blob_sha, path, commit in blobs:
        if any(pattern.search(path) for pattern in PRIVATE_CONTENT_PATTERNS):
            offending.append(f"{path} (path, commit {commit[:12]})")
            continue
        content = _git(root, "cat-file", "blob", blob_sha)
        if b"\0" in content[:8192]:
            continue
        if any(pattern.search(content.decode("utf-8", errors="replace")) for pattern in PRIVATE_CONTENT_PATTERNS):
            offending.append(f"{path} (commit {commit[:12]})")
    return offending


def validate_push(root: Path, ref_lines: list[str], remote: str = "origin") -> tuple[int, int]:
    """Fail closed on any listed pattern in the pushed commits, and on any error at all."""
    commits: list[str] = []
    try:
        for line in ref_lines:
            parts = line.split()
            if len(parts) != 4:
                continue
            _local_ref, local_sha, _remote_ref, remote_sha = parts
            if ZERO_SHA.match(local_sha):
                continue  # branch deletion carries no content
            commits.extend(c for c in commits_in_push(root, local_sha, remote_sha, remote) if c not in commits)
        blobs = blobs_introduced(root, commits)
        offending = scan_blobs(root, blobs)
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, ValueError) as error:
        raise SystemExit("Push privacy guard could not inspect the commits being pushed and refused the push: "
                         + type(error).__name__) from error
    if offending:
        raise SystemExit("Potential private content in the commits being pushed (not necessarily in the working tree): "
                         + ", ".join(offending) + "; the push was refused. Rewrite the commits, do not just delete the file.")
    return len(commits), len(blobs)


def pre_push(root: Path = ROOT, remote: str = "origin", stream=None) -> int:
    ref_lines = [line for line in (stream or sys.stdin).read().splitlines() if line.strip()]
    commit_count, blob_count = validate_push(root, ref_lines, remote)
    print(f"Push privacy guard: {commit_count} commits, {blob_count} file versions scanned, no listed pattern found")
    return 0


def check_only(root: Path = ROOT) -> int:
    """Entry point for CI and the pre-push hook: tree guard only, no archive."""
    validate_repository(root)
    print(f"Repository privacy guard: {len(repository_text_files(root))} text files scanned, no listed pattern found")
    return 0


def main() -> None:
    arguments = sys.argv[1:]
    if "--check-only" in arguments:
        raise SystemExit(check_only(ROOT))
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
