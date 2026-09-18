# B 工作线：现场 UI 加固

基线：`develop/field-demo-v02`，并依赖 A2 Match Timing 的 `/schedule-estimates` 只读接口。
本工作线只做现场操作与打印体验，不复制后端规则或 DTO。

## 已交付能力

- 大比分录入接入触屏 `− / +` 控件，同时保留键盘输入、幂等 `request_id`、比分审计、修改理由和弃权流程。
- CSV 支持 UTF-8、UTF-8 BOM、GB18030/GBK；无效 CSV、损坏或伪装的 `.xlsx` 提供 Excel/WPS 可操作提示。
- 控制台独立请求 `/api/tournaments/{id}/schedule-estimates`，按 `match_id` 展示预计上场信息；失败时不阻塞现场操作。
- 已结束比赛可打印单场成绩单，数据来自 generated OpenAPI `MatchOut`。
- 秩序册从选手/分组页进入，使用赛事真实局制并打印完整场次。
- `TeamTiePage`、`TeamScorePanel` 和禁用的 `TEAM` 选项仅作界面占位，不代表团体赛可用。

## 明确未做

- 不向 `MatchOut` 添加 ETA 字段；ETA 属于 `ScheduleEstimates` 推导数据。
- 不恢复旧版手写 `Match` interface。
- 不实现团体赛后端、排阵校验或胜负计算。
- 不改写 A2 的 `called_at`、`started_at`、`finished_at` 语义。

## 验收命令

```powershell
cd backend
python -m pytest
cd ../frontend
pnpm contract:check
pnpm build
```
