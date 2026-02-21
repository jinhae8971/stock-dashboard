# Market Dashboard - GitHub Setup Script
# Run: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass; .\setup_github.ps1

$GH_USER = "jinhae8971"
$GH_REPO = "stock-dashboard"
$TOKEN   = $env:GH_TOKEN

if (-not $TOKEN) {
    $TOKEN = Read-Host "GitHub Token"
}

$REMOTE_URL = "https://$TOKEN@github.com/$GH_USER/$GH_REPO.git"
$API_HDR    = @{
    "Authorization" = "token $TOKEN"
    "Accept"        = "application/vnd.github+json"
    "User-Agent"    = "MarketDashboardDeploy"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "[1] Git init..." -ForegroundColor White
git config --global --add safe.directory ($ScriptDir -replace '\\', '/') 2>$null
if (-not (Test-Path ".git")) { git init | Out-Null }
$prev = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
git remote remove origin 2>$null | Out-Null
$ErrorActionPreference = $prev
git remote add origin $REMOTE_URL
git config user.name $GH_USER
git config user.email "jinhae8971@gmail.com"
Write-Host "    OK" -ForegroundColor Green

Write-Host "[2] Create/check repo..." -ForegroundColor White
try {
    Invoke-RestMethod -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO" -Headers $API_HDR | Out-Null
    Write-Host "    Repo exists" -ForegroundColor Green
} catch {
    try {
        $body = @{name=$GH_REPO; private=$false; auto_init=$false; description="Personal Stock Market Dashboard"} | ConvertTo-Json
        Invoke-RestMethod -Method Post -Uri "https://api.github.com/user/repos" -Headers $API_HDR -Body $body -ContentType "application/json" | Out-Null
        Write-Host "    Repo created (Public)" -ForegroundColor Green
        Start-Sleep -Seconds 2
    } catch {
        Write-Host "    Create manually: github.com/new (name: $GH_REPO)" -ForegroundColor Red
        Read-Host "Press Enter after creating"
    }
}

Write-Host "[3] Commit & push..." -ForegroundColor White
$ErrorActionPreference = "SilentlyContinue"
git add .; git commit -m "feat: initial deploy" 2>$null
if ($LASTEXITCODE -ne 0) { git commit --allow-empty -m "chore: update" 2>$null }
git branch -M main; git push -u origin main --force 2>$null
$pushCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if ($pushCode -ne 0) {
    Write-Host "PUSH FAILED - check token scope (repo + workflow)" -ForegroundColor Red
    exit 1
}
Write-Host "    Push OK" -ForegroundColor Green

Write-Host "[4] Enable GitHub Pages..." -ForegroundColor White
try {
    $body = @{ source = @{ branch = "main"; path = "/" } } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO/pages" -Headers $API_HDR -Body $body -ContentType "application/json" | Out-Null
    Write-Host "    Pages enabled" -ForegroundColor Green
} catch {
    Write-Host "    Set manually: Settings > Pages > main / root" -ForegroundColor Yellow
}

Write-Host "[5] Set Secrets..." -ForegroundColor White
$ANTHROPIC_KEY = Read-Host "Anthropic API Key (Enter to skip)"
if (Get-Command gh -ErrorAction SilentlyContinue) {
    $env:GH_TOKEN = $TOKEN
    if ($ANTHROPIC_KEY) { gh secret set ANTHROPIC_API_KEY --body $ANTHROPIC_KEY --repo "$GH_USER/$GH_REPO" 2>$null }
    Write-Host "    Secrets set via gh CLI" -ForegroundColor Green
} else {
    Write-Host "    Set manually: github.com/$GH_USER/$GH_REPO/settings/secrets/actions" -ForegroundColor Yellow
    if ($ANTHROPIC_KEY) { Write-Host "    ANTHROPIC_API_KEY = $($ANTHROPIC_KEY.Substring(0,8))..." -ForegroundColor Cyan }
}

Write-Host "[6] Trigger Actions..." -ForegroundColor White
try {
    Invoke-RestMethod -Method Post `
        -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO/actions/workflows/update-data.yml/dispatches" `
        -Headers $API_HDR -Body '{"ref":"main"}' -ContentType "application/json" | Out-Null
    Write-Host "    Triggered! Check in ~3 min" -ForegroundColor Green
} catch {
    Write-Host "    Manual: github.com/$GH_USER/$GH_REPO/actions" -ForegroundColor White
}

Write-Host ""
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  Dashboard : https://$GH_USER.github.io/$GH_REPO" -ForegroundColor Yellow
Write-Host "  Actions   : github.com/$GH_USER/$GH_REPO/actions" -ForegroundColor Gray
Write-Host "===================================================" -ForegroundColor Cyan
