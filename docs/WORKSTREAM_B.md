# B 工作线：现场 UI 加固

> **历史工作线说明**
>
> 本文记录的是 V0.2／旧 Dev B“现场 UI 加固”工作线，已结束。V0.3 新版 B 轨为“规则／比赛引擎”，其 Release Candidate 冻结说明见 [D7B_RULE_FREEZE.md](D7B_RULE_FREEZE.md)。

基线：`develop/field-demo-v02`，并依赖 A2 Match Timing 的 `/schedule-estimates` 只读接口。
本工作线只做现场操作与打印体验，不复制后端规则或 DTO。

## 已交付能力

- 大比分录入接入触屏 `− / +` 控件，同时保留键盘输入、幂等 `request_id`、比分审计、修改理由和弃权流程。
- CSV 支持 UTF-8、UTF-8 BOM、GB18030/GBK；无效 CSV、损坏或伪装的 `.xlsx` 提供 Excel/WPS 可操作提示。
- 控制台独立请求 `/api/tournaments/{id}/schedule-estimates`，按 `match_id` 展示预计上场信息；失败时不阻塞现场操作。
- 已结束比赛可打印单场成绩单，数据来自 generated OpenAPI `MatchOut`。
- 秩序册从选手/分组页进入，使用赛事真实局制并打印完整场次。
- TEAM 创建入口、队伍与队员工作表、名单确认、后端分组与小组对抗生成已经连成浏览器主链；创建成功直达 `/team-roster?tid=...`。
- 团体对抗、排名、晋级确认及首轮淘汰签页面只消费既有 API；浏览器真实全链用例从空库创建赛事起跑，止于“生成团体淘汰首轮”。

## 明确未做

- 不向 `MatchOut` 添加 ETA 字段；ETA 属于 `ScheduleEstimates` 推导数据。
- 不恢复旧版手写 `Match` interface。
- 不实现团体赛后端、排阵校验或胜负计算。
- 不改写 A2 的 `called_at`、`started_at`、`finished_at` 语义。
- 不做 TEAM 淘汰胜者传播、TEAM Scheduler/ETA、团体改分/弃权/逐局小分、替补或 A/B/C/X/Y/Z 排阵规则，也不新增官方团体赛制。

## 旧 Dev B 收尾

旧 Dev B 工作线状态：**DONE**。交接到 V0.3 时，该人员应映射到新的 C/D 前端职责，不能映射为新版“B 规则引擎”。

停止点固定为：创建 TEAM 赛事 → 队伍/队员 → 确认名单 → 分组 → 生成小组 TeamTie → 阵容/逐盘录分 → 团体排名 → 晋级确认 → 生成团体淘汰首轮 → STOP。

## 验收命令

```powershell
cd backend
python -m pytest
cd ../frontend
pnpm contract:check
pnpm build
```
