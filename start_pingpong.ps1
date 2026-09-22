<#
.SYNOPSIS
    PingpongSystem production / 局域网单服务启动脚本（D 轨 Day 2，Day 4D 加固）。

.DESCRIPTION
    与 start_demo.ps1 的区别：

    * start_demo.ps1      = 开发 / Demo 双服务模式（FastAPI 8000 + Vite 5173）
    * start_pingpong.ps1  = production 单服务模式（只启动 FastAPI 8000，同时托管前端构建产物）

    流程：定位根目录 -> 检查 Python/venv/依赖 -> 确认或构建 frontend/dist
          -> 检查端口 -> uvicorn --host 0.0.0.0 --port 8000
          -> 等待 /api/health -> 探测 SPA 根路径与 Public 深链接
          -> 枚举并打印本机与局域网 IPv4（多网卡时给出选择提示）
          -> 若已存在赛事，打印基于**真实赛事 id** 的 Public 示例地址。

    Day 4D 加固点（现场 LAN 收口）：

    * 多网卡：区分真实 Wi-Fi / Ethernet 与 WSL / VPN / Hyper-V / VMware / Docker 等虚拟网卡，
      物理网卡优先展示，虚拟网卡**只降权、绝不删除**（脚本无法证明某张网卡一定无效）；
    * 多地址：明确提示“检测到多个局域网地址。请选择与比赛手机所在路由器同网段的地址。”；
    * Public 示例地址使用**真实读到的赛事 id**；读不到就只展示 base URL，
      绝不假定“赛事 id 永远是 12”；
    * 深链接探测：/public/t/<tid>/live 必须由同一个服务返回 SPA（刷新不 404）。

    本脚本明确**不会**：

    * 申请管理员权限
    * 修改 / 新增 / 删除 Windows 防火墙规则
    * 关闭 Windows 防火墙
    * 结束或重启其他进程
    * 修改本机网卡 IP / 网关 / DNS，也不修改路由器
    * 把服务暴露到公网
    * 把任何固定 IP / 主机名 / 域名写入代码或配置

    若手机无法访问，脚本只输出人工排查提示。

.EXAMPLE
    .\start_pingpong.ps1

.EXAMPLE
    .\start_pingpong.ps1 -SkipBuild      # 要求 dist 必须已存在，跳过自动构建
    .\start_pingpong.ps1 -NoBrowser      # 不自动打开浏览器
    .\start_pingpong.ps1 -TournamentId 12  # 直接指定打印 Public 示例所用的赛事 id
#>

[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$SkipBuild,
    [switch]$NoBrowser,
    # 可选：显式指定用于打印 Public 示例地址的赛事 id。
    # 不传时脚本只读地查一次本机 SQLite，取当前最小的真实赛事 id；两者都拿不到就只展示 base URL。
    [int]$TournamentId = 0
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

# ------------------------------------------------------- 7. 网卡识别与局域网 IPv4

<#
    判断一个网卡名 / 描述是否属于“虚拟 / 隧道 / 非常规”类别。

    ⚠️ 这里只做**降权标记**，不做删除：
    WSL / VPN / 虚拟网卡也可能真的连着比赛网络，脚本没有能力证明某张网卡一定无效，
    静默丢弃候选地址比多显示一行更危险。
#>
function Test-VirtualAdapterName([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return $false }
    $lower = $text.ToLowerInvariant()
    $keywords = @(
        'wsl', 'vethernet', 'hyper-v', 'vmware', 'virtualbox', 'vbox',
        'docker', 'vpn', 'tap-', 'tun', 'tailscale', 'zerotier', 'radmin',
        'openvpn', 'wireguard', 'hamachi', 'npcap', 'loopback',
        'bluetooth', 'virtual', 'pseudo', 'teredo', 'isatap'
    )
    foreach ($kw in $keywords) {
        if ($lower.Contains($kw)) { return $true }
    }
    return $false
}

<# 读取网卡元数据（名称 / 描述 / 连接状态 / 是否虚拟）。Get-NetAdapter 不可用时返回空表。 #>
function Get-NetAdapterMap {
    $map = @{}
    try {
        foreach ($a in @(Get-NetAdapter -ErrorAction Stop)) {
            $map[[string]$a.ifIndex] = [pscustomobject]@{
                Name        = [string]$a.Name
                Description = [string]$a.InterfaceDescription
                Status      = [string]$a.Status
                Virtual     = [bool]$a.Virtual
            }
        }
    } catch {
        # 老系统 / 精简环境：后续退化为“按网卡名关键字降权”
    }
    return $map
}

<#
    枚举候选局域网 IPv4。

    只保留 RFC1918 私网地址（192.168.x.x / 10.x.x.x / 172.16-31.x.x），
    排除回环与 APIPA(169.254.x.x)。

    排序权重（只影响展示顺序，不影响是否展示）：
      1 = 物理网卡且状态 Up（最可能是现场路由器同网段）
      2 = 状态未知（拿不到 Get-NetAdapter 元数据）
      3 = 虚拟 / 隧道网卡，或明确未连接
#>
function Get-LanIPv4 {
    $adapterMap = Get-NetAdapterMap
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
                ForEach-Object {
                    $ifName = $_.Name
                    $_.GetIPProperties().UnicastAddresses |
                        Where-Object { $_.Address.AddressFamily -eq 'InterNetwork' } |
                        ForEach-Object {
                            [pscustomobject]@{
                                IPAddress      = $_.Address.IPAddressToString
                                InterfaceAlias = $ifName
                                InterfaceIndex = -1
                            }
                        }
                })
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

        $alias = ''
        $desc = ''
        $status = ''
        $isVirtual = $false
        $index = -1
        if ($a.PSObject.Properties.Name -contains 'InterfaceAlias') { $alias = [string]$a.InterfaceAlias }
        if ($a.PSObject.Properties.Name -contains 'InterfaceIndex') { $index = [int]$a.InterfaceIndex }

        if ($index -ge 0 -and $adapterMap.ContainsKey([string]$index)) {
            $info = $adapterMap[[string]$index]
            if ($info.Description) { $desc = $info.Description }
            if ($info.Status) { $status = $info.Status }
            $isVirtual = $info.Virtual
            if ([string]::IsNullOrWhiteSpace($alias)) { $alias = $info.Name }
        }

        # Get-NetAdapter 不可用 / 未标记 Virtual 时，退化为关键字判断
        if (-not $isVirtual) {
            if ((Test-VirtualAdapterName $alias) -or (Test-VirtualAdapterName $desc)) {
                $isVirtual = $true
            }
        }

        $rank = 2
        if ($isVirtual) {
            $rank = 3
        } elseif ($status -eq 'Up') {
            $rank = 1
        } elseif (-not [string]::IsNullOrWhiteSpace($status)) {
            # 明确不是 Up（Disconnected / Disabled …）：降权但仍展示
            $rank = 3
        }

        [void]$result.Add([pscustomobject]@{
            IP      = $ip
            Alias   = $alias
            Desc    = $desc
            Status  = $status
            Virtual = $isVirtual
            Rank    = $rank
        })
    }

    # 排序只为输出稳定：物理优先（192.168 > 10 > 172.16-31），虚拟网卡一律靠后
    return @($result | Sort-Object Rank, @{ Expression = {
                $p = $_.IP.Split('.')
                if ($p[0] -eq '192') { 1 } elseif ($p[0] -eq '10') { 2 } else { 3 }
            } }, IP)
}

$lanIps = @(Get-LanIPv4)

<#
    只读探测本机 SQLite，取当前最小（最早创建）的赛事 id，用于打印 Public 示例地址。

    - 不经过 HTTP：`GET /api/tournaments` 需要登录态，启动脚本不该依赖任何凭据；
    - 不写死任何 id：拿不到就返回 $null，由调用方退化为“只展示 base URL”；
    - 只读打开（mode=ro），不改库、不迁移、不加锁；
    - 失败一律静默降级：探测不到赛事不应阻断启动。
#>
function Get-PublicTournamentId {
    if ($TournamentId -gt 0) { return $TournamentId }

    $probeFile = Join-Path ([System.IO.Path]::GetTempPath()) ("pingpong_tid_probe_{0}.py" -f $PID)
    $dbPath = $env:PINGPONG_DB_PATH
    if ([string]::IsNullOrWhiteSpace($dbPath)) { $dbPath = $env:DEMO_DB_PATH }
    if ([string]::IsNullOrWhiteSpace($dbPath)) {
        $dbPath = Join-Path $backend 'data\demo.db'
    }

    $probeCode = @'
import os
import sqlite3
import sys

db = os.environ.get("PINGPONG_DB_PATH") or os.environ.get("DEMO_DB_PATH") or sys.argv[1]
if not os.path.isfile(db):
    sys.exit(0)
try:
    con = sqlite3.connect("file:%s?mode=ro" % db.replace("?", "%3f"), uri=True)
except sqlite3.Error:
    sys.exit(0)
try:
    row = con.execute("SELECT id FROM tournaments ORDER BY id LIMIT 1").fetchone()
finally:
    con.close()
if row and row[0] is not None:
    sys.stdout.write(str(int(row[0])))
'@

    try {
        Set-Content -LiteralPath $probeFile -Value $probeCode -Encoding UTF8
        $out = & $venvPy $probeFile $dbPath 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $text = ([string]$out).Trim()
        if ([string]::IsNullOrWhiteSpace($text)) { return $null }
        if ($text -notmatch '^\d+$') { return $null }
        return [int]$text
    } catch {
        return $null
    } finally {
        if (Test-Path -LiteralPath $probeFile) {
            Remove-Item -LiteralPath $probeFile -Force -ErrorAction SilentlyContinue
        }
    }
}

<#
    只读查看 Windows 防火墙“配置文件”的入站默认动作，仅用于给出提示。

    ⚠️ 不申请管理员权限、不新增 / 修改 / 删除任何规则、不关闭防火墙。
    读取失败（常见于标准用户）时返回 $null，脚本退化为打印通用人工排查步骤。
#>
function Get-FirewallBlockingProfiles {
    try {
        $profiles = @(Get-NetFirewallProfile -ErrorAction Stop)
        $blocking = @($profiles | Where-Object {
            $_.Enabled -eq $true -and [string]$_.DefaultInboundAction -eq 'Block'
        })
        if ($blocking.Count -eq 0) { return $null }
        return (@($blocking | ForEach-Object { [string]$_.Name }) -join ' / ')
    } catch {
        return $null
    }
}

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

# Public 深链接探测：刷新 / 直接粘贴链接都不得 404。
$publicTid = Get-PublicTournamentId
$deepLinkPath = if ($publicTid -ne $null) { "/public/t/$publicTid/live" } else { "/public/t/1/live" }
try {
    $deep = Invoke-WebRequest -Uri "http://127.0.0.1:$Port$deepLinkPath" -UseBasicParsing -TimeoutSec 5
    if ($deep.StatusCode -eq 200 -and $deep.Content -match 'id="root"') {
        if ($publicTid -ne $null) {
            Write-Ok "Public 深链接已由同一服务返回 SPA（$deepLinkPath 刷新不 404）"
        } else {
            # 还没有赛事：只能证明“HTTP 层不会 404”，赛事是否存在由页面自己提示
            Write-Ok "SPA 深链接回退正常（$deepLinkPath 返回 SPA，刷新不 404）"
        }
    } else {
        Write-Note "深链接返回了非 SPA 内容，请确认 frontend\dist 是否为最新构建。"
    }
} catch {
    Write-Note "深链接探测失败（$deepLinkPath）：$($_.Exception.Message)"
}

# ---------------------------------------------------------------- 10. 打印访问地址

$localUrl = "http://127.0.0.1:$Port"
$lanBase = if ($lanIps.Count -gt 0) { "http://$($lanIps[0].IP):$Port" } else { $null }

Write-Host ""
Write-Host "===================================="
Write-Host " PingpongSystem 已启动"
Write-Host "===================================="
Write-Host ""
Write-Host " 本机："
Write-Host "   $localUrl" -ForegroundColor Green
Write-Host ""

Write-Host " 局域网："
if ($lanIps.Count -gt 0) {
    foreach ($item in $lanIps) {
        $suffix = ''
        if ($item.Alias) {
            $suffix = "  [$($item.Alias)"
            if ($item.Status) { $suffix += " · $($item.Status)" }
            $suffix += "]"
        }
        if ($item.Virtual) { $suffix += "  （虚拟 / 隧道网卡）" }
        Write-Host "   http://$($item.IP):$Port$suffix" -ForegroundColor Green
    }
    if ($lanIps.Count -gt 1) {
        Write-Note "检测到多个局域网地址。请选择与比赛手机所在路由器同网段的地址。"
    }
} else {
    Write-Note "未检测到可用的私网 IPv4 地址，手机可能无法通过局域网访问。"
    Write-Host "        请确认已连接 Wi-Fi/交换机，且网卡未被禁用。" -ForegroundColor DarkGray
}
Write-Host ""

Write-Host " 手机使用："
Write-Host "   1. 连接赛事现场路由器 Wi-Fi"
Write-Host "   2. 打开浏览器"
Write-Host "   3. 输入以上局域网地址"
Write-Host ""

if ($publicTid -ne $null -and $lanBase -ne $null) {
    Write-Host " Public 示例："
    Write-Host "   $lanBase/public/t/$publicTid/live" -ForegroundColor Green
    if ($lanIps.Count -gt 1) {
        Write-Host "   （把主机部分换成上面与手机同网段的地址即可）" -ForegroundColor DarkGray
    }
    Write-Host "   这是赛事 #$publicTid 的公开实况页；把 /live 换成 /schedule、/rankings、/bracket、/champion 可直达其它公开页面。" -ForegroundColor DarkGray
} else {
    Write-Host " Public 示例："
    if ($lanBase -ne $null) {
        Write-Host "   $lanBase" -ForegroundColor Green
    } else {
        Write-Host "   $localUrl" -ForegroundColor Green
    }
    Write-Host "   尚未读到赛事 id，因此只给出 base URL；创建赛事后请在地址后加 /public/t/<赛事ID>/live 。" -ForegroundColor DarkGray
    Write-Host "   也可用 -TournamentId <赛事ID> 重新运行本脚本以直接打印完整示例地址。" -ForegroundColor DarkGray
}
Write-Host ""

$firewallProfiles = Get-FirewallBlockingProfiles

Write-Host " 提示：" -ForegroundColor Yellow
Write-Host "   * 无需管理员权限；本脚本不会修改防火墙或任何系统网络配置（网卡 IP / 路由器 / DNS 一律不动）。" -ForegroundColor DarkGray
Write-Host "   * 若手机打不开页面，多半是 Windows 防火墙拦截 Python 入站连接：" -ForegroundColor DarkGray
Write-Host "     控制面板 → Windows Defender 防火墙 → 允许应用通过防火墙 → 勾选 Python 的“专用网络”。" -ForegroundColor DarkGray
Write-Host "     或（需管理员权限，请自行决定）放行 TCP $Port 端口。" -ForegroundColor DarkGray
if ($firewallProfiles) {
    Write-Host "     只读检测：当前入站默认动作仍为“阻止”的防火墙配置文件：$firewallProfiles" -ForegroundColor DarkGray
}
Write-Host "   * 同一台电脑上访问本机 LAN 地址不代表手机一定能访问（不经过防火墙入站路径），必须用真实手机验证。" -ForegroundColor DarkGray
Write-Host "   * 停止服务：直接关闭新打开的后端 PowerShell 窗口，或结束 PID $($proc.Id)。" -ForegroundColor DarkGray
Write-Host "   * 开发 / Demo 双服务模式请改用 .\start_demo.ps1 。" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoBrowser) { Start-Process $localUrl }

exit 0
