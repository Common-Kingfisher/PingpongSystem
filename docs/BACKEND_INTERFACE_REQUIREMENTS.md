# B 工作线后端接口约定

状态：与 `develop/field-demo-v02` 的 OpenAPI 契约保持一致。本文描述前端消费边界，不扩展团体赛业务模型。

## 1. 预计上场时间

前端通过以下只读接口获取动态预测：

```http
GET /api/tournaments/{id}/schedule-estimates
```

- `ScheduleEstimates` 是根据当前球台、比赛进度和调度规则即时推导的结果，不写入比赛事实。
- `MatchOut` 只保存比赛事实；不得增加 `queue_ahead` 或 `estimated_start_at`。
- 前端以 `ScheduleEstimateMatch.match_id` 关联 `MatchOut.id`，不得自行重新实现调度算法。
- 预计时间是提示而非保证；现场状态变化后会重新计算。
- 无法估算时，`estimated_start_at`、`queue_ahead` 可以为 `null`，并通过 `unavailable_reason` 说明原因。
- 接口请求失败或单场预测缺失时，比赛控制台必须正常工作，只降级隐藏具体预测。

## 2. 单场成绩单

成绩单直接使用 OpenAPI 生成的 `MatchOut` 和 `TournamentOut`：比赛标识、赛段、球台、双方、
大比分、逐局 `games`、`result_type`、`result_note`、`called_at`、`started_at`、`finished_at`
以及赛事的 `games_to_win`、`points_to_win`。前端不得复制手写 Match DTO。

## 3. 团体赛占位边界

当前 `TEAM` 只能作为禁用的 UI 占位。不得修改后端 `EventType`，不得创建 Team/TeamTie 数据模型，
不得由前端判断合法阵容或计算团体胜负。待规则冻结且后端契约、校验、测试齐备后另开 PR 启用。

## 4. 联调验收

- OpenAPI 快照、生成的 TypeScript 类型和后端 schema 一致。
- ETA 覆盖正常预测、`null`/`unavailable_reason`、单场缺失和请求失败。
- 不破坏现有录分、改分审计、弃权、打印、CSV 导入和单打/双打流程。
