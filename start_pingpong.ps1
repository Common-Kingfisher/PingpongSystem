<#
.SYNOPSIS
    PingpongSystem production / 局域网单服务启动脚本（D 轨 Day 2 PoC）。

.DESCRIPTION
    与 start_demo.ps1 的区别：

    * start_demo.ps1      = 开发 / Demo 双服务模式（FastAPI 8000 + Vite 5173）
    * start_pingpong.ps1  = production 单服务模式（只启动 FastAPI 8000，同时托管前端构建产物）

    流程：定位根目录 -> 检查 Python/venv/依赖 -> 确认或构建 frontend/dist
          -> 检查 8000 端口 -> uvicorn --host 0.0.0.0 --port 8000
          -> 等待 /api/health -> 枚举并打印本机与局域网 IPv4 地址。

    本脚本明确**不会**：

    * 申请管理员权限
    * 修改 Windows 防火墙规则
    * 结束或重启其他进程
    * 把服务暴露到公网
    * 修改任何系统网络配置

    若手机无法访问，脚本只输出人工排查提示。

.EXAMPLE
    .\start_pingpong.ps1

.EXAMPLE
    .\start_pingpong.ps1 -SkipBuild      # 要求 dist 必须已存在，跳过自动构建
    .\start_pingpong.ps1 -NoBrowser      # 不自动打开浏览器
#>

[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$SkipBuild,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- 输出 helper

function Write-Step([string]$msg) { Write-Host "[信息] $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "[完成] $msg" -ForegroundColor Green }
function Write-Note([string]$msg) { Write-Host "[注意] $msg" -ForegroundColor Yellow }
function Fail([string]$msg) {
    Write-Host ""
    Write-Host "[错误] $msg" -ForegroundColor Red
    Write-Host ""
    exit 1
}

# ---------------------------------------------------------------- 1. 项目根目录

# 无论从哪个目录调用，都定位到本脚本所在目录（= 项目根）
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$requirements = Join-Path $backend 'requirements.txt'
$distDir = Join-Path $frontend 'dist'
$distIndex = Join-Path $distDir 'index.html'
$venvPy = Join-Path $backend '.venv\Scripts\python.exe'

Write-Host ""
Write-Host "===================================="
Write-Host " PingpongSystem · production 单服务"
Write-Host "===================================="
Write-Step "项目根目录：$root"

if (-not (Test-Path $requirements)) { Fail "未找到 $requirements，脚本可能不在项目根目录。" }

# ---------------------------------------------------------------- 2. 检查 Python

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) { Fail "未检测到 Python，请先安装 Python 3.10+ 并加入 PATH。" }
Write-Ok "已检测到 Python：$($pythonCmd.Source)"

# ---------------------------------------------------------------- 3. 检查 backend venv

if (-not (Test-Path $venvPy)) {
    Write-Step "未找到虚拟环境，正在创建 backend\.venv ..."
    & python -m venv (Join-Path $backend '.venv')
    if ($LASTEXITCODE -ne 0) { Fail "创建虚拟环境失败。" }
}
Write-Ok "后端虚拟环境就绪：$venvPy"

# ---------------------------------------------------------------- 4. 检查/安装后端依赖

Write-Step "检查后端依赖 (fastapi / uvicorn) ..."
& $venvPy -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Step "缺少后端依赖，执行 pip install -r requirements.txt ..."
    & $venvPy -m pip install --disable-pip-version-check -r $requirements
    if ($LASTEXITCODE -ne 0) { Fail "后端依赖安装失败。" }
}
Write-Ok "后端依赖就绪"

# ---------------------------------------------------------------- 5. 确认/构建 frontend/dist

function Get-PackageManager {
    if (Test-Path (Join-Path $frontend 'pnpm-lock.yaml')) { return 'pnpm' }
    if (Test-Path (Join-Path $frontend 'yarn.lock')) { return 'yarn' }
    if (Test-Path (Join-Path $frontend 'package-lock.json')) { return 'npm' }
    return 'npm'
}

$pm = Get-PackageManager

if (-not (Test-Path $distIndex)) {
    Write-Note "未找到前端构建产物：$distIndex"

    if ($SkipBuild) {
        Fail "指定了 -SkipBuild，但 dist 不存在。请先构建：`n      cd `"$frontend`"`n      $pm install`n      $pm build"
    }

    $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
    if (-not $nodeCmd) {
        # 不静默失败：明确报错并给出构建命令
        Fail ("本机未检测到 Node.js，且 frontend\dist 尚未构建。`n`n" +
              "production 单服务需要预构建的前端产物。请任选其一：`n`n" +
              "  1) 在具备 Node.js 18+ 的机器上执行 pnpm build 后，把整个 frontend\dist 目录复制到本机；`n" +
              "  2) 在本机安装 Node.js 18+ 后执行：`n" +
              "         cd `"$frontend`"`n" +
              "         $pm install`n" +
              "         $pm build`n" +
              "     然后重新运行 .\start_pingpong.ps1`n`n" +
              "（开发/Demo 双服务模式不需要 dist，请改用 .\start_demo.ps1）")
    }

    if (-not (Get-Command $pm -ErrorAction SilentlyContinue)) {
        Fail "未找到包管理器命令 $pm（由 lockfile 推断）。请先安装 $pm，或改用预构建的 frontend\dist。"
    }

    Write-Step "使用 $pm 执行 production 构建（首次可能需要几分钟）..."
    Push-Location $frontend
    try {
        if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
            Write-Step "安装前端依赖（$pm install）..."
            & $pm install
            if ($LASTEXITCODE -ne 0) { Fail "前端依赖安装失败。" }
        }
        & $pm build
        if ($LASTEXITCODE -ne 0) { Fail "前端 production 构建失败（$pm build），请查看上方输出。" }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path $distIndex)) { Fail "构建结束仍未找到 $distIndex，请检查 $pm build 输出。" }
Write-Ok "前端构建产物就绪：$distDir"

# ---------------------------------------------------------------- 6. 检查端口

function Test-PortInUse([int]$p) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if ($conn) { return $true }
    } catch {
        # Get-NetTCPConnection 不可用时退化为直接连接探测
    }
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect('127.0.0.1', $p)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

if (Test-PortInUse $Port) {
    Fail "端口 $Port 已被占用。本脚本不会自动结束其他进程，请先手动关闭占用该端口的程序，或使用 -Port 指定其他端口。"
}
Write-Ok "端口 $Port 可用"

# ---------------------------------------------------------------- 7. 获取局域网 IPv4

function Get-LanIPv4 {
    $seen = @{}
    $result = New-Object System.Collections.ArrayList

    $addrs = @()
    try {
        $addrs = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '127.*' })
    } catch {
        # 退化为 .NET 枚举
        try {
            $addrs = @([System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
                Where-Object { $_.OperationalStatus -eq 'Up' } |
                ForEach-Object { $_.GetIPProperties().UnicastAddresses } |
                Where-Object { $_.Address.AddressFamily -eq 'InterNetwork' } |
                ForEach-Object { [pscustomobject]@{ IPAddress = $_.Address.IPAddressToString; InterfaceAlias = '' } })
        } catch {
            $addrs = @()
        }
    }

    foreach ($a in $addrs) {
        $ip = [string]$a.IPAddress
        if ([string]::IsNullOrWhiteSpace($ip)) { continue }

        # 排除：回环、APIPA 169.254.x.x
        if ($ip -like '127.*') { continue }
        if ($ip -like '169.254.*') { continue }

        $parts = $ip.Split('.')
        if ($parts.Count -ne 4) { continue }
        $o1 = [int]$parts[0]
        $o2 = [int]$parts[1]

        # 只保留 RFC1918 私网地址：192.168.x.x / 10.x.x.x / 172.16-31.x.x
        $isPrivate =
            ($o1 -eq 192 -and $o2 -eq 168) -or
            ($o1 -eq 10) -or
            ($o1 -eq 172 -and $o2 -ge 16 -and $o2 -le 31)
        if (-not $isPrivate) { continue }

        if ($seen.ContainsKey($ip)) { continue }
        $seen[$ip] = $true
        [void]$result.Add([pscustomobject]@{ IP = $ip; Alias = [string]$a.InterfaceAlias })
    }

    # 排序只为输出稳定：192.168 > 10 > 172.16-31
    return @($result | Sort-Object @{ Expression = {
                $p = $_.IP.Split('.')
                if ($p[0] -eq '192') { 1 } elseif ($p[0] -eq '10') { 2 } else { 3 }
            } }, IP)
}

$lanIps = @(Get-LanIPv4)

# ---------------------------------------------------------------- 8. 启动 FastAPI 单服务

Write-Step "启动 FastAPI（--host 0.0.0.0 --port $Port），同时托管 frontend\dist ..."

$backendCmd = "Set-Location '$backend'; & '$venvPy' -m uvicorn app.main:app --host 0.0.0.0 --port $Port"
$proc = Start-Process -FilePath 'powershell' `
    -ArgumentList @('-NoExit', '-NoProfile', '-Command', $backendCmd) `
    -PassThru
Write-Ok "服务进程已启动（PID $($proc.Id)）"

# ---------------------------------------------------------------- 9. 等待 /api/health

Write-Step "等待 http://127.0.0.1:$Port/api/health 就绪 ..."
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {
        Start-Sleep -Milliseconds 750
    }
}
if (-not $ready) {
    Fail "服务未在预期时间内就绪。请查看后端 PowerShell 窗口的输出。"
}
Write-Ok "后端 API 已就绪（/api/health OK）"

# 顺带确认 SPA 入口真的由同一个服务返回（而不是 404）
try {
    $page = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 5
    if ($page.StatusCode -eq 200 -and $page.Content -match 'id="root"') {
        Write-Ok "前端入口已由同一服务托管（/ 返回 SPA）"
    } else {
        Write-Note "根路径返回了非 SPA 内容，请确认 frontend\dist 是否为最新构建。"
    }
} catch {
    Write-Note "根路径探测失败：$($_.Exception.Message)"
}

# ---------------------------------------------------------------- 10. 打印访问地址

$localUrl = "http://127.0.0.1:$Port"

Write-Host ""
Write-Host "===================================="
Write-Host " PingpongSystem production 已启动"
Write-Host "===================================="
Write-Host ""
Write-Host " 本机访问："
Write-Host "   $localUrl" -ForegroundColor Green
Write-Host "   $localUrl/public/t/<赛事ID>/live     (Public 实况，深链接刷新不 404)" -ForegroundColor DarkGray
Write-Host ""

if ($lanIps.Count -gt 0) {
    Write-Host " 局域网访问（手机与电脑需在同一 Wi-Fi/局域网）："
    foreach ($item in $lanIps) {
        $suffix = ''
        if ($item.Alias) { $suffix = "  [$($item.Alias)]" }
        Write-Host "   http://$($item.IP):$Port$suffix" -ForegroundColor Green
    }
    if ($lanIps.Count -gt 1) {
        Write-Host "   （检测到多个私网地址：请逐个尝试，脚本无法可靠判断哪张网卡连通手机所在网络）" -ForegroundColor DarkGray
    }
} else {
    Write-Note "未检测到可用的私网 IPv4 地址，手机可能无法通过局域网访问。"
    Write-Host "        请确认已连接 Wi-Fi/交换机，且网卡未被禁用。" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host " 提示：" -ForegroundColor Yellow
Write-Host "   * 无需管理员权限；本脚本不会修改防火墙或任何系统网络配置。" -ForegroundColor DarkGray
Write-Host "   * 若手机打不开页面，多半是 Windows 防火墙拦截 Python 入站连接：" -ForegroundColor DarkGray
Write-Host "     控制面板 → Windows Defender 防火墙 → 允许应用通过防火墙 → 勾选 Python 的“专用网络”。" -ForegroundColor DarkGray
Write-Host "     或（需管理员权限，请自行决定）放行 TCP $Port 端口。" -ForegroundColor DarkGray
Write-Host "   * 停止服务：直接关闭新打开的后端 PowerShell 窗口，或结束 PID $($proc.Id)。" -ForegroundColor DarkGray
Write-Host "   * 开发 / Demo 双服务模式请改用 .\start_demo.ps1 。" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoBrowser) { Start-Process $localUrl }

exit 0
