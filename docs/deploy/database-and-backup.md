# Beacon 数据库与备份恢复（SQLite / Postgres / 文件数据）

本文档用于说明 Beacon 在运行阶段测试与工业交付场景下的数据落点、数据库选型建议、备份与恢复流程，覆盖：

- Admin 数据库：SQLite（默认）与 Postgres（可选）
- 文件数据：`uploadDir`、`modelDir`、日志目录
- 备份策略：周期、留存、离线介质、恢复演练

相关文档：

- 上线检查清单：`docs/deploy/go-live-checklist.md`
- 运维手册（诊断包/清理）：`docs/deploy/ops-runbook.md`
- 配置参考：`docs/deploy/config-reference.md`

---

## 1. 数据落点总览

Beacon 的“关键数据”通常分三类：

1. 数据库（Admin）：
   - 用户、权限、ApiKey、Streams、Controls、告警元数据、运维审计等
2. 文件数据（磁盘）：
   - 告警截图/告警视频/录制文件（`uploadDir`）
   - 模型文件（`modelDir`）
3. 日志与诊断（可选留存）：
   - Admin/Analyzer/MediaServer 日志
   - 诊断包导出（zip）

备份与恢复必须覆盖“数据库 + 文件数据”，否则会出现“告警记录存在但文件缺失”或“文件存在但数据库索引丢失”等不一致问题。

---

## 2. Admin 数据库选型与配置

### 2.1 SQLite（默认）

默认数据库：

- 文件：`Admin/Admin.sqlite3`
- 可通过环境变量覆盖路径：`BEACON_SQLITE_DB_PATH=/abs/path/to/db.sqlite3`

并发注意事项：

- SQLite 在多线程/多并发写入场景容易出现 `database is locked`。
- Beacon 提供写锁等待超时配置（秒）：`BEACON_SQLITE_TIMEOUT_SECONDS`（默认 30）。
- 工业交付或多用户并发较高场景建议迁移到 Postgres。

### 2.2 Postgres（推荐用于工业交付/多并发）

Beacon 提供 “DB URL -> Django DATABASES” 解析能力（当前实现仅支持 Postgres）：

- 环境变量：`BEACON_CLOUD_DB_URL`
- URL 形如：
  - `postgres://user:pass@host:5432/dbname`
  - `postgresql://user:pass@host:5432/dbname`

本地/Edge 环境需先安装 `Admin/requirements-optional.txt` 中的 PostgreSQL
驱动；Cloud 镜像已经包含该驱动。

启用后，Admin 将使用 Postgres 替代 SQLite（详见 `Admin/framework/settings.py` 与 `Admin/app/utils/DbUrl.py`）。

---

## 3. SQLite 备份与恢复

### 3.1 备份策略（推荐）

推荐备份窗口：

- 在业务低峰期执行
- 执行前建议停止 Admin（或至少确保无写入峰值）

最保守的备份方法（停服务后复制文件）：

- 停止 Admin 进程
- 复制 `Admin/Admin.sqlite3` 到备份目录
- 记录备份时间与对应版本（可附加诊断包留档）

说明：

- Windows 下文件锁更常见，停服务后复制是最稳妥方案。
- 若运行方式为容器/服务，可使用宿主机快照或卷快照方式执行。

### 3.2 恢复（SQLite）

恢复流程（概念步骤）：

1. 停止 Admin
2. 替换 `Admin/Admin.sqlite3` 为备份文件
3. 启动 Admin
4. 执行健康检查与最小验收（见 `docs/deploy/go-live-checklist.md` 与 `docs/deploy/e2e-acceptance.md`）

如版本跨越较大，建议在恢复后执行：

- `python Admin/manage.py migrate --noinput`

---

## 4. Postgres 备份与恢复（示例）

### 4.1 备份（逻辑备份）

建议输出为自包含的 custom format，便于校验与恢复：

```bash
pg_dump -Fc -h <host> -p 5432 -U <user> -d <dbname> -f beacon_db.dump
```

建议同时导出 `pg_dump --schema-only`（用于审计/对比，可选）：

```bash
pg_dump -s -h <host> -p 5432 -U <user> -d <dbname> -f beacon_schema.sql
```

### 4.2 恢复（示例）

恢复到空库（示例）：

```bash
createdb -h <host> -p 5432 -U <user> <new_dbname>
pg_restore -h <host> -p 5432 -U <user> -d <new_dbname> --clean --if-exists beacon_db.dump
```

恢复完成后：

- 以 `BEACON_CLOUD_DB_URL` 指向新库启动 Admin
- 执行健康检查与端到端验收

说明：

- 工业交付中更推荐将备份/恢复纳入 DBA 标准流程，并配合权限最小化与备份加密。

---

## 5. SQLite -> Postgres 迁移（运行阶段常见）

SQLite 到 Postgres 的迁移属于交付工程能力，常见做法：

1. 冻结变更窗口（停写入）
2. 备份 SQLite（见上节）
3. 创建 Postgres 数据库并配置 `BEACON_CLOUD_DB_URL`
4. 在新库上执行 `migrate`
5. 导入数据（例如 Django `dumpdata/loaddata`、定制迁移脚本、或通过业务侧导出导入功能）
6. 对齐 `uploadDir` 文件数据（告警素材、录制文件等）
7. 验收与回滚预案准备

说明：

- 不同交付包的历史版本与数据规模差异较大，“自动迁移脚本”不宜在文档层做绝对承诺。
- 建议先在隔离环境演练迁移流程，并固化为交付 SOP。

---

## 6. 文件数据备份（`uploadDir` / `modelDir` / 日志）

### 6.1 告警素材与录制数据（`uploadDir`）

字段来源：

- `config.json.uploadDir`
- 或 env 覆盖：`BEACON_UPLOAD_DIR`

建议：

- 交付包将可变数据统一落在 `${BEACON_ROOT_DIR}/data/upload/`
- 备份策略按业务留存要求执行（例如 7 天、30 天、90 天），并与磁盘容量规划协同

### 6.2 模型目录（`modelDir`）

字段来源：

- `config.json.modelDir`
- 或 env 覆盖：`BEACON_MODEL_DIR`

建议：

- 将模型目录纳入“发布物”管理，避免与运行时数据混放
- 交付包建议固化为 `${BEACON_ROOT_DIR}/data/models/`，并明确版本号与校验（hash）

### 6.3 日志与诊断包

建议纳入备份的内容：

- 诊断包（`/open/ops/diagnostics/export`）用于工单流转与验收留档（注意敏感信息）

不建议纳入长期备份的内容（按场景选择）：

- 大量历史日志（建议由日志系统集中采集并做归档；本地仅保留有限天数）

参考：

- `docs/deploy/ops-runbook.md` 的“诊断包导出”“清理”“日志落盘与位置”

---

## 7. 恢复演练（建议固化为上线前必做）

建议至少完成一次“全量恢复演练”：

- 在隔离环境恢复数据库（SQLite 文件或 Postgres dump）
- 恢复 `uploadDir` 与 `modelDir`（按实际交付内容）
- 启动 Admin/Analyzer/MediaServer
- 执行 L0/L1 级别验收（见 `docs/deploy/e2e-acceptance.md`）

输出物建议包含：

- 演练时间、版本号、配置摘要（脱敏）
- 健康检查结果与验收结果
- 遗留问题与改进项
