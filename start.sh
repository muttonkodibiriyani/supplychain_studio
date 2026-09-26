#!/usr/bin/env bash
# One-command start for Invoice Studio on macOS and Linux.
# Mirrors Start-InvoiceStudio.ps1: checks Docker, builds and starts the
# Compose project, waits for the health check, prints the URL and opens it.
#
# Usage: ./start.sh [--project-name NAME] [--port PORT] [--no-build] [--no-browser]
set -euo pipefail

PROJECT_NAME="invoice-studio"
PORT="8000"
BUILD=1
BROWSER=1

usage() {
    sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --project-name) PROJECT_NAME="${2:-}"; shift 2 ;;
        --port) PORT="${2:-}"; shift 2 ;;
        --no-build) BUILD=0; shift ;;
        --no-browser) BROWSER=0; shift ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

fail() {
    echo "" >&2
    echo "ERROR: $*" >&2
    exit 1
}

if ! printf '%s' "$PROJECT_NAME" | grep -Eq '^[a-z0-9][a-z0-9_-]*$'; then
    fail "Project name must be lowercase letters, digits, '-' or '_' and start with a letter or digit."
fi
if ! printf '%s' "$PORT" | grep -Eq '^[0-9]+$' || [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
    fail "Port must be a number between 1024 and 65535."
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

# Development clones only: point git at the in-repo pre-push privacy guard so a
# push from this clone runs scripts/package_source.py --check-only. Git never
# installs hooks on clone, so this is done here, on the first start. Idempotent,
# silent when already set, skipped in an unpacked source package (no .git).
if [ -d .git ] && command -v git >/dev/null 2>&1; then
    if [ "$(git config --get core.hooksPath 2>/dev/null || true)" != ".githooks" ]; then
        git config core.hooksPath .githooks
        echo "Installed the pre-push privacy guard for this clone (git config core.hooksPath .githooks)."
    fi
fi

if ! command -v docker >/dev/null 2>&1; then
    fail "Docker was not found. Follow docs/MAC_SETUP.md (macOS) or install Docker Engine (Linux), then open a new terminal."
fi

if ! engine="$(docker info --format '{{.OSType}}' 2>/dev/null)"; then
    fail "Docker is not ready. Open Docker Desktop and wait for the whale icon to stop animating, then try again."
fi
if [ "$engine" != "linux" ]; then
    fail "Invoice Studio uses Linux containers, but the Docker engine reports OS type '$engine'."
fi

if ! docker compose version >/dev/null 2>&1; then
    fail "'docker compose' is not available. Update Docker Desktop, or install the docker-compose-plugin on Linux."
fi

export INVOICE_HOST_PORT="$PORT"

if ! docker compose --project-name "$PROJECT_NAME" config --quiet; then
    fail "Docker Compose configuration failed. Run this script from the application folder that contains compose.yaml."
fi

# If another process already owns the port and it is not this project, stop early with a clear message.
if docker compose --project-name "$PROJECT_NAME" ps --status running --quiet 2>/dev/null | grep -q .; then
    : # Our own project is already running; compose up will reconcile it.
elif (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
    # Something already accepts connections on the port (bash built-in probe; works on macOS and Linux without lsof).
    fail "Port $PORT is already in use by another program. Stop it, or rerun with: ./start.sh --port 8010"
fi

compose_args=(compose --project-name "$PROJECT_NAME" up --detach --wait --wait-timeout 180)
if [ "$BUILD" -eq 1 ]; then
    compose_args+=(--build)
fi

echo "Building and starting Invoice Studio (project: $PROJECT_NAME, port: $PORT)."
echo "The first build downloads images and packages and can take several minutes."
if ! docker "${compose_args[@]}"; then
    fail "Startup failed. Read the output above and the troubleshooting section in docs/MAC_SETUP.md."
fi

url="http://localhost:$PORT"
echo ""
echo "Workspace: $PROJECT_NAME"
echo "Open $url"
echo "Use this same project name on upgrades to retain your invoices and item master."
echo "For a different brand, choose both a different project name and an unused port."
docker compose --project-name "$PROJECT_NAME" ps

if [ "$BROWSER" -eq 1 ]; then
    if command -v open >/dev/null 2>&1; then
        open "$url" || true
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 || true
    fi
fi
