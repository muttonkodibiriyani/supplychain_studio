# Invoice Studio on a fresh Windows computer

Validation limit: these Windows instructions were authored and reviewed, but were not executed end to end on a clean Windows computer. Application and container checks ran on Linux. Treat the first Windows installation as a pilot and verify each checkpoint before importing real data.

This guide installs and runs Invoice Studio with Docker Desktop. It is written for an operator who has a new Windows computer and has not installed Python, Node.js, Tesseract, Git, or any developer tools.

The Docker route does **not** require Python, Node.js, Tesseract, Git, or Microsoft Excel to be installed on Windows. Docker builds those application components inside a Linux container. Excel, or another approved XLSX viewer, is only needed to inspect the finished workbook.

The application is a local pilot. It listens only on `localhost`, and it has no application login or user roles. Use it on one access-controlled computer with one authorized operator at a time. Do not publish its port to the office network or internet.

## 1. Check the Windows computer

These requirements were checked against the official Microsoft and Docker pages on 25 September 2026:

- Use a fully updated, serviced Windows 11 release. For a new computer in September 2026, Windows 11 25H2 (build 26200) or later is the sensible baseline. Docker's nominal WSL 2 floor is Windows 11 23H2/build 22631, but Docker also requires a Windows release that is still inside Microsoft's servicing period. Normal Windows 10 support ended on 14 October 2025, and Windows 11 Home/Pro 23H2 is also out of service. Windows Server is not supported by Docker Desktop.
- A 64-bit processor with Second Level Address Translation (SLAT), at least 8 GB RAM, and hardware virtualization enabled in BIOS/UEFI.
- WSL version 2.1.5 or later. Use the latest WSL available through Windows Update or the Microsoft Store.
- The Windows Server service (`LanmanServer`) enabled with startup type Automatic, as required by Docker Desktop.
- Permission to enable WSL the first time. This one-time Windows change requires an administrator.
- Enough free disk space for Docker Desktop, the application image, the private invoice originals, OCR working data, exports, and backups. Capacity depends on invoice volume; do not begin a real batch on a nearly full drive.
- Internet access for the first image build and later updates. Once the image is built, invoice OCR and matching run locally and do not need a paid AI API.

Open **Settings > System > About** to check the Windows edition, version, installed RAM, and system type. Run `winver` to see the release and build. Open **Task Manager > Performance > CPU** and confirm that **Virtualization** says **Enabled**. If it says Disabled, ask your IT team or computer manufacturer to enable virtualization in BIOS/UEFI.

Docker's current page omits Home from its WSL requirement list while separately stating that Home can run Linux containers and documenting WSL 2 on Home. This application needs only Linux containers, but an organization that requires formally listed support should resolve that documentation inconsistency with Docker before choosing Windows Home. Download the x86-64 installer unless **Settings > System > About** explicitly says the computer has an Arm-based processor; Docker Desktop for Windows Arm is currently Early Access.

Official references:

- [Install Docker Desktop on Windows and current system requirements](https://docs.docker.com/desktop/setup/install/windows-install/)
- [Microsoft: install WSL](https://learn.microsoft.com/windows/wsl/install)
- [Microsoft: basic WSL commands](https://learn.microsoft.com/windows/wsl/basic-commands)
- [Microsoft: Windows 11 release and servicing status](https://learn.microsoft.com/windows/release-health/windows11-release-information)
- [Microsoft: Windows 10 end of support](https://learn.microsoft.com/lifecycle/announcements/windows-10-end-of-support)
- [Docker: WSL 2 best practices](https://docs.docker.com/desktop/features/wsl/best-practices/)
- [Docker Desktop Windows permission requirements](https://docs.docker.com/desktop/setup/install/windows-permission-requirements/)
- [Docker Desktop licensing](https://docs.docker.com/subscription-billing/desktop-license/)

Docker Desktop has subscription terms. Docker's current page says commercial use in an enterprise with more than 250 employees **or** more than US$10 million in annual revenue requires a paid subscription; government use also requires a paid subscription. Have your organization confirm licensing before the pilot.

## 2. Install or update WSL 2

1. Select **Start**, type `PowerShell`, right-click **Windows PowerShell**, and select **Run as administrator**.
2. Run:

   ```powershell
   wsl --install --no-distribution
   ```

3. Restart Windows when prompted. `--no-distribution` installs the WSL platform without an Ubuntu user distribution; Docker Desktop does not require one.
4. After restart, open a normal, non-administrator PowerShell window and run:

   ```powershell
   wsl --update
   wsl --version
   wsl --status
   wsl --set-default-version 2
   ```

Confirm that `wsl --version` reports 2.1.5 or later. An Ubuntu distribution is optional. If an operator also needs one, install and verify it separately:

```powershell
wsl --list --online
wsl --install -d Ubuntu
wsl --list --verbose
```

If a Store download remains at 0%, Microsoft documents this alternative:

```powershell
wsl --update --web-download
```

An organization that blocks Microsoft Store or WSL changes must have IT complete this section. Do not download WSL from an unofficial site.

## 3. Install Docker Desktop

1. Download Docker Desktop only from the [official Docker Windows installer page](https://docs.docker.com/desktop/setup/install/windows-install/).
2. Run `Docker Desktop Installer.exe`.
3. Choose the recommended **per-user** installation unless IT requires an all-users installation.
4. Keep the **WSL 2** backend selected. This application uses Linux containers.
5. Start **Docker Desktop** from the Start menu. Read and accept the Docker terms if your organization has approved them.
6. Wait until Docker Desktop reports that the engine is running.

The equivalent per-user PowerShell install, run from the folder containing the official installer, is:

```powershell
Start-Process ".\Docker Desktop Installer.exe" -Wait `
  -ArgumentList "install", "--user", "--backend=wsl-2"
```

Open a new normal PowerShell window and verify the installation:

```powershell
docker desktop status
docker version
docker compose version
docker run --rm hello-world
```

All four commands must complete successfully. `docker version` must show both Client and Server sections. If the Docker Desktop menu offers **Switch to Linux containers**, select it; that wording means Docker is currently in Windows-container mode.

Do not separately install Docker Engine or the Docker CLI inside an Ubuntu or other WSL distribution; Docker warns that the second installation can conflict with Docker Desktop. A corporate VM/VDI also needs nested virtualization or another IT-approved Docker execution option.

## 4. Download the application from GitHub

Open the private repository [muttonkodibiriyani/supplychain_studio](https://github.com/muttonkodibiriyani/supplychain_studio), or the release link supplied by the application owner. Confirm that the owner, repository, release tag, and checksum are the ones approved by your organization. Do not use a fork, mirror, email attachment, or link from a search result.

1. Sign in to the organization-approved GitHub account. A private repository appears only when that account has been granted read access. On the approved repository, select **Code > Download ZIP**. GitHub documents this process in [Downloading source code archives](https://docs.github.com/repositories/working-with-files/using-files/downloading-source-code-archives).
2. In File Explorer, right-click the ZIP and select **Extract All**.
3. Move the extracted folder to a stable, private location under your Windows account, for example `C:\Users\your-name\InvoiceStudio\app-1.0.0`.
4. Open that folder and confirm that `compose.yaml` and `Dockerfile` are present.
5. In File Explorer, open the folder containing `compose.yaml`, right-click an empty area, and select **Open in Terminal**. The PowerShell prompt should now be inside the extracted application folder.

The application source folder must contain code and fictional examples only. Never copy real invoices, RMS extracts, supplier records, generated workbooks, Docker-volume backups, credentials, or the private `data\reference` material into this folder. See [Keep real business data out of GitHub](#10-keep-real-business-data-out-of-github).

## 5. Assign one isolated instance to each brand

Every brand must have its own:

- lowercase brand slug;
- Compose project name;
- localhost port;
- Docker data volume;
- RMS item master and reviewed mappings;
- backups and operator record.

Do not put several brands into one instance. The example below starts the Ulta UAE instance on port 8000. Change the slug and port for another brand. Use only lowercase letters, numbers, and hyphens in the slug.

Run this block at the start of every PowerShell session:

```powershell
$BrandSlug = "ulta-ae"
$Port = "8000"
$ProjectName = "invoice-studio-$BrandSlug"
$env:INVOICE_HOST_PORT = $Port
```

For a second brand, use a different slug and unused port, such as `brand-b` and `8001`. Keep a controlled brand-instance register outside the GitHub source folder. A useful register contains brand name, slug, port, project name, item-master date, last backup date, and operator owner.

`INVOICE_HOST_PORT` changes only the Windows-side localhost port. The service still listens on port 8000 inside its container. The fixed project name makes Docker reuse the same brand volume when a newer GitHub ZIP is extracted into a differently named folder.

Validate the configuration before starting it:

```powershell
docker compose --project-name $ProjectName config
```

Under `ports`, confirm that the published address is `127.0.0.1` and the chosen host port. Stop if it shows `0.0.0.0` or a non-loopback network address.

## 6. Build and start the application

From the folder containing `compose.yaml`, after setting the brand variables above, run:

```powershell
docker compose --project-name $ProjectName up --build --detach --wait --wait-timeout 180
docker compose --project-name $ProjectName ps
Invoke-RestMethod "http://localhost:$Port/api/health" | ConvertTo-Json
Start-Process "http://localhost:$Port"
```

The first build can take several minutes because Docker downloads the base images, application packages, and English Tesseract OCR data. `docker compose ps` should show `invoice-review` as running and healthy. The health request should return JSON with a status of `ok`.

The real application URL is:

```text
http://localhost:<brand-port>
```

Do not add `?preview=1`; that opens fictional preview data rather than the durable brand workspace.

The source package also includes an optional checked-in helper. It performs the same Docker readiness, Linux-container, project-name, port, build, start, status, and browser-opening steps:

```powershell
.\Start-InvoiceStudio.ps1 -ProjectName $ProjectName -Port $Port
```

The direct Compose commands above remain the canonical procedure and are the commands used throughout this guide. If corporate PowerShell policy blocks the helper, use the direct commands; do not weaken the execution policy. The helper builds by default. `-NoBuild` is suitable only for a previously built, unchanged release, and `-NoBrowser` suppresses browser opening.

Docker creates a separate named volume for this project. With the example settings it is normally `invoice-studio-ulta-ae_invoice-data`. The volume contains the SQLite database, accepted source documents, learned mappings, and generated exports. Deleting the extracted source folder does not delete that volume, but deleting the Docker volume does.

## 7. Daily start, status, logs, restart, and stop

Start Docker Desktop first. Open PowerShell in the application folder and set `$BrandSlug`, `$Port`, `$ProjectName`, and `$env:INVOICE_HOST_PORT` as shown in section 5.

On Docker Desktop versions that include the Desktop CLI, these commands start it and show its state:

```powershell
docker desktop start
docker desktop status
```

Start or recreate the brand service while keeping its existing volume:

```powershell
docker compose --project-name $ProjectName up --detach --wait --wait-timeout 180
Start-Process "http://localhost:$Port"
```

Check its state and health:

```powershell
docker compose --project-name $ProjectName ps
Invoke-RestMethod "http://localhost:$Port/api/health" | ConvertTo-Json
```

Show the most recent log entries:

```powershell
docker compose --project-name $ProjectName logs --tail 200 invoice-review
```

A health status of `degraded` means the extraction worker pool needs attention: the `problems` list says whether workers are dead (they are respawned on the next health check) or whether the queue has stalled. The log shows `extraction worker error` lines with the cause.

Follow new log entries until you press Ctrl+C:

```powershell
docker compose --project-name $ProjectName logs --follow invoice-review
```

Ctrl+C stops only the log display when the service was started with `--detach`.

Restart the application process without deleting data:

```powershell
docker compose --project-name $ProjectName restart invoice-review
```

Stop it at the end of the day while retaining the container and data:

```powershell
docker compose --project-name $ProjectName stop
```

Start that stopped container again:

```powershell
docker compose --project-name $ProjectName start
```

You may instead remove the container and its temporary network while preserving the named volume:

```powershell
docker compose --project-name $ProjectName down
```

The next `up` recreates them. **Never add `--volumes` or `-v` to `docker compose down`.** Those options delete the brand's named data volume. Do not run `docker volume prune` on an operating computer. Docker documents that ordinary [`docker compose down`](https://docs.docker.com/reference/cli/docker/compose/down/) preserves named volumes unless the volume option is supplied.

## 8. Back up a brand

Back up before every application update, before Docker Desktop repair or removal, after an important reviewed batch, and on the operating schedule approved by Finance/IT. Stop the brand service first so SQLite and stored files form one consistent snapshot.

The following commands save the brand's named volume outside the GitHub source folder. Set the normal brand variables first, then run:

```powershell
$BackupRoot = Join-Path $HOME "InvoiceStudioBackups\$BrandSlug"
New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
$BackupFile = "invoice-data-$BrandSlug-$(Get-Date -Format 'yyyyMMdd-HHmmss').tar.gz"
$BackupPath = Join-Path $BackupRoot $BackupFile
$VolumeName = "${ProjectName}_invoice-data"

docker compose --project-name $ProjectName stop invoice-review
docker volume inspect $VolumeName | Out-Null
docker run --rm `
  --mount "type=volume,source=$VolumeName,target=/source,readonly" `
  --mount "type=bind,source=$BackupRoot,target=/backup" `
  --env "BACKUP_FILE=$BackupFile" `
  alpine:3.22 sh -c 'tar -czf "/backup/$BACKUP_FILE" -C /source .'

if ($LASTEXITCODE -ne 0) { throw "Backup failed; keep the application stopped and contact support." }
docker run --rm `
  --mount "type=bind,source=$BackupRoot,target=/backup,readonly" `
  --env "BACKUP_FILE=$BackupFile" `
  alpine:3.22 sh -c 'tar -tzf "/backup/$BACKUP_FILE" >/dev/null'
if ($LASTEXITCODE -ne 0) { throw "Backup archive validation failed." }

$Hash = (Get-FileHash $BackupPath -Algorithm SHA256).Hash
$Hash | Set-Content "$BackupPath.sha256.txt"
Get-Item $BackupPath, "$BackupPath.sha256.txt" | Select-Object FullName, Length, LastWriteTime
docker compose --project-name $ProjectName start invoice-review
```

The first backup may download the small official Alpine image used only to run `tar`. Confirm that both the `.tar.gz` file and its `.sha256.txt` file exist and are not zero bytes. Store them in an access-controlled, encrypted location approved for supplier and finance data. A backup contains confidential invoice originals and master/mapping data; do not email it, attach it to a ticket, or place it in GitHub.

Docker's supported volume-backup pattern is documented under [Back up, restore, or migrate data volumes](https://docs.docker.com/engine/storage/volumes/#back-up-restore-or-migrate-data-volumes).

## 9. Restore a brand from a backup

Restore replaces the entire selected brand volume. Check the brand slug, project name, backup filename, and application version twice. Keep the current volume until you have a separate verified backup of it.

1. Put the approved `.tar.gz` and `.sha256.txt` files in `$HOME\InvoiceStudioBackups\<brand-slug>`.
2. Open PowerShell in the application source folder for the version you intend to run.
3. Set the brand variables from section 5.
4. Set the exact backup filename, without changing it:

   ```powershell
   $BackupRoot = Join-Path $HOME "InvoiceStudioBackups\$BrandSlug"
   $BackupFile = "invoice-data-ulta-ae-20260925-170000.tar.gz"
   $BackupPath = Join-Path $BackupRoot $BackupFile
   $VolumeName = "${ProjectName}_invoice-data"
   ```

5. Validate the file and recorded hash before changing Docker data:

   ```powershell
   if (-not (Test-Path $BackupPath)) { throw "Backup file not found: $BackupPath" }
   if (-not (Test-Path "$BackupPath.sha256.txt")) { throw "SHA256 file not found." }
   $ExpectedHash = (Get-Content "$BackupPath.sha256.txt").Trim()
   $ActualHash = (Get-FileHash $BackupPath -Algorithm SHA256).Hash
   if ($ActualHash -ne $ExpectedHash) { throw "Backup hash mismatch. Do not restore." }
   docker run --rm `
     --mount "type=bind,source=$BackupRoot,target=/backup,readonly" `
     --env "BACKUP_FILE=$BackupFile" `
     alpine:3.22 sh -c 'tar -tzf "/backup/$BACKUP_FILE" >/dev/null'
   if ($LASTEXITCODE -ne 0) { throw "Backup archive validation failed. Do not restore." }
   ```

6. Replace only the selected brand volume and restore the archive:

   ```powershell
   docker compose --project-name $ProjectName down
   $ExistingVolume = docker volume ls --format "{{.Name}}" | Where-Object { $_ -eq $VolumeName }
   if ($ExistingVolume) {
     docker volume rm $VolumeName
     if ($LASTEXITCODE -ne 0) { throw "The old volume was not removed; stop and investigate." }
   }

   docker compose --project-name $ProjectName up --build --no-start
   docker run --rm `
     --mount "type=volume,source=$VolumeName,target=/restore" `
     --mount "type=bind,source=$BackupRoot,target=/backup,readonly" `
     --env "BACKUP_FILE=$BackupFile" `
     alpine:3.22 sh -c 'tar -xzf "/backup/$BACKUP_FILE" -C /restore'
   if ($LASTEXITCODE -ne 0) { throw "Restore failed; do not start the application." }

   docker compose --project-name $ProjectName up --detach --wait --wait-timeout 180
   Invoke-RestMethod "http://localhost:$Port/api/health" | ConvertTo-Json
   Start-Process "http://localhost:$Port"
   ```

7. In the application, verify the brand, item-master count, learned matches, a known reviewed invoice, and export history before resuming work. Record who restored it, the source backup hash, time, application release, and verification result.

On an existing installation, stop if the expected volume is absent before restore; that usually means the wrong brand/project name was entered. A genuinely new replacement computer has no old volume, so the commands create the correctly labelled empty volume before unpacking the verified archive. Do not guess another volume name.

## 10. Update to a newer GitHub release

Do not overwrite the old source folder. Keeping the old approved release makes diagnosis and controlled rollback easier.

1. Finish or pause the current batch and record its status.
2. Make and validate a brand backup using section 8.
3. Download the approved tagged release ZIP from the authorized GitHub repository.
4. Verify the release tag/checksum supplied by the application owner, extract it to a new versioned folder, and confirm `compose.yaml` and `Dockerfile` are present.
5. Open PowerShell in the new folder and set the **same** `$BrandSlug`, `$ProjectName`, and `$Port` used for that brand.
6. Preview the configuration and confirm the localhost binding:

   ```powershell
   docker compose --project-name $ProjectName config
   ```

7. Build and start the release against the existing brand volume:

   ```powershell
   docker compose --project-name $ProjectName up --build --detach --wait --wait-timeout 180
   docker compose --project-name $ProjectName ps
   Invoke-RestMethod "http://localhost:$Port/api/health" | ConvertTo-Json
   ```

8. Run the agreed smoke check with approved fictional or designated validation data: reopen Brand setup, confirm **Include UPC in target workbook** is off unless downstream UPC acceptance has been verified, confirm the catalog and learned-match counts, open a known invoice, and create the exact three-sheet export. Verify the current conservative application behavior: **Target unit cost** is **Invoice net unit cost after discount**, an RMS difference above the configured AED 10 threshold raises review without substitution, and Header ex-tax total reconciles to Details.
9. Record the release/tag, brand, backup hash, operator, date, and smoke-check result.

[`docker compose up`](https://docs.docker.com/reference/cli/docker/compose/up/) recreates a changed service while preserving mounted named volumes. If a database migration or changed conversion rule makes rollback necessary, stop the new release, open the prior source folder, and restore the pre-update backup before starting the prior release. Merely starting old code against data already migrated by a new release is not a safe rollback.

## 11. Keep real business data out of GitHub

GitHub is for reviewed application source and fictional test fixtures. Real supplier and finance data belongs in the local brand volume or an approved secure records system.

Never commit, upload, or attach any of the following to a GitHub repository or release:

- supplier invoices, credit notes, RTVs, PODs, purchase orders, or scans;
- RMS Excel/CSV extracts, RMS SQLite databases, catalog projections, or supplier aliases;
- generated consolidated workbooks or exception/status reports;
- Docker volume archives, database files, logs containing invoice details, or screenshots of real records;
- credentials, tokens, email addresses, bank details, tax identifiers, or commercial prices;
- anything under the private working path `data\reference`, including `target_conversion_rules.json`, `confirmed_invoice_aliases.json`, the RMS workbook, and the RMS database.

Practical controls:

1. Upload real documents through the running application, not by copying them into the extracted source folder.
2. Keep backups under `$HOME\InvoiceStudioBackups`, which is outside the source folder.
3. Keep browser downloads in an approved private output folder outside the source folder.
4. Do not initialize Git or use GitHub Desktop in a folder that has ever held real business inputs or outputs.
5. Before any source publication, the release maintainer must review the exact archive contents and run the organization's secret and sensitive-data checks. Ignore files are a safety net, not approval to mix private data with source.
6. If real data is accidentally placed in GitHub, treat it as a data incident. Removing the current file is not enough because Git history, forks, caches, and downloaded archives may retain it. Notify InfoSec and the data owner immediately.

Brand initialization artifacts must be transferred through the approved internal secure channel. They must not be bundled into the public or private source repository merely for convenience.

## 12. Troubleshooting

### `docker` is not recognized

Close PowerShell, start Docker Desktop, wait for it to finish starting, and open a new PowerShell window. If the command is still missing, repair or reinstall Docker Desktop from the official installer.

### Docker reports that it cannot connect to the engine

Open Docker Desktop and wait until the engine is running, then retry:

```powershell
docker version
```

If Docker Desktop is running but WSL is stuck, close Docker Desktop, run the following in an administrator PowerShell, restart Windows if requested, and reopen Docker Desktop:

```powershell
wsl --update
wsl --shutdown
```

### WSL version details do not appear or the version is below 2.1.5

Run `wsl --update` in an administrator PowerShell. Docker's current Windows guide says an inbox WSL version that does not return version details must be updated.

### Virtualization is disabled

Confirm **Task Manager > Performance > CPU > Virtualization**. BIOS/UEFI changes vary by computer and may be locked by corporate policy; ask IT rather than changing unrelated firmware settings.

### The selected port is already in use

Check it:

```powershell
Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
```

Stop the conflicting approved application or assign this brand another unused port, set `$env:INVOICE_HOST_PORT` to that port, and run `docker compose ... up` again. Do not expose the service on a non-loopback address.

### The browser cannot open the application

Run:

```powershell
docker compose --project-name $ProjectName ps --all
docker compose --project-name $ProjectName logs --tail 200 invoice-review
Invoke-RestMethod "http://localhost:$Port/api/health"
```

Capture the command output and release/brand details for support. Do not attach real documents or full private logs to a public issue.

### The build cannot download packages or images

The first build needs internet and may require the organization's Docker proxy configuration. Confirm VPN/proxy policy with IT, verify that Docker Desktop has free disk space, and retry. Do not disable endpoint protection or install packages from an unofficial mirror.

### Data appears missing after moving to a newer ZIP

The usual cause is a different Compose project name. Stop before importing or uploading anything, then inspect local projects and volumes:

```powershell
docker compose ls
docker volume ls --filter "name=invoice-studio"
```

Restart with the original `$ProjectName`. Do not copy database files manually between volumes.

### A file is rejected or remains in review

Current Docker defaults for invoice documents include 64 MiB per file, 50 pages/frames, one invoice per file, and explicit supported formats. The item-master importer has a separate 128 MiB catalog limit so an approved original RMS XLSX can be projected without weakening the invoice-document limit. Encrypted, corrupt, empty, legacy XLS/DOC, HEIC, ZIP, HTML, SVG, and limit-exceeding invoice files are rejected. Review capture notes and the original. Do not split, rename, or convert a finance document in a way that loses pages or audit provenance; follow the exception procedure in [OPERATOR_TRAINING.md](OPERATOR_TRAINING.md).

### A scanned image is rejected for its resolution

**Supported scan resolution (until the limits become configurable).** Two fixed pixel limits apply to every page, whether an image input (PNG, JPG, TIFF, BMP, WebP frames) or a PDF page once rendered: a hard limit of 30,000,000 pixels per page, which fails the whole document, and a total budget of 150,000,000 pixels per document across all frames. An A4 page scanned at 600 dpi is about 4,962 x 7,014 pixels (about 34.8 million) and is rejected; A4 at 300, 400 or 500 dpi passes the per-page limit. The total budget allows about 17 A4 pages at 300 dpi or about 6 at 500 dpi in one multi-frame image, whatever the 50-page limit says. Scan at 300 dpi for multi-page documents and never above 500 dpi. PDF pages are rendered at twice the page box; a page box of real A4 size renders at about 2.0 million pixels and passes, but a scanner PDF whose page box is written in pixels (for example 2480 x 3507 pt for a 300 dpi A4 scan) renders at 4 times its pixel count and is rejected by the per-page limit; re-export such PDFs with a true page size or upload the image instead. The per-file size limit and the OCR time budget of 180 seconds per document still apply. Rescan at 300 dpi rather than resampling a finance document; if a rescan is impossible, follow the exception procedure in [OPERATOR_TRAINING.md](OPERATOR_TRAINING.md).

### Two brands were mixed

Stop work immediately. Do not approve, export, or try to repair mappings by hand. Record the two project names, ports, affected filenames, and actions taken; then notify the pilot owner. Restore from the last known clean brand backup if the owner confirms that is required.

## 13. Local pilot boundaries

- One brand per Compose project and named volume; one application process per volume.
- One access-controlled Windows host and one operator at a time.
- No application authentication, roles, verified individual audit identity, shared-server deployment, or remote network access.
- No automatic email/shared-folder intake, live RMS/REIM integration, SIOCS pre-GRN control, GRN confirmation, invoice posting, or payment release.
- OCR and generic layout parsing can be wrong. Every extracted field, item identity, quantity, cost, tax, and total requires human review.
- The raw 179-column RMS import is a supported release contract with a separate 128 MiB ceiling, but it must pass the approved-build release test and operator count/spot checks before real invoice work; documentation alone is not a test result.
- The current conservative application behavior places invoice net unit cost after discount in every `Details.Unit Cost`. RMS cost is comparison evidence only; a difference above the configured AED 10 threshold triggers review without substitution. `Header.Total Cost Ex Tax` must reconcile to `Details.Unit Cost × Quantity` and the reviewed invoice ex-tax total. Commercial signoff on the invoice-net-only policy is still pending, so this behavior must not be described as an unequivocally user-confirmed business rule; operators nevertheless follow the deployed behavior until an approved, tested release changes it.
- A generated workbook is not evidence that a downstream system accepted it. Record acceptance or rejection separately in the controlled operating process.
- No universal accuracy or throughput claim is made. Pilot results must be measured per brand, supplier layout, document quality, and reviewed line.
- Backups, restore tests, retention/deletion rules, endpoint security, and disk monitoring remain operating responsibilities.

Use [OPERATOR_TRAINING.md](OPERATOR_TRAINING.md) for the brand setup, invoice review, learned mapping, and exact three-sheet Excel handoff.
