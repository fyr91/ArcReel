# 公司资产库部署与运维

公司资产库使用一套统一模型存放角色、场景和道具，并以 `origin=official | user_shared` 区分资产来源。官方导入与用户共享复用相同的版本、文件、别名和变更日志表，因此 ArcReel 客户端只需要一条“当前清单对账 + 增量追赶”链路。

## 组件边界

- Supabase：保存资产元数据、不可变版本、文件索引、变更日志、监控源与运行记录；私有 Storage bucket 为 `arcreel-assets`。
- 资产源监控：独立 Docker 服务，部署在 Supabase 同一服务器并加入 `supabase_default` 网络。它认领数据库中的运行记录、拉取上游、校验文件、上传 Storage，再通过仅限 `service_role` 的 RPC 原子发布版本。
- ArcReel：登录后按角色、场景、道具分别做当前清单对账并追赶增量；资产页的“同步资产”只同步当前页签；本地删除的公司资产会在下次对账时恢复，本地自建资产不受影响；本地资产通过显式“共享/更新版本”发布。

监控不是 Supabase 数据库插件或数据库内进程。独立容器让网络访问、重试、文件下载和资源限制不占用数据库容器，同时运行状态仍由 Supabase 统一管理。

## 数据与权限

- `arcreel_assets`：稳定资产身份、来源、类型、当前版本与发布状态。
- `arcreel_asset_versions` / `arcreel_asset_files`：不可变版本快照与私有 Storage 对象。
- `arcreel_asset_changes`：冻结当前清单水位并在清单完成后继续追赶的单调增量游标来源。
- `arcreel_asset_sync_sources` / `arcreel_asset_sync_runs`：监控配置、调度、心跳、取消、计数和错误。
- 账号必须处于启用状态才可读取公司资产；用户只能写自己 UUID 前缀下的共享文件；监控写接口只授权 `service_role`；监控管理接口只授权 ArcReel 管理员。

## 服务器部署

1. 先备份 PostgreSQL，再按文件名顺序执行尚未应用的 `supabase/migrations/` 迁移。
2. 将 `asset_sync_worker/` 与 `deploy/asset-sync-worker/` 放到服务器同一部署根目录。
3. 从 `.env.example` 创建仅 root 可读的 `.env`，填写 Supabase `service_role` 和上游资产源令牌。
4. 在 `deploy/asset-sync-worker/` 执行：

   ```bash
   docker compose up -d --build
   docker compose ps
   docker compose logs --tail 100
   ```

5. 若只能开放 50001–50003，可用 `deploy/supabase-tls-proxy/` 将 50002 映射为 Supabase HTTPS。生成的 CA 私钥只留在服务器；把 CA 公钥证书复制到 ArcReel 主机，并设置 `ARCREEL_CLOUD_CA_BUNDLE`。

场景和道具源在没有正式上游接口前保持 `adapter=unconfigured`、禁用和暂停；这不影响两类资产的用户共享、公司存储和 ArcReel 拉取能力。不得用人物样例伪造场景或道具源。

## 日常操作

管理员从资产库页面进入“资产源同步监控”，可查看三个数据源、最近运行、导入/更新/未变/归档计数及错误，亦可立即运行、暂停、恢复、修改间隔、取消或重试。监控采用稳定的上游资产键与内容指纹：内容未变不重复上传，上游缺席只归档官方资产，不删除历史版本或 Storage 文件。

发布失败时，ArcReel 会清理本次已上传但未落版本的对象；同步文件会验证大小与 SHA-256，路径限制在本地全局资产根目录。服务端 `.env`、`service_role`、上游令牌、CA 私钥和账号刷新令牌不得提交到 Git。
