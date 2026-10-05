# 前端浏览器验收

冠军之路测试通过拦截 API 返回固定签表，验证 7 场比赛、7 条真实依赖连线及其来源拓扑、3 段冠军高亮路线，并实际滚动窄屏画布。完整排位测试验证季军、9–16、13–16、15–16 等区间不会混成一张难以识别的比赛列表。

`test_operation_mode.py` 连接真实本地前后端，验证正式/演示标识、演示按钮隔离及后端拒绝正式赛事调用演示接口。

人工晋级裁定测试通过固定的三人完全并列排名，验证候选选择、理由/操作者必填、提交载荷及裁定后的审计展示。

在 `frontend` 目录启动预览服务后运行：

```powershell
python -m pip install -r e2e/requirements.txt
$env:PINGPONG_E2E_URL = "http://127.0.0.1:4173"
python e2e/test_champion_journey.py
python e2e/test_placement_bracket.py
```

默认使用本机 Microsoft Edge；可通过 `PLAYWRIGHT_CHANNEL` 改为其他已安装的 Chromium 通道。

## 现场问题清单验收（2026-10-05，Node + Playwright）

`field_issues_20261005.mjs` 针对现场问题清单的 5 个缺陷做**真实浏览器**验收：
真实 FastAPI + 真实 SQLite + 真实 Chromium（`channel: 'chrome'`），
覆盖 jsdom 无法证明的部分 —— viewport 可达性、CSS 布局、
SVG 连线在横向滚动 / resize / 横竖屏后的**视口坐标**对齐、以及双裁判并发冲突的真实 HTTP 行为。

与上面 Python 用例不同，它**不拦截 API**：脚本自己 bootstrap 账号、建赛事、跑完小组赛并生成淘汰签，
然后驱动页面。因此它同时验证前后端契约，而不只是前端渲染。

```powershell
# 1) 构建前端（后端会以单服务方式托管 frontend/dist）
cd frontend
pnpm build

# 2) 用独立数据库启动后端（不要用现场库）
cd ../backend
$env:PINGPONG_DB_PATH = "$env:TEMP\field_e2e.db"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8011

# 3) 另开一个终端安装 playwright 并运行（Node 版，非 e2e/requirements.txt）
npm install playwright
$env:BASE_URL = "http://127.0.0.1:8011"
$env:OUT_DIR = "$env:TEMP\field-evidence"
node e2e/field_issues_20261005.mjs
```

脚本退出码 0 表示全部通过；结果（含逐条断言与实测数值）写入
`$env:OUT_DIR/results.json`，截图同样写入该目录。

2026-10-05 冻结结果：**80 项全部通过**，见
`docs/evidence/field-issues-20261005/`（含 `browser-acceptance-results.json` 与三组截图）。
`playwright` **不是**本仓库依赖，未写入 `package.json`：它只在人工现场验收时临时安装。

## 团体赛真实联调

另开一个终端启动独立数据库与后端（不会写入 `backend/data/demo.db`）：

```powershell
cd backend
python run_team_tie_demo.py --fresh
```

再启动 `pnpm dev`，然后运行真实浏览器链路：

```powershell
$env:PINGPONG_E2E_URL = "http://127.0.0.1:5173"
$env:TEAM_TIE_E2E_TID = "<启动器输出的赛事 id>"
$env:TEAM_TIE_E2E_TIE_ID = "<启动器输出的对抗 id>"
python e2e/test_team_tie_live.py
```

启动器会直接打印前两条环境变量的 PowerShell 赋值。该验收不拦截 API；它验证真实后端的已分组对抗、阵容确认、逐盘录分、提前结束与团体排名展示。

## 团体名单真实联调

另开一个终端启动独立数据库与后端：

```powershell
cd backend
python run_team_roster_demo.py --fresh
```

再启动 `pnpm dev`，把启动器输出的赛事 id 填入后运行：

```powershell
$env:TEAM_ROSTER_E2E_TID = "<赛事 id>"
python e2e/test_team_roster_live.py
```

该验收不拦截 API；它验证浏览器分配未归队队员、保存工作表与确认冻结的真实 FastAPI/SQLite 链路。

## TEAM 纯 UI 全链

在一个空的独立数据库启动 FastAPI、再启动 Vite 后执行：

```powershell
$env:PINGPONG_E2E_URL = "http://127.0.0.1:5173"
$env:TEAM_UI_JOURNEY_E2E = "1"
python e2e/test_team_ui_journey_live.py
```

该用例不使用 seed/demo 脚本：浏览器创建 TEAM 赛事、录入队伍与队员、确认名单、调用后端分组和小组对抗生成、录入两场小组对抗、确认晋级并生成淘汰首轮。首轮生成后即停止；不覆盖未实现的胜者传播。

## 团体晋级与淘汰签真实联调

另开一个终端启动独立数据库与后端：

```powershell
cd backend
python run_team_qualification_knockout_demo.py --fresh
```

再启动 `pnpm dev`，把启动器输出的赛事 id 填入后运行：

```powershell
$env:TEAM_QUALIFICATION_KNOCKOUT_E2E_TID = "<赛事 id>"
python e2e/test_team_qualification_knockout_live.py
```

该验收不拦截 API；它以既有 Runtime 真实完成四个两队小组赛，再在浏览器中确认八支晋级队伍、生成四场首轮淘汰对抗，并验证两场半决赛与一场决赛保持待上游胜者状态。
