<#
.SYNOPSIS
    Smoke test do backend — valida o fluxo 3D ponta a ponta via HTTP.

.DESCRIPTION
    Assume o backend rodando em http://localhost:8000 (customizavel via -BaseUrl).
    1. Ping em /health
    2. POST /captures com 2 imagens sinteticas
    3. Poll de /captures/{id}/status ate completed ou timeout
    4. Download do .glb e validacao do magic header "glTF"

.PARAMETER BaseUrl
    Base URL do backend. Default: http://localhost:8000

.PARAMETER TimeoutSeconds
    Tempo maximo de espera no polling. Default: 30s

.EXAMPLE
    .\scripts\smoke.ps1
    .\scripts\smoke.ps1 -BaseUrl http://192.168.0.3:8000 -TimeoutSeconds 60
#>
param(
    [string]$BaseUrl = "http://localhost:8000",
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "    OK: $Message" -ForegroundColor Green
}

function Write-Fail {
    param([string]$Message)
    Write-Host "    FAIL: $Message" -ForegroundColor Red
    exit 1
}

# ----------------------------------------------------------------- 1) health
Write-Step "GET $BaseUrl/health"
try {
    $health = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 5
    if ($health.status -ne "ok") { Write-Fail "status != ok: $($health | ConvertTo-Json -Compress)" }
    Write-Ok "health respondeu ok"
} catch {
    Write-Fail "backend nao respondeu em $BaseUrl. Subiu o uvicorn? ($($_.Exception.Message))"
}

# --------------------------------- 2) criar 2 imagens tmp e fazer POST /captures
Write-Step "POST $BaseUrl/captures (2 imagens sinteticas)"
$tmp = [System.IO.Path]::GetTempPath()
$img1 = Join-Path $tmp "smoke_1.jpg"
$img2 = Join-Path $tmp "smoke_2.jpg"
# O backend nao valida conteudo das imagens — bytes aleatorios bastam.
[System.IO.File]::WriteAllBytes($img1, [byte[]](1..128 | ForEach-Object { Get-Random -Max 255 }))
[System.IO.File]::WriteAllBytes($img2, [byte[]](1..128 | ForEach-Object { Get-Random -Max 255 }))

# curl.exe (nativo do Windows 10+) lida com multipart melhor que Invoke-RestMethod.
$createJson = & curl.exe -s -X POST "$BaseUrl/captures" `
    -F "images=@$img1" `
    -F "images=@$img2"
if ($LASTEXITCODE -ne 0) { Write-Fail "curl retornou exit code $LASTEXITCODE" }

$create = $createJson | ConvertFrom-Json
if (-not $create.jobId) { Write-Fail "resposta sem jobId: $createJson" }
$jobId = $create.jobId
Write-Ok "jobId = $jobId"

# ---------------------------------------- 3) polling ate completed ou timeout
Write-Step "GET $BaseUrl/captures/$jobId/status (poll ate completed)"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$lastStatus = ""
do {
    Start-Sleep -Seconds 1
    $statusResp = Invoke-RestMethod -Uri "$BaseUrl/captures/$jobId/status" -TimeoutSec 5
    if ($statusResp.status -ne $lastStatus) {
        Write-Host "    status = $($statusResp.status)" -ForegroundColor DarkGray
        $lastStatus = $statusResp.status
    }
    if ($statusResp.status -eq "completed") { break }
    if ($statusResp.status -eq "error") {
        Write-Fail "job falhou: $($statusResp.error)"
    }
} while ((Get-Date) -lt $deadline)

if ($statusResp.status -ne "completed") {
    Write-Fail "timeout de ${TimeoutSeconds}s aguardando completed (ultimo status: $($statusResp.status))"
}
if (-not $statusResp.modelUrl) { Write-Fail "completed sem modelUrl" }
Write-Ok "status = completed, modelUrl = $($statusResp.modelUrl)"

# ---------------------------------------------------- 4) baixar e validar .glb
Write-Step "GET $($statusResp.modelUrl) (valida magic header glTF)"
$glbPath = Join-Path $tmp "smoke_$jobId.glb"
Invoke-WebRequest -Uri $statusResp.modelUrl -OutFile $glbPath -TimeoutSec 10 | Out-Null

$bytes = [System.IO.File]::ReadAllBytes($glbPath)
if ($bytes.Length -lt 12) { Write-Fail ".glb muito curto (${($bytes.Length)} bytes)" }

$magic = [System.Text.Encoding]::ASCII.GetString($bytes[0..3])
if ($magic -ne "glTF") { Write-Fail "magic header esperado 'glTF', veio '$magic'" }
Write-Ok "glb valido ($($bytes.Length) bytes, magic='glTF')"

# ---------------------------------------------------------------- cleanup tmp
Remove-Item $img1, $img2, $glbPath -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "smoke test: OK" -ForegroundColor Green
Write-Host ""
