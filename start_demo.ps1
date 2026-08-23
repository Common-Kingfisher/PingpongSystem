# 乒乓球赛事编排 Demo 一键启动脚本（Windows PowerShell）
# 用法：在项目根目录执行  .\start_demo.ps1   或双击 start_demo.bat

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$backendPort = 8000
$frontendPort = 5173

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "[错误] $msg" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------- 后端准备
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) { Fail "未检测到 Python，请先安装 Python 3.10+" }

$venvPy = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "[信息] 未找到虚拟环境，正在创建 backend\.venv ..."
    & python -m venv (Join-Path $backend ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "创建虚拟环境失败" }
}

Write-Host "[信息] 检查后端依赖 ..."
& $venvPy -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[信息] 安装后端依赖 (pip install -r requirements.txt) ..."
    & $venvPy -m pip install --disable-pip-version-check -r (Join-Path $backend "requirements.txt")
    if ($LASTEXITCODE -ne 0) { Fail "后端依赖安装失败" }
}

# ---------------------------------------------------------------- 前端准备
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) { Fail "未检测到 Node.js，请先安装 Node 18+" }

$pm = "npm"
if (Test-Path (Join-Path $frontend "pnpm-lock.yaml")) { $pm = "pnpm" }
elseif (Test-Path (Join-Path $frontend "yarn.lock")) { $pm = "yarn" }
elseif (Test-Path (Join-Path $frontend "package-lock.json")) { $pm = "npm" }

if (-not (Get-Command $pm -ErrorAction SilentlyContinue)) {
    Fail "检测到包管理器为 $pm，但未找到 $pm 命令，请先安装 $pm"
}

if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "[信息] 安装前端依赖 ($pm install) ..."
    Push-Location $frontend
    & $pm install
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "前端依赖安装失败" }
    Pop-Location
}

# ---------------------------------------------------------------- 端口检查
function Test-PortInUse([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return [bool]$conn
}
if (Test-PortInUse $backendPort) { Fail "端口 $backendPort 已被占用（后端），请先关闭占用进程" }
if (Test-PortInUse $frontendPort) { Fail "端口 $frontendPort 已被占用（前端），请先关闭占用进程" }

# ---------------------------------------------------------------- 启动后端
Write-Host "[信息] 启动后端 (http://localhost:$backendPort) ..."
$backendCmd = "Set-Location '$backend'; & '$venvPy' -m uvicorn app.main:app --port $backendPort"
Start-Process -FilePath "powershell" -ArgumentList @("-NoExit", "-NoProfile", "-Command", $backendCmd)

$backendUp = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$backendPort/api/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $backendUp = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $backendUp) { Fail "后端启动失败（$backendPort/api/health 未就绪，请查看后端窗口日志）" }
Write-Host "[信息] 后端已就绪 (health OK)"

# ---------------------------------------------------------------- 启动前端
Write-Host "[信息] 启动前端 (http://localhost:$frontendPort) ..."
$frontendCmd = "Set-Location '$frontend'; & $pm dev"
Start-Process -FilePath "powershell" -ArgumentList @("-NoExit", "-NoProfile", "-Command", $frontendCmd)

$frontendUp = $false
for ($i = 0; $i -lt 40; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$frontendPort" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $frontendUp = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $frontendUp) { Fail "前端启动失败（$frontendPort 未就绪，请查看前端窗口日志）" }

# ---------------------------------------------------------------- 成功
Write-Host ""
Write-Host "===================================="
Write-Host " 乒乓球赛事编排 Demo 启动成功"
Write-Host " Backend:  http://localhost:$backendPort"
Write-Host " Frontend: http://localhost:$frontendPort"
Write-Host "===================================="
Start-Process "http://localhost:$frontendPort"
exit 0
