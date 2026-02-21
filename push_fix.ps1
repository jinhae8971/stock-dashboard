# ═══════════════════════════════════════════════════════
#  Push 실패 수정 스크립트 — 새 토큰으로 재시도
#  실행: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#         .\push_fix.ps1
# ═══════════════════════════════════════════════════════
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding            = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

$GH_USER = "jinhae8971"
$GH_REPO = "stock-dashboard"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  GitHub Token 재발급 안내" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor White
Write-Host ""
Write-Host "  1. 아래 URL을 브라우저에서 열기:" -ForegroundColor Yellow
Write-Host "     https://github.com/settings/tokens/new" -ForegroundColor White
Write-Host ""
Write-Host "  2. 설정값:" -ForegroundColor Yellow
Write-Host "     - Note : market-dashboard" -ForegroundColor White
Write-Host "     - Expiration : 90 days (또는 No expiration)" -ForegroundColor White
Write-Host "     - Scopes : [v] repo (전체 체크)" -ForegroundColor White
Write-Host ""
Write-Host "  3. 'Generate token' 클릭 후 토큰 복사" -ForegroundColor Yellow
Write-Host ""

$NEW_TOKEN = Read-Host "새 GitHub Token 붙여넣기 (ghp_...)"
if ([string]::IsNullOrWhiteSpace($NEW_TOKEN)) {
    Write-Host "토큰이 없습니다. 종료합니다." -ForegroundColor Red
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$REMOTE_URL = "https://$NEW_TOKEN@github.com/$GH_USER/$GH_REPO.git"

Write-Host ""
Write-Host "[1] Remote URL 업데이트..." -ForegroundColor White
$ErrorActionPreference = "SilentlyContinue"
git remote remove origin 2>$null | Out-Null
$ErrorActionPreference = "Continue"
git remote add origin $REMOTE_URL
git config user.name  $GH_USER
git config user.email "jinhae8971@gmail.com"

Write-Host "[2] branch main으로 전환..." -ForegroundColor White
$ErrorActionPreference = "SilentlyContinue"
git branch -M main 2>$null
$ErrorActionPreference = "Continue"

Write-Host "[3] GitHub로 Push..." -ForegroundColor White
$ErrorActionPreference = "SilentlyContinue"
git push -u origin main --force 2>$null
$pushCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if ($pushCode -ne 0) {
    Write-Host ""
    Write-Host "[!] 여전히 실패. 아래를 확인하세요:" -ForegroundColor Red
    Write-Host "    - Token에 'repo' scope 체크됐는지 확인" -ForegroundColor Yellow
    Write-Host "    - https://github.com/$GH_USER/$GH_REPO 레포 존재 여부 확인" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "[4] GitHub Actions 수동 트리거..." -ForegroundColor White
$API_HDR = @{
    "Authorization" = "token $NEW_TOKEN"
    "Accept"        = "application/vnd.github+json"
    "User-Agent"    = "MarketDashboardDeploy"
}

# Secrets 업데이트
Write-Host ""
$ANTHROPIC_KEY = Read-Host "Anthropic API Key 입력 (엔터 = 이전 값 유지)"
if (-not [string]::IsNullOrWhiteSpace($ANTHROPIC_KEY)) {
    try {
        # Public key 조회
        $pubKey = Invoke-RestMethod -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO/actions/secrets/public-key" -Headers $API_HDR
        Write-Host "  Secrets는 수동으로 등록하세요:" -ForegroundColor Yellow
        Write-Host "  https://github.com/$GH_USER/$GH_REPO/settings/secrets/actions" -ForegroundColor White
        Write-Host "  이름: ANTHROPIC_API_KEY" -ForegroundColor Cyan
        Write-Host "  값  : $($ANTHROPIC_KEY.Substring(0, [Math]::Min(20, $ANTHROPIC_KEY.Length)))..." -ForegroundColor Gray
    } catch {}
}

try {
    Invoke-RestMethod -Method Post `
        -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO/actions/workflows/update-data.yml/dispatches" `
        -Headers $API_HDR -Body '{"ref":"main"}' -ContentType "application/json" | Out-Null
    Write-Host "  Actions 트리거 완료!" -ForegroundColor Green
} catch {
    Write-Host "  Actions 수동 실행:" -ForegroundColor Yellow
    Write-Host "  https://github.com/$GH_USER/$GH_REPO/actions" -ForegroundColor White
}

# GitHub Pages 활성화
try {
    $pagesBody = @{ source = @{ branch = "main"; path = "/" } } | ConvertTo-Json
    Invoke-RestMethod -Method Post `
        -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO/pages" `
        -Headers $API_HDR -Body $pagesBody -ContentType "application/json" | Out-Null
    Write-Host "  GitHub Pages 활성화 완료" -ForegroundColor Green
} catch {
    Write-Host "  GitHub Pages 수동 설정:" -ForegroundColor Yellow
    Write-Host "  github.com/$GH_USER/$GH_REPO -> Settings -> Pages -> Branch: main / root" -ForegroundColor White
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  완료!" -ForegroundColor Green
Write-Host ""
Write-Host "  대시보드: https://$GH_USER.github.io/$GH_REPO" -ForegroundColor Yellow
Write-Host "  Actions : https://github.com/$GH_USER/$GH_REPO/actions" -ForegroundColor Gray
Write-Host "  Secrets : https://github.com/$GH_USER/$GH_REPO/settings/secrets/actions" -ForegroundColor Gray
Write-Host "============================================" -ForegroundColor Cyan
