# Market Dashboard - Direct Push Script
# Run: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass; .\direct_push.ps1

$GH_USER = "jinhae8971"
$GH_REPO = "stock-dashboard"
$TOKEN   = $env:GH_TOKEN  # Set via: $env:GH_TOKEN = "ghp_..."

if (-not $TOKEN) {
    $TOKEN = Read-Host "GitHub Token (korean-market-bot)"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$API_HDR = @{
    "Authorization" = "token $TOKEN"
    "Accept"        = "application/vnd.github+json"
    "User-Agent"    = "MarketDashboard"
}

Write-Host "[1] Check token..." -ForegroundColor Cyan
$me = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $API_HDR -ErrorAction SilentlyContinue
if ($me.login) {
    Write-Host "    OK - user: $($me.login)" -ForegroundColor Green
} else {
    Write-Host "    FAIL - invalid token" -ForegroundColor Red; exit 1
}

Write-Host "[2] Check repo..." -ForegroundColor Cyan
$repo = Invoke-RestMethod -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO" -Headers $API_HDR -ErrorAction SilentlyContinue
if ($repo.full_name) {
    Write-Host "    OK - $($repo.full_name)" -ForegroundColor Green
} else {
    Write-Host "    Creating repo..." -ForegroundColor Yellow
    $body = @{ name=$GH_REPO; private=$false; auto_init=$false } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri "https://api.github.com/user/repos" -Headers $API_HDR -Body $body -ContentType "application/json" | Out-Null
    Start-Sleep -Seconds 3
    Write-Host "    Repo created" -ForegroundColor Green
}

Write-Host "[3] Reset git history (clean slate)..." -ForegroundColor Cyan
if (Test-Path ".git") { Remove-Item -Recurse -Force ".git" }
git init | Out-Null
git remote add origin "https://$TOKEN@github.com/$GH_USER/$GH_REPO.git"
git config user.name  $GH_USER
git config user.email "jinhae8971@gmail.com"

Write-Host "[4] Commit & push..." -ForegroundColor Cyan
git add -A
git commit -m "deploy: stock-dashboard $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1 | Out-Null
git branch -M main

$out = git push -u origin main --force 2>&1
Write-Host $out
$code = $LASTEXITCODE

if ($code -ne 0) {
    Write-Host "PUSH FAILED" -ForegroundColor Red; exit 1
}
Write-Host "    Push OK" -ForegroundColor Green

Write-Host "[5] Enable GitHub Pages..." -ForegroundColor Cyan
try {
    $body = @{ source = @{ branch = "main"; path = "/" } } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO/pages" -Headers $API_HDR -Body $body -ContentType "application/json" | Out-Null
    Write-Host "    Pages enabled" -ForegroundColor Green
} catch {
    Write-Host "    Pages already set" -ForegroundColor Yellow
}

Write-Host "[6] Trigger GitHub Actions..." -ForegroundColor Cyan
try {
    Invoke-RestMethod -Method Post `
        -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO/actions/workflows/update-data.yml/dispatches" `
        -Headers $API_HDR -Body '{"ref":"main"}' -ContentType "application/json" | Out-Null
    Write-Host "    Actions triggered - data ready in ~5 min" -ForegroundColor Green
} catch {
    Write-Host "    Trigger manually: github.com/$GH_USER/$GH_REPO/actions" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  Dashboard : https://$GH_USER.github.io/$GH_REPO" -ForegroundColor Yellow
Write-Host "  Secrets   : github.com/$GH_USER/$GH_REPO/settings/secrets/actions" -ForegroundColor Gray
Write-Host "  >> Add ANTHROPIC_API_KEY for trading strategy <<" -ForegroundColor White
Write-Host "===================================================" -ForegroundColor Cyan
