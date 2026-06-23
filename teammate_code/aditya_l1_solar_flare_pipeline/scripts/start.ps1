# Aditya-L1 Flare Operations — one-command demo launcher (Windows / PowerShell)
#
#   powershell -ExecutionPolicy Bypass -File scripts/start.ps1
#
# Ensures pipeline outputs exist, builds the React frontend if needed, then
# serves the full app (API + WebSocket + dashboard) from a single port.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 1. Generate pipeline outputs on first run.
if (-not (Test-Path "outputs/pipeline_summary.txt")) {
    Write-Host "==> No pipeline outputs found. Running synthetic showcase pipeline..." -ForegroundColor Cyan
    python -m pipeline.run_pipeline --source synthetic
}

# 2. Build the frontend if it has not been built yet.
if (-not (Test-Path "frontend/dist/index.html")) {
    # Corporate networks often do TLS inspection, which makes npm fail with
    # UNABLE_TO_VERIFY_LEAF_SIGNATURE. Export the machine's trusted CAs (which
    # include the corporate root) and point Node at them — no security disabled.
    $pem = Join-Path $root "frontend/corp-ca-bundle.pem"
    if (-not (Test-Path $pem)) {
        Write-Host "==> Exporting trusted CA bundle for npm (corporate-proxy safe)..." -ForegroundColor Cyan
        $sb = New-Object System.Text.StringBuilder
        foreach ($s in @("Cert:\LocalMachine\Root","Cert:\LocalMachine\CA","Cert:\CurrentUser\Root","Cert:\CurrentUser\CA")) {
            Get-ChildItem $s -ErrorAction SilentlyContinue | ForEach-Object {
                try {
                    $b = [System.Convert]::ToBase64String($_.RawData, 'InsertLineBreaks')
                    [void]$sb.AppendLine("-----BEGIN CERTIFICATE-----")
                    [void]$sb.AppendLine($b)
                    [void]$sb.AppendLine("-----END CERTIFICATE-----")
                } catch {}
            }
        }
        Set-Content -Path $pem -Value $sb.ToString() -Encoding ascii
    }
    $env:NODE_EXTRA_CA_CERTS = $pem

    Write-Host "==> Building frontend..." -ForegroundColor Cyan
    Set-Location "$root/frontend"
    if (-not (Test-Path "node_modules")) { npm install --no-audit --no-fund }
    npm run build
    Set-Location $root
}

# 3. Serve everything from one port.
Write-Host "==> Starting Aditya-L1 Flare Operations Center at http://127.0.0.1:8000" -ForegroundColor Green
uvicorn backend.app:app --host 127.0.0.1 --port 8000
