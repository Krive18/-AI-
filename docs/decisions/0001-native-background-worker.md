# ADR-0001：首版采用 MySQL 状态机与 Redis 租约 Worker

## 状态

Accepted

## 日期

2026-09-01

## 背景

视频校验、ASR、翻译、TTS 和 FFmpeg 渲染不能在 FastAPI 请求中执行。首版需要同时满足：

- 本地环境为 Windows、MySQL 8.0 和 Redis 3.2，不使用 Docker；
- 部署目标是腾讯云集中式服务，但服务器操作系统暂未决定；
- MySQL 必须保存最终任务状态，Redis 不能成为业务真相来源；
- 共享 ASR 与多语言子任务需要可恢复、可重试和可横向扩展。

## 决策

首版使用独立的 `python -m app.worker` 进程轮询 MySQL 状态机，并用带 TTL 的 Redis 所有权租约防止多个 Worker 同时处理同一项目或语言任务。

每个外部调用和 FFmpeg 步骤都在数据库事务外执行；阶段结果、任务事件、供应商用量和费用在短事务中落 MySQL。Redis 仅保存工作租约、进度缓存和认证会话。Worker 崩溃后，下一实例根据 MySQL 阶段继续处理。

## 备选方案

### Celery + Redis Broker

Celery 提供成熟的队列、重试和调度能力，但会让本地 Windows/Redis 3.2 环境增加额外兼容与运维成本。当前任务规模不需要在首版引入第二套任务真相和结果后端，因此暂不采用。

### FastAPI BackgroundTasks

该机制与 API 进程生命周期绑定，进程重启会丢失未完成工作，也不适合耗时音视频处理，因此不采用。

## 影响

- API、Worker 和 Vue 必须作为独立进程运行。
- 轮询间隔决定空闲任务的启动延迟，默认 2 秒。
- 多 Worker 可以共享 MySQL/Redis 水平扩展；生产租约 TTL、续租和任务超时需要按允许的视频时长配置。
- 正式环境仍须升级到 Redis 7.2+ 并验证认证、持久化和故障恢复。
- 如果后续吞吐量或队列优先级需求显著提高，可以新增 ADR 将调度层迁移到 Celery；MySQL 状态机与幂等阶段仍保留。
