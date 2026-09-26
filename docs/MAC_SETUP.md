# Invoice Studio on a fresh Mac

Validation limit: these macOS instructions were authored and reviewed against the Windows guide, but were not executed end to end on a physical Mac. What was verified, and how, is stated in [section 12](#12-what-was-verified-for-apple-silicon-and-intel-macs). Treat the first Mac installation as a pilot and confirm each checkpoint before importing real data.

This guide installs and runs Invoice Studio with Docker Desktop for Mac. It is written for an operator who has a new Mac and has not installed Python, Node.js, Tesseract, Git, Homebrew, or any developer tools. None of those are needed. Docker builds every application component inside a Linux container. Excel, Numbers, or another approved XLSX viewer is only needed to inspect the finished workbook.

The application is a local pilot. It listens only on `localhost`, has no application login or user roles, and must be used on one access-controlled computer by one authorized operator at a time. Do not publish its port to the office network or the internet.

## 1. Check the Mac

- **Apple Silicon (M1, M2, M3, M4 or later) or Intel.** Both are supported. Docker Desktop's system requirements at the time of writing (25 September 2026) call for a supported macOS release: the current version and the two previous major versions. Check **Apple menu > About This Mac**. If the Mac is older than that, update macOS first or ask IT.
- At least 8 GB RAM and 10 GB free disk space. 16 GB RAM is recommended when processing large scanned batches with more extraction workers (see [Throughput](VOLUME_RESULTS.md)).
- Administrator rights on the Mac for the one-time Docker Desktop install. Day-to-day use does not need them.
- Rosetta is **not** required. Every image the application uses has a native Apple Silicon (arm64) build; see section 12.

## 2. Install Docker Desktop

1. Download Docker Desktop for Mac from the official page, [https://docs.docker.com/desktop/setup/install/mac-install/](https://docs.docker.com/desktop/setup/install/mac-install/). Choose **Apple Silicon** or **Intel chip** to match **About This Mac**. Do not use a copy from a search result, a file share, or an email.
2. Open the downloaded `Docker.dmg` and drag **Docker** into **Applications**.
3. Open **Docker** from Applications. Accept the service agreement and, if prompted, enter the administrator password so it can install its helper.
4. Wait until the whale icon in the menu bar stops animating and shows **Docker Desktop is running**. The first start can take a minute.
5. You do not need a Docker account. If it asks you to sign in, choose to continue without signing in.

Confirm it works. Open **Terminal** (Applications > Utilities > Terminal, or press Command-Space and type `Terminal`) and run:

```bash
docker version
docker compose version
```

Both commands must print a client and server version. If `docker` is "command not found", quit and reopen Terminal after Docker Desktop has fully started.

## 3. Download the application from GitHub

Open the private repository [muttonkodibiriyani/supplychain_studio](https://github.com/muttonkodibiriyani/supplychain_studio), or the release link supplied by the application owner. Confirm that the owner, repository, release tag, and checksum are the ones approved by your organization. Do not use a fork, mirror, email attachment, or link from a search result.

1. Sign in to the organization-approved GitHub account. The private repository appears only when that account has read access. Select **Code > Download ZIP**.
2. In Finder, double-click the ZIP in Downloads. macOS extracts it to a folder next to it.
3. Move the extracted folder to a stable, private location under your account, for example `~/InvoiceStudio/app-1.0.0`.
4. Open that folder and confirm that `compose.yaml`, `Dockerfile`, `start.sh` and `Start-InvoiceStudio.command` are present.

The application source folder must contain code and fictional examples only. Never copy real invoices, RMS extracts, supplier records, generated workbooks, Docker-volume backups, credentials, or the private `data/reference` material into this folder. See [Keep real business data out of GitHub](#10-keep-real-business-data-out-of-github).

## 4. First start: one command

With Docker Desktop running, there are two equivalent ways to start.

**Option A, double-click.** In Finder, open the application folder and double-click **`Start-InvoiceStudio.command`**. macOS opens Terminal and runs the start script. On the very first use, macOS may say the file "cannot be opened because it is from an unidentified developer": right-click (or Control-click) the file, choose **Open**, then **Open** again in the dialog. That is only asked once. If Terminal reports "permission denied", run the Option B command once instead; the ZIP extraction sometimes drops the execute permission.

**Option B, Terminal.** Open Terminal, then:

```bash
cd ~/InvoiceStudio/app-1.0.0
chmod +x start.sh Start-InvoiceStudio.command
./start.sh
```

Either way the script:

1. checks that Docker is installed, running, and using Linux containers;
2. validates the Compose configuration;
3. stops with a clear message if port 8000 is taken by something else;
4. builds the image and starts the service (`docker compose --project-name invoice-studio up --build --detach --wait`);
5. waits for the health check, prints the URL and the container status;
6. opens **http://localhost:8000** in your default browser.

The first build downloads base images, Python packages and the English Tesseract OCR data and can take several minutes. Later starts take seconds. When the browser opens on the Invoice Studio page, the installation is complete. Continue with the [operator training guide](OPERATOR_TRAINING.md) to set up the brand and import its item master.

The direct Compose commands are the canonical procedure and are what the script runs for you:

```bash
cd ~/InvoiceStudio/app-1.0.0
docker compose --project-name invoice-studio up --build --detach --wait --wait-timeout 180
docker compose --project-name invoice-studio ps
curl -s http://localhost:8000/api/health
open http://localhost:8000
```

Do not add `?preview=1` to the URL; that opens fictional preview data rather than the durable brand workspace.

## 5. One isolated instance per brand

Every brand must have its own lowercase brand slug, Compose project name, localhost port, Docker data volume, RMS item master and reviewed mappings, and backups. Do not put several brands into one instance.

The start script takes the project name and port as options. For the Ulta UAE instance on port 8000 and a second brand on port 8001:

```bash
./start.sh --project-name invoice-studio-ulta-ae --port 8000
./start.sh --project-name invoice-studio-brand-b --port 8001
```

Use only lowercase letters, numbers, hyphens and underscores in the project name. Keep a controlled brand-instance register outside the GitHub source folder: brand name, slug, port, project name, item-master date, last backup date, and operator owner.

The port changes only the Mac-side localhost port; the service still listens on 8000 inside its container. The fixed project name makes Docker reuse the same brand volume when a newer ZIP is extracted into a differently named folder. Docker names the volume `<project-name>_invoice-data`. It contains the SQLite database, accepted source documents, learned mappings, and generated exports. Deleting the source folder does not delete that volume; deleting the Docker volume does.

The examples below use shell variables. Set them at the start of every Terminal session for the brand you are working on:

```bash
BRAND_SLUG="ulta-ae"
PORT="8000"
PROJECT_NAME="invoice-studio-$BRAND_SLUG"
export INVOICE_HOST_PORT="$PORT"
```

Validate the configuration before starting it and confirm that under `ports` the published address is `127.0.0.1` and your chosen port, never `0.0.0.0`:

```bash
docker compose --project-name "$PROJECT_NAME" config
```

## 6. Daily start, status, logs, restart, and stop

Start Docker Desktop first (Applications > Docker, or the whale icon). Then either double-click `Start-InvoiceStudio.command`, or open Terminal in the application folder, set the brand variables from section 5, and use the commands below.

Start or recreate the brand service while keeping its existing volume:

```bash
docker compose --project-name "$PROJECT_NAME" up --detach --wait --wait-timeout 180
open "http://localhost:$PORT"
```

Check its state and health:

```bash
docker compose --project-name "$PROJECT_NAME" ps
curl -s "http://localhost:$PORT/api/health"
```

Show the most recent log entries, or follow new ones until you press Control-C:

```bash
docker compose --project-name "$PROJECT_NAME" logs --tail 200 invoice-review
docker compose --project-name "$PROJECT_NAME" logs --follow invoice-review
```

Restart the application process without deleting data:

```bash
docker compose --project-name "$PROJECT_NAME" restart invoice-review
```

Stop it at the end of the day while retaining the container and data, and start it again later:

```bash
docker compose --project-name "$PROJECT_NAME" stop
docker compose --project-name "$PROJECT_NAME" start
```

You may instead remove the container and its network while preserving the named volume; the next `up` recreates them:

```bash
docker compose --project-name "$PROJECT_NAME" down
```

**Never add `--volumes` or `-v` to `docker compose down`.** Those options delete the brand's data volume. Do not run `docker volume prune` on an operating Mac. Ordinary [`docker compose down`](https://docs.docker.com/reference/cli/docker/compose/down/) preserves named volumes.

Quitting Docker Desktop stops the containers; they start again with the next `start.sh` or `up`.

## 7. Back up a brand

Back up before every application update, before Docker Desktop repair or removal, after an important reviewed batch, and on the schedule approved by Finance/IT. Stop the brand service first so SQLite and stored files form one consistent snapshot. Set the brand variables from section 5, then:

```bash
BACKUP_ROOT="$HOME/InvoiceStudioBackups/$BRAND_SLUG"
mkdir -p "$BACKUP_ROOT"
BACKUP_FILE="invoice-data-$BRAND_SLUG-$(date +%Y%m%d-%H%M%S).tar.gz"
VOLUME_NAME="${PROJECT_NAME}_invoice-data"
docker compose --project-name "$PROJECT_NAME" stop invoice-review
docker volume inspect "$VOLUME_NAME" >/dev/null
docker run --rm \
  --mount "type=volume,source=$VOLUME_NAME,target=/source,readonly" \
  --mount "type=bind,source=$BACKUP_ROOT,target=/backup" \
  --env "BACKUP_FILE=$BACKUP_FILE" \
  alpine:3.22 sh -c 'tar -czf "/backup/$BACKUP_FILE" -C /source .'
docker run --rm \
  --mount "type=bind,source=$BACKUP_ROOT,target=/backup,readonly" \
  --env "BACKUP_FILE=$BACKUP_FILE" \
  alpine:3.22 sh -c 'tar -tzf "/backup/$BACKUP_FILE" >/dev/null'
shasum -a 256 "$BACKUP_ROOT/$BACKUP_FILE" | awk '{print $1}' > "$BACKUP_ROOT/$BACKUP_FILE.sha256.txt"
ls -l "$BACKUP_ROOT/$BACKUP_FILE" "$BACKUP_ROOT/$BACKUP_FILE.sha256.txt"
docker compose --project-name "$PROJECT_NAME" start invoice-review
```

If any command prints an error, keep the application stopped and contact support. Confirm that both the `.tar.gz` and `.sha256.txt` files exist and are not zero bytes. Store them in an access-controlled, encrypted location approved for supplier and finance data. A backup contains confidential invoice originals and master/mapping data; do not email it, attach it to a ticket, or place it in GitHub. Docker documents this pattern under [Back up, restore, or migrate data volumes](https://docs.docker.com/engine/storage/volumes/#back-up-restore-or-migrate-data-volumes).

## 8. Restore a brand from a backup

Restore replaces the entire selected brand volume. Check the brand slug, project name, backup filename, and application version twice. Keep the current volume until you have a separate verified backup of it.

1. Put the approved `.tar.gz` and `.sha256.txt` files in `~/InvoiceStudioBackups/<brand-slug>`.
2. Open Terminal in the application source folder for the version you intend to run and set the brand variables from section 5.
3. Set the exact backup filename, without changing it:
   ```bash
   BACKUP_ROOT="$HOME/InvoiceStudioBackups/$BRAND_SLUG"
   BACKUP_FILE="invoice-data-ulta-ae-20260925-170000.tar.gz"
   VOLUME_NAME="${PROJECT_NAME}_invoice-data"
   ```
4. Validate the file and recorded hash before changing Docker data. Every line must succeed:
   ```bash
   test -f "$BACKUP_ROOT/$BACKUP_FILE" || echo "Backup file not found"
   test -f "$BACKUP_ROOT/$BACKUP_FILE.sha256.txt" || echo "SHA256 file not found"
   [ "$(shasum -a 256 "$BACKUP_ROOT/$BACKUP_FILE" | awk '{print $1}')" = "$(tr -d '[:space:]' < "$BACKUP_ROOT/$BACKUP_FILE.sha256.txt")" ] && echo "Hash OK" || echo "HASH MISMATCH. Do not restore."
   docker run --rm \
     --mount "type=bind,source=$BACKUP_ROOT,target=/backup,readonly" \
     --env "BACKUP_FILE=$BACKUP_FILE" \
     alpine:3.22 sh -c 'tar -tzf "/backup/$BACKUP_FILE" >/dev/null' && echo "Archive OK"
   ```
5. Replace only the selected brand volume and restore the archive:
   ```bash
   docker compose --project-name "$PROJECT_NAME" down
   if docker volume ls --format '{{.Name}}' | grep -qx "$VOLUME_NAME"; then docker volume rm "$VOLUME_NAME"; fi
   docker compose --project-name "$PROJECT_NAME" up --build --no-start
   docker run --rm \
     --mount "type=volume,source=$VOLUME_NAME,target=/restore" \
     --mount "type=bind,source=$BACKUP_ROOT,target=/backup,readonly" \
     --env "BACKUP_FILE=$BACKUP_FILE" \
     alpine:3.22 sh -c 'tar -xzf "/backup/$BACKUP_FILE" -C /restore'
   docker compose --project-name "$PROJECT_NAME" up --detach --wait --wait-timeout 180
   curl -s "http://localhost:$PORT/api/health"
   open "http://localhost:$PORT"
   ```
6. In the application, verify the brand, item-master count, learned matches, a known reviewed invoice, and export history before resuming work. Record who restored it, the source backup hash, time, application release, and verification result.

On an existing installation, stop if the expected volume is absent before restore; that usually means the wrong brand or project name was entered. A genuinely new replacement Mac has no old volume, so the commands create the correctly named empty volume before unpacking the verified archive.

## 9. Update to a newer GitHub release

Do not overwrite the old source folder; keeping the old approved release makes diagnosis and rollback easier.

1. Finish or pause the current batch and record its status.
2. Make and validate a brand backup (section 7).
3. Download the approved tagged release ZIP, verify the tag/checksum supplied by the application owner, and extract it to a new versioned folder.
4. Open Terminal in the new folder and run the start script with the **same** project name and port used for that brand, which rebuilds the image against the existing brand volume:
   ```bash
   chmod +x start.sh Start-InvoiceStudio.command
   ./start.sh --project-name "$PROJECT_NAME" --port "$PORT"
   ```
5. Run the agreed smoke check with approved fictional or designated validation data: reopen Brand setup, confirm **Include UPC in target workbook** is off unless downstream UPC acceptance has been verified, confirm the catalog and learned-match counts, open a known invoice, and create the exact three-sheet export.
6. Record the release/tag, brand, backup hash, operator, date, and smoke-check result.

If rollback is necessary, stop the new release, open the prior source folder, and restore the pre-update backup before starting the prior release. Starting old code against data already migrated by a new release is not a safe rollback.

## 10. Keep real business data out of GitHub

GitHub is for reviewed application source and fictional test fixtures. Real supplier and finance data belongs in the local brand volume or an approved secure records system. Never commit, upload, or attach supplier invoices or scans, RMS extracts or databases, supplier aliases, generated workbooks or exception reports, Docker volume archives, logs with invoice details, screenshots of real records, credentials, bank details, tax identifiers, commercial prices, or anything under the private `data/reference` path.

Practical controls:

1. Upload real documents through the running application, not by copying them into the source folder.
2. Keep backups under `~/InvoiceStudioBackups`, outside the source folder.
3. Keep browser downloads in an approved private output folder outside the source folder.
4. Do not initialize Git or use GitHub Desktop in a folder that has ever held real business inputs or outputs.
5. If real data is accidentally placed in GitHub, treat it as a data incident and notify InfoSec and the data owner immediately; removing the file is not enough because history, forks and caches retain it.

## 11. Troubleshooting

### `docker: command not found`

Docker Desktop is not installed, or Terminal was opened before it finished starting. Start Docker Desktop, wait for the whale icon to settle, then open a **new** Terminal window.

### "Docker is not ready" or "Cannot connect to the Docker daemon"

Open Docker Desktop and wait until it says it is running, then retry `docker version`. If it never starts, choose **Troubleshoot > Restart** from the whale menu, or reboot the Mac.

### "Port 8000 is already in use"

Another program owns the port. Find it with `lsof -nP -iTCP:8000 -sTCP:LISTEN`, stop it, or start this brand on another port: `./start.sh --port 8010`. Do not expose the service on a non-loopback address.

### `Start-InvoiceStudio.command` will not open, or "permission denied"

For the "unidentified developer" warning, right-click the file and choose **Open**. For "permission denied", open Terminal in the folder and run `chmod +x start.sh Start-InvoiceStudio.command`, then double-click again or run `./start.sh`.

### The browser cannot open the application

```bash
docker compose --project-name "$PROJECT_NAME" ps --all
docker compose --project-name "$PROJECT_NAME" logs --tail 200 invoice-review
curl -s "http://localhost:$PORT/api/health"
```

Capture the command output and release/brand details for support. Do not attach real documents or full private logs to a public issue.

### The build cannot download packages or images

The first build needs internet and may require the organization's proxy configured in Docker Desktop **Settings > Resources > Proxies**. Confirm VPN/proxy policy with IT, check free disk space, and retry. Do not disable endpoint protection or use an unofficial mirror.

### Slow processing of scanned invoices

OCR is CPU-bound. Docker Desktop for Mac limits CPUs and memory in **Settings > Resources**; give it at least 4 CPUs and 6 GB for the default `INVOICE_WORKERS=4`, more for higher worker counts. See [VOLUME_RESULTS.md](VOLUME_RESULTS.md) for the recommended worker count per core.

### Data appears missing after moving to a newer ZIP

The usual cause is a different Compose project name. Stop before importing or uploading anything, run `docker compose ls` and `docker volume ls --filter name=invoice-studio`, and restart with the original project name. Do not copy database files between volumes.

### A file is rejected or remains in review, or two brands were mixed

Same rules as Windows, including the supported scan resolution: see the [Windows guide](WINDOWS_SETUP.md#12-troubleshooting) and the exception procedure in [OPERATOR_TRAINING.md](OPERATOR_TRAINING.md). If two brands were mixed, stop work immediately, do not approve or export, and notify the pilot owner.

## 12. What was verified for Apple Silicon and Intel Macs

All checks were run on 25 September 2026 on a Linux x86_64 build host; no physical Mac was used. Intel Macs use the same `linux/amd64` image that is exercised by every Linux verification in this repository.

For Apple Silicon (`linux/arm64`):

- **Base images.** `docker buildx imagetools inspect` confirmed that both `node:22-alpine` and `python:3.12-slim` publish `linux/arm64/v8` manifests, so Docker Desktop on Apple Silicon pulls native images with no `--platform` override and no Rosetta.
- **Python dependencies.** Every compiled package pinned in `requirements.lock.txt` (Pillow, pydantic-core, pypdfium2, RapidFuzz, lxml, uvloop, httptools, watchfiles, websockets, PyYAML) has a prebuilt `aarch64` manylinux wheel on PyPI for CPython 3.12, verified with `pip download --platform manylinux_2_28_aarch64 --only-binary=:all:`. No package needs a compiler inside the image.
- **Full image build under emulation.** The complete `Dockerfile` was built with `docker buildx build --platform linux/arm64` using QEMU user-mode emulation, and the resulting arm64 container was started and answered `/api/health`. The result of that build is recorded in the pull request that added this guide. Emulation proves the image assembles and starts on arm64; it does not measure Apple Silicon performance.

Not verified: Docker Desktop installation UX on a real Mac, Finder's Gatekeeper prompt wording for the `.command` file, and real-world OCR throughput on Apple Silicon. Treat the first Mac installation as a pilot and report the outcome to the application owner.

## 13. Local pilot boundaries

The boundaries in the [Windows guide, section 13](WINDOWS_SETUP.md#13-local-pilot-boundaries) apply unchanged on macOS: one brand per project and volume, one access-controlled computer and one operator at a time, no application authentication or remote access, no live RMS/REIM/SIOCS integration, human review of every extracted field, and no universal accuracy or throughput claim.

Use [OPERATOR_TRAINING.md](OPERATOR_TRAINING.md) for brand setup, invoice review, learned mappings, and the exact three-sheet Excel handoff.
