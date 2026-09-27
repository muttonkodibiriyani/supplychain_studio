"""Build a source-only handoff archive; exclude session metadata and invoice data."""
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import base64
import hashlib
import json
import re

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

def main() -> None:
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
