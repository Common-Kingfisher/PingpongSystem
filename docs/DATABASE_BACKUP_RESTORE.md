# 数据库备份与恢复说明

> 适用版本：V0.3 RC
>
> 当前 migration：`v5`
>
> 备份入口：`backend/backup_db.py`
>
> 恢复入口：`backend/restore_db.py`
>
> 最后更新：2026-09-23

## 1. 定位

### 1.1 Tournament Export

```text
GET /api/tournaments/{id}/export
```

用途：

- 赛事归档；
- 结构化交接；
- 人工审阅。

它不能代替整库恢复备份。

### 1.2 Database Backup

```text
python backend/backup_db.py
```

用途：

- 灾难恢复；
- 整库快照；
- 保留 auth、session、tournament、registration、score、audit 和 migration 状态。

核心原则：

> **Tournament Export 不是可恢复数据库备份。**

## 2. 数据库路径

实际路径优先级：

```text
PINGPONG_DB_PATH
>
DEMO_DB_PATH（兼容旧变量，主要用于测试）
>
backend/data/demo.db
```

默认路径：

```text
backend/data/demo.db
```

默认备份目录：

```text
<数据库文件所在目录>/backups/
```

示例：

```powershell
$env:PINGPONG_DB_PATH = 'D:\pingpong\data\demo.db'
```

## 3. 备份内容

整库 backup 会包含：

- SQLite 业务数据；
- users 和 password hash；
- user_sessions；
- tournament_admins 和权限数据；
- tournaments；
- registrations；
- organizations 和 venues；
- players、entries、groups 和 tables；
- matches、match_games、比分请求和审计；
- qualification_decisions 和团体赛数据；
- schema_migrations。

整库 backup 不会自动包含：

- Python 程序版本；
- frontend build 文件；
- `.env`、启动参数和其它配置；
- 自定义外部文件；
- Git 仓库。

因此，发布恢复需要同时保存程序版本和部署配置，不能只依赖 `.db` 文件。

## 4. 正式备份操作

### 4.1 默认数据库

```powershell
cd backend
python backup_db.py
```

### 4.2 指定数据库

```powershell
cd backend
python backup_db.py `
  --database D:\pingpong\data\demo.db
```

### 4.3 指定数据库和备份目录

```powershell
cd backend
python backup_db.py `
  --database D:\pingpong\data\demo.db `
  --backup-dir D:\pingpong\backups
```

### 4.4 实现约束

- backup 使用 SQLite backup API；
- 不直接复制正在运行中的 `.db` 文件；
- 备份文件命名带时间戳；
- 同秒重复备份自动追加 `-01`、`-02` 等序号；
- 复制完成后对生成的备份快照执行完整性、外键及必需表校验；
- 默认目录是 `<db-dir>/backups/`；
- 备份文件不得提交 Git。

命名示例：

```text
pingpong-backup-20260923-180000.db
pingpong-backup-20260923-180000-01.db
```

## 5. 备份成功标准

CLI 成功输出至少应包含：

```text
备份成功
源数据库
integrity_check：ok
foreign_key_check：0 条违规
schema_migrations：5（源库为 legacy v2/v3/v4 时对应输出 2/3/4）
```

只要出现失败或校验不通过，就不能把该文件标记为可恢复备份。

建议在升级、名单确认、重要比赛开始前和赛事结束后分别保存备份。升级前备份是必做项。

## 6. 恢复安全边界

恢复只支持停服离线恢复：

- 必须停止 PingpongSystem 服务；
- 必须显式提供 `--service-stopped`；
- 目标库旁不能有 `-wal`、`-shm`、`-journal`；
- 备份文件不存在时拒绝恢复；
- `integrity_check` 不通过时拒绝恢复；
- `foreign_key_check` 不通过时拒绝恢复；
- 缺少必需表时拒绝恢复；
- migration 后版本不是当前版本时拒绝恢复；
- 替换前自动生成 pre-restore backup；
- 先复制到临时库并完成 migration 和校验，再原子替换正式库；
- 替换后校验失败时尝试恢复 pre-restore backup；
- 不支持在线热恢复。

## 7. 恢复操作

### 7.1 恢复前

```text
1. 停止服务
2. 确认没有 backend Python / Uvicorn 进程占用数据库
3. 确认目标数据库旁没有 -wal / -shm / -journal
4. 记录待恢复 backup 文件路径
5. 确认实际目标数据库路径
```

### 7.2 执行恢复

```powershell
cd backend

python restore_db.py `
  D:\pingpong\backups\pingpong-backup-20260923-180000.db `
  --database D:\pingpong\data\demo.db `
  --backup-dir D:\pingpong\backups `
  --service-stopped
```

### 7.3 恢复流程

```text
待恢复 backup
  -> 校验 backup 文件
  -> 复制到临时数据库
  -> 执行 init_db / migration
  -> 检查 integrity / FK / required tables / migration version
  -> 原子替换目标数据库
  -> 再次校验
```

### 7.4 恢复后 smoke

```text
1. 启动应用
2. 检查 /api/health
3. 管理员登录
4. 打开一个历史赛事
5. 检查报名、比赛、排名和审计
6. 确认没有异常日志
```

## 8. 恢复成功标准

CLI 成功输出至少应包含：

```text
恢复成功
来源备份
恢复前备份
integrity_check：ok
foreign_key_check：0 条违规
schema_migrations：5
```

如果目标库原先不存在，CLI 会显示“目标库原先不存在”。如果原先存在，必须保留并记录 pre-restore backup 路径。

## 9. 版本兼容

### 9.1 旧 backup 移动到当前版本

恢复时会把 backup 复制到临时库，执行当前 migration，再替换目标库。因此旧 migration 备份可以在当前程序下升级。backup 按源库 migration 版本校验：当前 v5 库要求全部必需表，legacy v2/v3/v4 库允许缺少 v5 新增表，v2 还允许缺少 v3 新增的 `system_state`；恢复时再迁移到 v5 并按当前完整表清单校验。

### 9.2 新 backup 不保证向下兼容

较新版本生成的 backup 可能包含旧程序不认识的表、列或 migration。不要假设旧程序可以直接恢复新 backup。

规则：

- RC 发布前优先使用同版本工具备份；
- 升级前必须先生成一次整库 backup；
- 恢复失败时保留失败库和 pre-restore backup；
- 不要手工编辑 `schema_migrations` 强行跳过版本。

## 10. 已知限制

- 没有在线热恢复；
- 没有云备份；
- 没有自动定时备份服务；
- 备份不包含程序、前端构建物和 `.env`；
- 恢复会覆盖整库；
- `user_sessions` 随整库恢复，旧 Session 可能重新有效；
- Tournament Export 不能用于灾难恢复；
- 未来若新增 v6，本说明和验证证据必须同步更新。

## 11. 备份文件安全

backup 包含用户资料、password hash、session 数据、赛事数据和联系方式，必须按敏感文件处理：

- 不发送到公共渠道；
- 不提交 Git；
- 不上传 issue 或 PR；
- 只由赛事服务器维护者保管；
- 复制后限制目录和文件访问权限；
- 恢复失败后不要随意丢弃现场备份。

## 12. 验证证据

当前 D7A 定向验证：

```text
tests/test_database_backup_restore.py
tests/test_restart_persistence.py
tests/test_schema_migrations.py
tests/test_d6a_concurrency.py
tests/test_tournament_export.py
```

结果：`38 passed`，`0 failed`。

已验证场景包括：

- 空库 backup / restore 后应用启动；
- 报名状态 round trip；
- 进行中比赛状态 round trip；
- 已结束比赛和审计 round trip；
- 损坏 backup 不覆盖目标库；
- 未提供 `--service-stopped` 时拒绝恢复；
- 旧 migration backup 升级且数据不丢；
- 原子替换失败时原库保持不变；
- 缺 `system_state` 时拒绝生成或恢复伪成功快照。
