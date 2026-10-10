# 供应商配置与故障排查

本文对应管理端“接口配置”。模型、价格和可用区域会随供应商调整；下表记录的是当前代码预设，实际开通情况以供应商控制台为准。

## 1. 配置原则

1. 先在供应商控制台完成实名认证、服务开通、模型授权和余额准备。
2. 在管理端创建配置，密钥只填写在“API Key/应用密钥”字段。
3. `options` 仅保存轮询地址、资源 ID、音色、模型档位等非敏感参数。
4. 保存后点击“检查”。只有 `CONNECTED` 才表示远程鉴权和最小调用通过。
5. 配置价格规则后再投入生产，否则用量会被记录，但费用可能显示为未配置或 0。

“已启用”仅控制是否参与任务路由，不等价于远程可用。

## 2. 当前预设

### 2.1 豆包录音文件识别

| 字段 | 值/说明 |
| --- | --- |
| `providerCode` | `doubao_asr` |
| 模型 | `bigmodel` |
| 提交地址 | `https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit` |
| 查询地址 | `https://openspeech.bytedance.com/api/v3/auc/bigmodel/query` |
| 资源 ID | 默认 `volc.seedasr.auc`，必须与控制台实际授权一致 |
| 密钥 | 豆包语音控制台创建的 API Key |

系统使用 `X-Api-Key`、`X-Api-Resource-Id` 和请求 ID 请求新语音接口。资源未授权通常返回 `PROVIDER_RESOURCE_NOT_GRANTED`，不是账户余额问题。

### 2.2 火山方舟文本翻译

| 字段 | 值/说明 |
| --- | --- |
| `providerCode` | `ark` |
| 地址 | `https://ark.cn-beijing.volces.com/api/v3/chat/completions` |
| 模型名称 | 控制台已开通、可调用的模型 ID |
| 密钥 | 方舟 API Key |

文本模型必须支持当前区域和账号。保存模型展示名但实际未开通调用权限，仍会在运行时失败。

### 2.3 MiniMax 异步语音合成

| 字段 | 值/说明 |
| --- | --- |
| `providerCode` | `minimax` |
| 提交地址 | `https://api.minimax.cn/v1/t2a_async_v2` |
| 查询地址 | `https://api.minimax.cn/v1/query/t2a_async_query_v2` |
| 下载地址 | `https://api.minimax.cn/v1/files/retrieve_content` |
| 语言增强 | 通常为 `auto` |
| 默认音色 ID | 填账号可用的音色，例如控制台提供的系统音色 ID |
| 密钥 | **按量付费 API Key（通常 `sk-api-...`）** |

订阅套餐的 `sk-cp-...` Key 只用于 Token Plan/积分调用，不能替代按量付费 TTS API Key。二者混用时常见表现是提交接口返回错误，随后系统显示“语音任务响应无效”。

### 2.4 有道大模型同声传译

| 字段 | 值/说明 |
| --- | --- |
| `providerCode` | `youdao_si` |
| 地址 | `wss://openapi.youdao.com/stream-audio/stream-si` |
| 模型 | `youdao-simultaneous-interpretation` |
| 应用 ID | 写入扩展字段 `app_key` |
| 应用密钥 | 写入密钥字段 |
| 音色 | `female` 或 `male` |

有道控制台必须把“大模型同传”服务绑定到同一个应用。错误 `110` 通常表示服务未开通或未绑定；`108/202` 通常与鉴权信息有关。

当前“智能翻译”路径使用有道返回的识别文本、目标译文和时间轴；最终配音继续调用已配置的 MiniMax TTS，以便与专业精译共享音色和声画合成逻辑。

### 2.5 图片生成

| 字段 | 值/说明 |
| --- | --- |
| `providerCode` | `seedream` |
| 地址 | `https://ark.cn-beijing.volces.com/api/v3/images/generations` |
| 默认模型 | `doubao-seedream-5-0-260128` |
| 密钥 | 方舟 API Key |

模型版本可能调整，请以方舟控制台可调用的模型 ID 为准。企业资质和模型规则会影响水印、参考图和内容审核结果。

### 2.6 画面字幕识别

| 字段 | 值/说明 |
| --- | --- |
| `providerCode` | `ark_vision` |
| 地址 | `https://ark.cn-beijing.volces.com/api/v3/chat/completions` |
| 默认模型 | `doubao-seed-2-0-lite-260428` |
| 密钥 | 方舟 API Key |

该能力读取抽帧图片中的画面字幕。它不是传统音频 ASR；视频没有稳定字幕带时，可能返回“未识别到字幕”。

### 2.7 图生视频

| 字段 | 值/说明 |
| --- | --- |
| `providerCode` | `seedance_video` |
| 任务地址 | `https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks` |
| 标准版 | `doubao-seedance-2-0-260128` |
| 快速版 | `doubao-seedance-2-0-fast-260128` |
| 轻量版 | `doubao-seedance-2-0-mini-260615` |
| 密钥 | 方舟 API Key |

当前产品提供 5/10/15 秒、480P/720P 和三个模型档位。参考图将作为首帧上传。真人肖像、未授权人物、敏感内容或不符合内容规范的素材可能被供应商拒绝；这与账户余额是两套独立检查。

“检查”会创建一个最小任务并尝试立即删除。远程任务已经进入执行阶段时，供应商可能不允许删除，并可能产生极少量费用。

## 3. 通用错误码

| 错误码 | 含义 | 优先排查 |
| --- | --- | --- |
| `PROVIDER_AUTH_FAILED` | 401/403 或鉴权失败 | Key 类型、是否复制完整、应用/项目归属、Key 是否被禁用 |
| `PROVIDER_RESOURCE_NOT_GRANTED` | 语音资源未授权 | 控制台已开通资源与 `resource_id` 是否一致 |
| `PROVIDER_RATE_LIMITED` | 请求被限流 | QPS、并发、日配额，稍后重试 |
| `PROVIDER_TIMEOUT` | 建连、提交、轮询或下载超时 | 网络、地址、超时时间、供应商状态 |
| `PROVIDER_HTTP_ERROR` | 供应商返回非预期 HTTP 错误 | 操作日志、模型权限、参数、区域、内容审核、供应商公告 |
| `PROVIDER_RESPONSE_INVALID` | HTTP 成功但响应结构或必需字段不符合预期 | Key 是否属于错误产品、模型/接口是否匹配、供应商 API 是否改版 |
| `PROVIDER_JOB_FAILED` | 异步任务远程执行失败 | 内容安全、模型参数、远程任务详情、素材规范 |
| `PROVIDER_REJECTED` | 供应商明确拒绝请求 | 权限、资源 ID、参数和内容安全策略 |
| `PROVIDER_CONFIG_INVALID` | 本地扩展配置不完整 | 查询/下载地址、默认音色、三个视频模型 ID |

## 4. `PROVIDER_HTTP_ERROR` 与余额的关系

`PROVIDER_HTTP_ERROR` 只说明远程服务器返回了非成功状态，余额充足并不能排除以下原因：

- 模型尚未开通、区域不一致或 Key 没有该模型权限；
- 请求参数不受当前模型版本支持；
- 真人肖像或素材触发内容安全策略；
- 配额、QPS、并发或账号风控限制；
- 供应商接口临时故障。

排查顺序：先查看管理端操作日志和任务时间 → 在供应商控制台按时间查请求/任务 → 用同一个 Key 对目标模型执行官方最小示例 → 再核对本系统端点与模型 ID。

## 5. `PROVIDER_RESPONSE_INVALID` 的典型原因

系统已经收到响应，但没有拿到代码需要的字段。例如：

- TTS 提交结果没有整数 `task_id`；
- 视频生成结果没有字符串任务 `id`；
- 识别结果没有分段时间轴；
- 下载接口返回的不是有效 MP3/MP4；
- 使用了订阅套餐 Key 调用按量付费接口，返回的是另一种错误结构。

不要反复盲目重试。先确认“Key 类型、接口产品、模型 ID”三者属于同一套服务。

## 6. 上线前检查单

- [ ] 七类能力中，实际需要的配置均已创建、启用并通过“检查”。
- [ ] API Key、应用 ID、资源 ID 和模型属于同一账号/项目/区域。
- [ ] 价格规则的计量单位和供应商账单一致。
- [ ] 用 5～15 秒、无敏感内容的素材分别完成最小端到端测试。
- [ ] 翻译成片无中文原声，配音与画面时间轴基本同步。
- [ ] SRT 是目标语言，在线外挂字幕可正常显示。
- [ ] 图生视频测试素材不含未经授权的真人肖像。
- [ ] 失败日志不包含密钥、完整响应凭据或用户隐私数据。
