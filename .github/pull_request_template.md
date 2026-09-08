## 本次改动

- 

## 明确未改

- 

## 影响范围

- [ ] 数据库结构或迁移
- [ ] API / Pydantic Schema
- [ ] OpenAPI 快照及生成的 TypeScript 类型
- [ ] 前端页面或交互
- [ ] 核心赛制、排名或晋级规则

## 验证

- [ ] 新增或更新自动化测试
- [ ] 后端完整测试通过
- [ ] 前端 TypeScript 与生产构建通过
- [ ] 接口变化时契约检查通过
- [ ] 已写出主裁判手动测试步骤

## 文档

- [ ] README / 操作手册已按需更新
- [ ] HANDOFF / DEVELOPMENT_ROADMAP 已按需更新
- [ ] CHANGELOG 已更新

## 已知限制与回退

- 已知限制：
- 回退方法：Revert 本 PR 的 squash commit；涉及数据库新增列时保留兼容列，不直接删除现场数据。
