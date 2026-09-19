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
