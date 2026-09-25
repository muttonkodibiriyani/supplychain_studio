"""Keep the preview bundle within tm8's supported static asset types."""
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "artifact"
for path in root.rglob("*"):
    if path.is_file() and path.suffix in {".zip", ".csv"}:
        path.unlink()
for name in ["index.html", "source-package.json", "templates/invoice.csv.txt", "templates/rms-item-master.csv.txt"]:
    if not (root / name).is_file():
        raise SystemExit(f"Required preview asset missing: {name}")
print("Static preview prepared with JSON source download and text templates")
