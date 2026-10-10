# 寰语智能视频全球化内部平台设计规格

- 日期：2026-09-01
- 状态：已由用户确认
- 产品形态：公司内部 Web 系统
- 部署地域：中国大陆

## 1. 目标与问题定义

为公司运营同事建设一个内部 AI 视频翻译生产平台。运营人员上传中文视频，选择一个或多个目标语言，系统异步完成语音识别、文本翻译、语音合成和视频渲染，并提供结果预览、下载及历史记录。管理员负责内部账号、全局任务、AI 供应商、API 密钥、调用费用和审计日志。

目标用户只有两类：

1. 运营人员：创建翻译任务、跟踪进度、查看自己的历史记录、下载结果。
2. 管理员：管理内部账号和权限、查看全部任务、切换 AI API、查看调用成本及审计日志。

首版是单公司、内部使用系统，不开放员工自助注册，不包含套餐、余额、订单和支付。所有员工必须登录；账号由管理员创建。

## 2. 已确认的产品边界

### 2.1 首版包含

- 独立登录页，无注册链接。
- 管理员创建运营账号，并签发临时密码。
- 首次登录强制修改临时密码。
- 运营工作台：上传视频、配置翻译、查看进度、查看记录、预览和下载结果。
- 管理后台：数据看板、账号管理、任务管理、API 管理、费用中心、日志中心。
- 中文源视频输入。
- 英语、日语、韩语、越南语、马来语、泰语、新加坡英语和菲律宾语输出。
- 一次提交多个目标语言，每种语言作为独立子任务处理。
- MP4 成片及 SRT 字幕输出。
- 任务失败重试、取消请求和部分成功展示。
- AI 供应商配置的测试、启停、切换、版本追踪和回滚。
- 按员工、任务、语言、供应商、模型和时间统计费用。
- 操作审计、任务事件、AI 调用记录和结构化系统日志。

### 2.2 首版不包含

- 开放注册、短信登录、第三方登录。
- 套餐、余额、订单、发票和支付。
- 多公司租户和部门级数据隔离。
- 移动端 App。
- 实时直播翻译。
- 数字人口型同步。
- 默认声音克隆。
- 复杂审批流和多人协作编辑字幕。
- 对外开放 API。
- 微服务拆分和 Kubernetes。

### 2.3 语言编码

| 显示名称 | 语言编码 | 首版语音说明 |
| --- | --- | --- |
| 英语 | `en-US` | 通用美式英语音色 |
| 日语 | `ja-JP` | 日语音色 |
| 韩语 | `ko-KR` | 韩语音色 |
| 越南语 | `vi-VN` | 越南语音色 |
| 马来语 | `ms-MY` | 马来西亚马来语音色 |
| 泰语 | `th-TH` | 泰语音色 |
| 新加坡英语 | `en-SG` | 文本按新加坡英语本地化；首版使用通用英语音色，不承诺特定新加坡口音 |
| 菲律宾语 | `fil-PH` | Filipino 音色 |

## 3. 推荐总体架构

首版采用单仓库、单 Vue 应用、模块化 FastAPI 后端和独立 Celery Worker。前端通过两个受权限保护的布局形成员工工作台和管理后台，不建立两套重复代码库。

```text
Browser
  -> Nginx / HTTPS
    -> Vue SPA
       -> /login
       -> /workbench/*
       -> /admin/*
    -> FastAPI /api/v1
       -> Auth and RBAC
       -> Project and Task API
       -> Provider and Cost API
       -> Audit API
    -> Celery Workers
       -> AI queue
       -> Media queue
       -> Render queue
    -> MySQL 8.0
    -> Redis
    -> Volcano Engine TOS or compatible mainland object storage
    -> Doubao ASR and Ark text model
    -> MiniMax TTS, with optional Doubao TTS fallback
    -> FFmpeg server-side processing
```

### 3.1 采用模块化单体的原因

- 首版团队和用户规模不需要微服务复杂度。
- 账号、任务、费用和审计需要强一致的业务边界。
- API 和 Worker 可以独立扩容，但共享领域模型。
- 后续如渲染吞吐成为瓶颈，可以先拆 Worker，不需要重写业务 API。

## 4. 技术栈基线

版本为 2026-09-01 从官方文档和包注册表核对的生产兼容基线；当某个最新主版本尚未被配套工具支持时，采用满足完整 peer dependency 的最新稳定版本。实施时写入锁文件，升级必须通过测试和变更评审。

### 4.1 前端

| 技术 | 版本基线 | 用途 |
| --- | --- | --- |
| Node.js | 24 LTS | 构建运行时 |
| Vue | 3.5.42 | SPA 框架 |
| Vite | 8.2.2 | 开发和生产构建 |
| TypeScript | 6.0.3 | 静态类型；满足 typescript-eslint 8.69.0 的 `<6.1.0` peer 范围 |
| Vue Router | 5.3.0 | 登录、工作台和后台路由 |
| Pinia | 4.0.3 | 会话和少量跨页面状态 |
| Tailwind CSS | 4.3.3 | 设计令牌和样式 |
| Reka UI | 2.10.4 | 无样式、可访问的 Vue UI 原语 |
| Vitest | 4.1.11 | 单元和组件测试 |
| Playwright | 1.62.1 | 浏览器端到端测试 |

Vite 8 要求 Node.js 20.19+ 或 22.12+；使用 Node.js 24 LTS 满足要求。Creative Tim UI 资料是 React/shadcn 实现，首版不复制其 React 组件，仅继承其设计哲学、视觉规则和组件组合原则，在 Vue 中使用 Reka UI 与本地组件实现。

### 4.2 后端

| 技术 | 版本基线 | 用途 |
| --- | --- | --- |
| Python | 3.13 | 服务端运行时 |
| FastAPI | 0.141.1 | REST API 和 OpenAPI |
| Pydantic | 2.13.5 | 请求、响应和外部 API 校验 |
| SQLAlchemy | 2.0.52 | 数据访问和显式查询 |
| Alembic | 1.19.1 | 数据库迁移 |
| uv | 0.12.8 | Python 通用锁文件与精确环境同步 |
| Celery | 5.6.3 | 可重试的分布式后台任务 |
| redis-py | 8.1.0 | Redis 客户端 |
| Uvicorn | 0.52.4 | ASGI 服务 |
| pytest | 9.1.1 | 后端测试 |
| FFmpeg | 发布时锁定具体构建 | 音视频提取、混音、字幕和成片 |

Celery 5.6 支持 Python 3.13。视频处理属于重型、长耗时工作，不使用 FastAPI 进程内 `BackgroundTasks` 执行。

### 4.3 数据和基础设施

- MySQL 8.0.45，InnoDB，`utf8mb4`，默认排序规则 `utf8mb4_0900_ai_ci`。
- Redis 用于服务端会话、Celery broker、幂等锁、限流、进度和短期缓存。
- Redis 生产实例采用 `noeviction`，所有非持久键必须设置 TTL，并监控内存和队列深度。
- 对象存储 Bucket 必须为私有，使用短时签名 URL 上传和下载。
- 本地开发使用现有原生 MySQL 8.0.45 和 Redis 3.2.100，不依赖 Docker；本地 Redis 连接固定使用 RESP2。
- Redis 3.2.100 仅用于本地兼容开发。正式环境必须升级到 Redis 7.2 或更高版本，并通过真实集成、持久化、认证和故障恢复验证。
- 腾讯云服务器操作系统和部署拓扑在独立上线计划中决定，本阶段不预设 Linux、Windows或容器方案。

## 5. 前端信息架构与页面设计

### 5.1 路由

```text
/login
/change-password
/workbench/new
/workbench/records
/workbench/records/:projectId
/admin/dashboard
/admin/accounts
/admin/tasks
/admin/providers
/admin/costs
/admin/logs
```

未登录访问受保护路由时统一跳转 `/login`。运营账号访问 `/admin/*` 返回 403 页面；管理员可以访问工作台和后台。

### 5.2 登录页

- 中性浅色背景和居中登录卡片，橙色作为主操作色。
- 展示产品名称、内部系统标识、用户名、密码、显示密码按钮和登录按钮。
- 不展示注册链接、套餐或营销内容。
- 辅助文案为“账号由管理员统一创建，如无法登录请联系管理员”。
- 错误统一显示“用户名或密码错误”，不泄露账号是否存在。
- 登录请求期间禁止重复提交，并展示明确加载状态。
- 临时密码登录成功后强制跳转 `/change-password`。
- 支持键盘完整操作、可见焦点、表单标签和 `aria-live` 错误提示。

### 5.3 员工工作台

默认进入“新建翻译”，以完成任务为中心，不做装饰性大盘。

新建翻译页包含：

- 拖拽和选择上传区域。
- 文件格式、大小、时长限制提示。
- 中文源语言固定展示。
- 多选目标语言。
- 每种语言的音色选择。
- 是否保留原声、原声音量、是否烧录字幕。
- 费用预估、预计输出数量。
- 提交按钮及上传进度。

记录列表包含：

- 文件名称、目标语言、创建时间、任务状态、进度、创建人和总费用。
- 运营人员只看自己的记录；管理员可以看全部记录。
- 使用游标分页，支持按状态、语言和时间筛选。
- 状态不能只靠颜色，同时显示图标和文本。

详情页包含：

- 源视频信息和目标语言子任务。
- 阶段进度、耗时、失败原因和重试入口。
- 成片预览、视频下载和 SRT 下载。
- 部分语言成功时明确展示成功和失败项。

### 5.4 管理后台

- 数据看板：任务量、成功率、队列积压、视频分钟数、当日和当月成本、供应商健康状态。
- 账号管理：新增、编辑、角色调整、重置密码、启用和停用；不提供物理删除。
- 任务管理：全局筛选、详情、取消请求、失败重试和阶段事件。
- API 管理：供应商、能力、模型、语言覆盖、优先级、密钥、连接测试、启停和版本历史。
- 费用中心：按时间、员工、任务、语言、能力、供应商和模型聚合。
- 日志中心：操作审计、任务事件和 API 调用；系统内部堆栈不直接展示。

### 5.5 UI 设计约束

- 遵循 Creative Tim 的 95% 原则和 Light 原则，优先完成高频任务。
- 主色为橙色；成功、警告、错误、进行中分别使用 emerald、amber、red、blue。
- 禁止紫色 AI 模板风、无意义渐变、过量阴影和全部大圆角。
- 正文至少使用 `text-sm`；`text-xs` 仅用于徽标、时间戳和次要元信息。
- 使用 Tailwind 标准尺度和断点，禁止任意像素值及内联样式。
- 内容卡片采用统一 Card/Header/Content 结构；可溢出列表使用可访问滚动区域。
- 必须实现加载、空、失败、无权限和过期文件状态。
- 响应式测试宽度：320、768、1024、1440 像素。
- 达到 WCAG 2.1 AA，正文对比度至少 4.5:1，移动端触控目标至少 44 x 44 像素。

## 6. 认证、账号与权限

### 6.1 认证方式

- 使用服务端会话，不把 JWT 或登录令牌写入 `localStorage`。
- 浏览器只保存 `HttpOnly`、`Secure`、`SameSite=Lax` 的会话 Cookie。
- 会话状态存储在 Redis，空闲 8 小时失效，绝对有效期 24 小时。
- 所有写请求使用会话绑定的 CSRF Token。
- 密码使用 Argon2id 哈希。
- 单账号 15 分钟内连续失败 5 次后临时锁定。
- 会话保存账号认证版本；每个受保护请求同时校验账号启用状态和认证版本。
- 登出、停用账号或重置密码后，服务端主动撤销该账号全部会话并递增认证版本；即使 Redis 清理暂时失败，旧会话也会在下一次请求时失效。

### 6.2 角色

| 能力 | 运营人员 | 管理员 |
| --- | --- | --- |
| 创建翻译任务 | 允许 | 允许 |
| 查看自己的记录 | 允许 | 允许 |
| 查看全部记录 | 禁止 | 允许 |
| 重试自己的失败任务 | 允许 | 允许 |
| 管理账号 | 禁止 | 允许 |
| 修改 API 配置 | 禁止 | 允许 |
| 查看费用和审计 | 禁止 | 允许 |

系统必须保证至少存在一个启用的管理员；最后一个管理员不能被停用或降级。首次管理员通过受控命令创建，不使用公开初始化接口。

## 7. 视频翻译业务流程

### 7.1 上传

1. 前端请求上传初始化接口。
2. 后端校验文件名、大小、声明类型和用户权限，创建项目、私有对象 Key 和最长 24 小时的分片上传会话。
3. 前端按分片请求 15 分钟有效的对象存储签名地址，支持断点续传和失败分片重试。
4. 浏览器直接上传对象存储，不让大文件穿过 FastAPI。
5. 前端提交分片清单完成上传；后端通过对象存储 `HEAD` 再次确认对象存在、大小正确、已完成且属于当前账号。
6. 源文件先进入私有隔离前缀，Worker 计算 SHA-256，并使用 `ffprobe` 验证真实容器、编码、时长和音视频流；验证通过后才允许进入 AI 处理队列。

首版默认限制：单文件不超过 2 GB，时长不超过 120 分钟；支持 MP4、MOV、MKV 输入，统一输出 H.264/AAC MP4。

### 7.2 多语言任务

一次提交创建一个翻译项目和多个语言子任务。视频校验、音频提取和中文 ASR 属于项目级共享阶段，只执行一次；识别成功后再向多个语言子任务分流，避免重复识别和重复计费。每个语言子任务独立翻译、合成、渲染、计费和重试，项目状态由共享阶段和语言子任务共同聚合。

```text
Project
  DRAFT
  -> UPLOADING
  -> VALIDATING
  -> EXTRACTING_AUDIO
  -> RECOGNIZING

Language task
  QUEUED
  -> TRANSLATING
  -> SYNTHESIZING
  -> RENDERING
  -> SUCCEEDED
  -> FAILED
  -> CANCELLED
```

项目终态包括 `SUCCEEDED`、`PARTIALLY_SUCCEEDED`、`FAILED` 和 `CANCELLED`。`PARTIALLY_SUCCEEDED` 表示至少一个目标语言成功且至少一个失败；共享源阶段失败时，尚未开始的语言子任务统一终止，并引用同一个项目级失败事件。

### 7.3 AI 和媒体链路

1. FFmpeg 提取统一采样率的单声道音频。
2. 豆包录音文件 ASR 生成中文文本、分段时间轴和置信信息。
3. 豆包方舟文本模型按字幕段落和上下文翻译。
4. 首版 MiniMax TTS 作为覆盖全部目标语言的主供应商；豆包 TTS 可作为支持语种的备用适配器。
5. Worker 按时间轴切分、调速和插入静音，避免整段音频累计漂移。
6. FFmpeg 混合配音和可选原声，生成 SRT，并按配置烧录字幕。
7. 成片和字幕写入私有对象存储。

首版不做口型同步。新加坡英语只保证文本本地化，不保证新加坡特定口音。

### 7.4 重试与幂等

- 创建项目接口接受幂等键，重复提交不创建重复任务。
- 共享阶段以项目和阶段组成幂等键；语言阶段以项目、语言和阶段组成幂等键，成功产物可复用。
- 外部 API 超时采用指数退避，单阶段最多自动重试 3 次。
- 无效视频、鉴权失败、配额不足和不支持语言不自动重试。
- Worker 使用软超时和硬超时；媒体处理必须限制 CPU、内存、磁盘和运行时间。
- 用户取消后设置 `CANCEL_REQUESTED`，Worker 在阶段边界安全停止；不能强行中断正在写文件的步骤。
- 任务进度由 Redis 提供快速读取，MySQL 保存阶段最终状态和事件。
- 前端使用 3 秒轮询，不在首版引入 WebSocket。

## 8. API 和模块契约

### 8.1 API 约定

- 所有业务 API 使用 `/api/v1` 前缀。
- URL 使用复数名词，不在路径中使用 `create`、`get` 等动词。
- JSON 字段使用 camelCase，Python 和数据库内部使用 snake_case。
- 列表接口必须分页；记录列表默认使用基于 `id` 的游标分页。
- 所有请求和响应使用 Pydantic 模型，第三方响应也必须校验后使用。
- 错误响应统一为：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求参数不正确",
    "requestId": "01K43HDTQ2P8X6MZ0V7C9N1R4S",
    "details": {}
  }
}
```

生产响应不包含数据库错误、供应商密钥、内部路径或堆栈。

### 8.2 主要端点

```text
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
GET    /api/v1/auth/me
POST   /api/v1/auth/password

POST   /api/v1/projects/uploads
POST   /api/v1/projects/uploads/:uploadId/parts
POST   /api/v1/projects/uploads/:uploadId/complete
POST   /api/v1/projects
GET    /api/v1/projects
GET    /api/v1/projects/:projectId
POST   /api/v1/projects/:projectId/cancel
POST   /api/v1/tasks/:taskId/retry

GET    /api/v1/admin/accounts
POST   /api/v1/admin/accounts
PATCH  /api/v1/admin/accounts/:accountId
POST   /api/v1/admin/accounts/:accountId/reset-password
POST   /api/v1/admin/accounts/:accountId/sessions/revoke

GET    /api/v1/admin/providers
POST   /api/v1/admin/providers
PATCH  /api/v1/admin/providers/:providerId
POST   /api/v1/admin/providers/:providerId/test
POST   /api/v1/admin/providers/:providerId/activate

GET    /api/v1/admin/costs/summary
GET    /api/v1/admin/costs/records
GET    /api/v1/admin/logs/audit
GET    /api/v1/admin/logs/tasks
GET    /api/v1/admin/logs/provider-calls
```

### 8.3 后端模块

```text
auth       -> 登录、会话、密码和 RBAC
account    -> 内部账号生命周期
project    -> 视频项目、上传和记录
workflow   -> 状态机、编排、重试和取消
provider   -> ASR、翻译、TTS 统一适配器与路由
media      -> FFmpeg、ffprobe、临时文件和对象存储
cost       -> 价格版本、用量和费用聚合
audit      -> 操作审计和业务事件
worker     -> Celery 任务与队列
```

## 9. API 供应商管理

供应商配置不是一个可随意覆盖的字符串，而是版本化的生产配置。

- 每个供应商声明能力：ASR、TRANSLATION 或 TTS。
- 配置包括模型、服务区域、语言覆盖、优先级、超时、重试策略和费用规则。
- 密钥使用 AES-256-GCM 加密后写入数据库，主加密密钥只通过生产环境 Secret 注入，不与数据库同存。
- 前端只显示密钥后四位；保存后不能读取明文，只能覆盖。
- 新配置必须通过连接测试后才能启用。
- 激活新版本只影响后续任务；运行中的任务保存并继续使用创建时的配置版本。
- 自动降级只在能力、语言和质量等级匹配时发生。
- 切换、测试、启停、失败降级和密钥更新全部写审计日志。
- 最后一个可用的关键能力供应商不能停用。

## 10. 费用和用量设计

每次外部调用写入不可变用量记录，失败调用也要记录，以识别重试损耗。ASR 用量归属项目且语言子任务为空；翻译和 TTS 用量同时关联项目与语言子任务。项目汇总成本时只计算一次共享 ASR 成本，不在各语言中重复摊入。

### 10.1 计费维度

- ASR：音频秒数或供应商返回的计费时长。
- 文本翻译：输入和输出 Token。
- TTS：计费字符数。
- FFmpeg：内部计算资源，不计入外部 API 费用，但记录处理时长。

### 10.2 费用精度

费用使用 `BIGINT` 保存“微元”，即一元等于 1,000,000 微元，避免浮点误差并支持低于一分钱的单次调用。用量记录保存价格版本和当次单价快照，后续修改价格不能改变历史成本。

### 10.3 管理报表

- 今日和本月总费用。
- 每分钟视频平均成本。
- 按供应商、模型、能力、语言、员工和任务统计。
- 失败和重试费用。
- 预估费用与实际费用差异。
- 数据导出为 CSV。

## 11. MySQL 数据模型

### 11.1 核心表

| 表 | 作用 | 关键索引方向 |
| --- | --- | --- |
| `user_account` | 账号、角色、状态、密码 | 登录名唯一、状态和创建时间 |
| `translation_project` | 一次视频翻译项目 | 创建人和创建时间、项目状态 |
| `translation_task` | 单个目标语言任务 | 项目、语言、状态、创建时间 |
| `media_asset` | 源文件、中间文件和输出文件元数据 | 项目、任务、资产类型 |
| `source_segment` | 共享中文原文、开始和结束时间、置信度 | 项目和片段序号唯一 |
| `subtitle_segment` | 单语言译文及对应源片段 | 任务和源片段唯一 |
| `task_event` | 任务阶段事件和可展示错误 | 任务和创建时间 |
| `provider_config` | 供应商逻辑配置 | 能力、状态和优先级 |
| `provider_version` | 模型、端点、超时和密钥版本 | 供应商和版本号唯一 |
| `provider_price` | 生效时间范围内的计价规则 | 供应商、模型、能力和生效时间 |
| `ai_usage_record` | 每次 AI 调用用量和成本 | 项目、可空任务、供应商、时间和状态 |
| `audit_log` | 管理员和安全敏感操作 | 操作人、动作、资源和时间 |

### 11.2 数据库规范决议

- 表名和字段名使用小写 snake_case、单数、可理解名称且不超过 32 个字符。
- 每表使用 `BIGINT AUTO_INCREMENT` 的 `id` 主键，另设不可猜测的 `public_id CHAR(26)` 唯一索引用于 API。
- 使用 InnoDB，显式 `utf8mb4`，所有表和字段带注释。
- 使用 `DATETIME(3)` 保存 UTC 时间，避免 MySQL `TIMESTAMP` 的 2038 年范围限制。
- IP 地址如需保存，使用 `VARBINARY(16)` 和 `INET6_ATON` / `INET6_NTOA`，不使用只支持 IPv4 的普通 `INT`。
- 状态字段使用 `TINYINT` 和应用常量，关键范围使用 MySQL 8.0 `CHECK` 约束。
- 按所给规范中更严格的线上条款执行：只定义逻辑外键及索引，不建立物理外键约束；服务层事务和测试保证一致性。
- 不在 MySQL 保存视频、音频和图片二进制，只保存私有对象 Key、哈希、大小、格式和时长。
- `SELECT` 和 `INSERT` 必须显式列名，禁止 `SELECT *`。
- 所有查询参数化，禁止拼接用户输入；SQLAlchemy 可以使用，但必须检查生成 SQL、避免 N+1，并为关键查询保留显式 Core 查询。
- 外部 API 调用和 FFmpeg 处理不得放在数据库事务内。
- 更新按主键或唯一键进行，事务内 SQL 不超过 5 条，保持一致的锁顺序。
- 记录列表使用游标分页，避免大偏移量 `LIMIT offset`。
- 超过 100 万行的表变更和大索引操作必须先评估在线 DDL、备份和回滚方案。
- 原始 MySQL 错误只写脱敏内部日志，不返回前端。

## 12. Redis 设计

Redis 不是业务真相来源。MySQL 保存最终任务状态、账号、费用和审计；Redis 只提供低延迟协调。

- 会话：`session:{sessionId}`，TTL 8 小时并受绝对过期时间约束。
- 登录限流：`login-limit:{loginName}:{window}`。
- 项目进度：`progress:{projectId}`，TTL 24 小时。
- 幂等键：`idempotency:{accountId}:{key}`，TTL 24 小时。
- 分布式锁：`lock:task:{taskId}:{stage}`，必须设置所有者和自动过期。
- Celery broker 使用独立命名空间，不与缓存 Key 混淆。
- 生产采用 TLS、认证、私网访问、内存告警和持久化配置。

## 13. 文件、安全与数据生命周期

- Bucket 私有，上传和下载 URL 默认 15 分钟过期。
- 后端生成对象 Key，不直接使用用户文件名作为文件路径。
- 校验扩展名、MIME、Magic Bytes、容器、Codec、大小和时长。
- FFmpeg 通过参数数组调用，禁止把文件名拼入 Shell 命令。
- 每个任务使用独立临时目录，完成或失败后清理。
- Worker 使用非 root 用户，并限制 CPU、内存、磁盘和运行时长。
- 中间音频默认 24 小时删除；源视频和输出默认保留 90 天；业务元数据、费用和审计默认保留 3 年。保留期由管理员配置，但修改只影响新对象。
- 下载必须验证账号和资源权限；运营人员不能通过猜测 ID 查看其他人的文件。
- API 密钥、密码、会话、完整请求正文和视频内容不得写日志。
- 如果系统通过中国大陆公网域名访问，上线前完成 ICP 备案、HTTPS 证书和公司隐私/版权使用规则确认。

## 14. 日志、指标和告警

### 14.1 日志分类

- 审计日志：谁在何时修改了账号、角色、API、价格和任务。
- 任务事件：任务进入或退出哪个阶段、耗时和可展示失败代码。
- AI 调用记录：供应商、模型、能力、用量、耗时、错误码和费用。
- 系统日志：JSON 结构化日志，进入日志平台，不直接完整展示给管理员。

所有 HTTP 请求生成 `requestId`，翻译项目生成 `projectId`，子任务生成 `taskId`。这些标识通过 API、Celery 消息和外部调用日志贯穿全链路。

### 14.2 指标

- API：请求率、错误率、p50/p95/p99 时延。
- Worker：队列深度、最老任务等待时间、阶段耗时、失败率和重试率。
- 供应商：成功率、超时率、p95 时延、用量和费用。
- 数据库：连接池、慢查询、锁等待和存储增长。
- 前端：LCP、INP、CLS 和 JavaScript 错误。

告警优先面向用户症状：任务连续失败、供应商错误率升高、队列等待过长、费用异常增长和对象存储失败。每条告警必须链接处理手册。

## 15. 错误处理

| 场景 | 用户行为 | 系统行为 |
| --- | --- | --- |
| 用户名或密码错误 | 显示统一错误 | 记录安全事件并限流 |
| 上传格式不支持 | 阻止提交并说明格式 | 不创建翻译任务 |
| 视频校验失败 | 详情页显示无法处理 | 清理中间文件，不自动重试 |
| AI 服务超时 | 显示重试中 | 指数退避，最多 3 次 |
| API 密钥失效 | 显示服务暂不可用 | 停止自动重试并告警管理员 |
| 单语言失败 | 其他语言继续 | 项目标记部分成功 |
| 渲染失败 | 保留上游产物 | 只重试渲染阶段 |
| 费用超过预估阈值 | 暂停后续调用 | 标记待管理员处理并告警 |
| 用户取消任务 | 显示取消中 | 在安全阶段边界停止 |

## 16. 测试策略

### 16.1 前端

- Vitest：组合函数、权限判断、表单校验、费用格式化和状态映射。
- Vue Test Utils：登录表单、上传表单、任务状态、API 配置和费用筛选组件。
- Playwright：登录、强制改密、创建任务、查看记录、管理员建号、切换 API 和查看费用。
- axe / Lighthouse：无障碍和 Core Web Vitals。

### 16.2 后端

- 单元测试：状态机、权限、计费、重试、路由和配置版本。
- 集成测试：FastAPI、MySQL、Redis、对象存储适配器和 Celery eager 模式。
- 契约测试：豆包和 MiniMax 请求/响应模型，使用官方沙箱或录制的脱敏 Fixture。
- 媒体测试：短小合法和损坏视频 Fixture，验证音频提取、字幕和成片。
- 安全测试：越权、会话撤销、CSRF、上传伪装、限流、密钥掩码和错误脱敏。
- 迁移测试：空库升级、已有数据升级和回滚前置检查。

核心领域服务行覆盖率不低于 80%。测试必须证明失败路径和重试路径，而不只覆盖成功路径。

## 17. 性能和容量目标

- 登录和普通 CRUD API：p95 小于 300 ms，不含外部服务调用。
- 创建项目并入队：p95 小于 1 秒。
- 前端任务进度从 Worker 更新到页面可见：不超过 5 秒。
- LCP 不超过 2.5 秒，INP 不超过 200 ms，CLS 不超过 0.1。
- 前端初始 JavaScript gzip 后目标小于 200 KB；管理页按路由懒加载。
- 数据库列表全部分页，禁止无界查询和 N+1。
- Worker 并发按 CPU、内存和供应商 QPS 分开配置；AI 队列和媒体渲染队列隔离。
- 性能优化必须先测量基线，再优化并复测。

## 18. 项目结构

```text
frontend/
  src/
    api/
    components/
    layouts/
    modules/
      auth/
      workbench/
      admin/
    router/
    stores/
    styles/
  tests/
  e2e/

backend/
  app/
    api/v1/
    core/
    modules/
      auth/
      account/
      project/
      workflow/
      provider/
      media/
      cost/
      audit/
    workers/
  migrations/
  tests/

deploy/
  runbooks/                    # 后续腾讯云上线计划确定操作系统和拓扑后创建

docs/
  superpowers/specs/
  adr/

tasks/
  plan.md
  todo.md
```

模块内聚合路由、服务、仓储、Schema 和测试；跨模块只能通过公开服务接口调用，不能跨模块直接操作内部表模型。

## 19. 开发和验证命令

项目脚手架建立后必须提供以下稳定命令：

```bash
# Native local infrastructure
powershell -ExecutionPolicy Bypass -File scripts/check_local_services.ps1

# Frontend
cd frontend
npm ci
npm run dev
npm run lint
npm run type-check
npm run test:unit -- --run
npm run test:e2e
npm run build

# Backend
cd backend
   python -m pip install uv==0.12.8
   python -m uv sync --extra dev --locked
python -m alembic upgrade head
python -m pytest -q
python -m app.cli create-admin
python -m uvicorn app.main:app --reload
python -m celery -A app.workers.celery_app worker --loglevel=INFO
```

## 20. 工程边界

### 20.1 始终执行

- 先更新规格和 API 契约，再修改实现。
- 所有外部输入和第三方响应在边界校验。
- 所有受保护资源同时检查登录状态、角色和资源归属。
- 使用参数化 SQL、显式字段、短事务和必要索引。
- 任务、供应商调用和费用都有结构化日志与关联 ID。
- 每个增量通过测试、Lint、类型检查和运行时验证后再提交。
- 所有依赖锁定版本并记录许可证。

### 20.2 必须先询问

- 新增目标语言或 AI 供应商。
- 更改账号角色、数据可见性和登录策略。
- 更改数据库 Schema、数据保留期和费用精度。
- 新增运行时依赖、修改 CI/CD 或基础设施拓扑。
- 启用声音克隆、口型同步或将视频发送到新的外部服务。
- 上线生产、迁移生产数据和执行不可逆操作。

### 20.3 永远禁止

- 提交真实密码、API Key、Token、证书和生产配置。
- 将登录 Token 放入 `localStorage`。
- 在日志中记录密钥、密码、完整个人信息或视频内容。
- 把用户输入或模型输出直接拼入 SQL、Shell、HTML 或文件路径。
- 绕过权限检查、关闭安全头或使用生产 CORS 通配符。
- 向前端返回数据库原始错误、内部堆栈和供应商密钥。
- 删除失败测试来让流水线通过。
- 未经确认物理删除账号、任务、费用或审计数据。

## 21. 上线策略（后续独立计划）

- 系统集中部署到腾讯云，运营同事只通过浏览器访问，不在员工电脑安装后端、数据库、Redis 或 FFmpeg。
- 腾讯云服务器操作系统、网络、反向代理、进程管理和扩缩容方案尚未决定，本阶段不写入强制实现。
- 环境必须分为本地、测试和生产，配置严格隔离；正式环境 Redis 不得低于 7.2。
- 数据库迁移、备份、灰度、监控、告警和回滚由后续上线计划完整设计并验证。

## 22. 验收标准

1. 管理员可以通过受控命令创建首个管理员并进入登录页。
2. 管理员可以新增运营账号，运营人员用临时密码登录并被强制改密。
3. 页面不存在公开注册入口，未登录和越权请求被正确拒绝。
4. 运营人员可以上传合法中文视频、选择多个目标语言并提交任务。
5. 系统可以生成任务进度、MP4 成片和 SRT 字幕，并处理部分成功。
6. 运营人员只能查看和下载自己的项目；管理员可以查看全部项目。
7. 管理员可以测试、启用和切换 API 配置，运行中任务不受切换影响。
8. 每次 AI 调用都有用量、价格快照、费用、状态和关联任务。
9. 费用中心可以按时间、员工、任务、语言、能力和供应商聚合并导出。
10. 管理员可以查看脱敏的审计、任务和供应商调用日志。
11. 文件、会话、密钥、权限、日志和保留期符合本规格安全边界。
12. 单元、集成、E2E、安全、媒体和迁移测试通过，构建无错误。
13. 测试环境中可通过日志、指标和关联 ID 定位一次人为注入的失败。
14. 生产部署具备健康检查、告警、备份、灰度和回滚说明。

## 23. 主要风险与应对

| 风险 | 应对 |
| --- | --- |
| 小语种音色不自然 | 上线前用固定脚本做八语种人工盲测，供应商适配层允许切换 |
| 翻译音频比原片段长 | 分段翻译、语速约束、静音调整，仍超限时标记人工检查 |
| 供应商限流或故障 | 队列削峰、指数退避、健康状态、备用供应商和管理告警 |
| 重试造成重复计费 | 阶段幂等、供应商请求号、费用记录和最大重试限制 |
| 大文件压垮 API | 浏览器直传对象存储，媒体处理与 API 进程隔离 |
| API 密钥泄漏 | 加密存储、前端掩码、最小权限、审计、轮换和日志脱敏 |
| 历史文件持续增长 | 生命周期删除、中间文件 24 小时、源和输出默认 90 天 |
| 本地 Redis 3.2 被误用于正式环境 | 上线门槛强制 Redis 7.2+，并执行真实集成和故障恢复测试 |

## 24. 决策依据

- Vue 官方 TypeScript 指南：https://vuejs.org/guide/typescript/overview
- Vite 官方入门与 Node.js 要求：https://vite.dev/guide/
- FastAPI 重型后台任务建议：https://fastapi.tiangolo.com/tutorial/background-tasks/
- Celery 5.6 Redis Broker：https://docs.celeryq.dev/en/v5.6.2/getting-started/backends-and-brokers/redis.html
- MySQL 8.0 参考手册：https://dev.mysql.com/doc/refman/8.0/en/
- MySQL `utf8mb4` 与字符集说明：https://dev.mysql.com/doc/refman/8.0/en/charset-unicode-sets.html
- MySQL `DATETIME` 和 `TIMESTAMP` 范围：https://dev.mysql.com/doc/refman/8.0/en/datetime.html
- MySQL IPv4/IPv6 函数：https://dev.mysql.com/doc/refman/8.0/en/miscellaneous-functions.html
- redis-py 支持矩阵：https://github.com/redis/redis-py#supported-redis-versions
- 原生本地依赖与 Redis 升级门槛：`docs/superpowers/specs/2026-09-01-native-local-services-design.md`
- 豆包录音文件识别：https://www.volcengine.com/docs/6561/1354871?lang=zh
- MiniMax 多语种异步 TTS：https://platform.minimaxi.com/docs/guides/speech-t2a-async
- MiniMax 按量计费：https://platform.minimaxi.com/docs/guides/pricing-paygo
- FFmpeg 许可说明：https://ffmpeg.org/legal.html
- uv 锁定与同步：https://docs.astral.sh/uv/concepts/projects/sync/
