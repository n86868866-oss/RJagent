# Research Journey Agent 后端骨架设计

> 文档状态：当前实施约束与演进准则
>
> 修订日期：2026-09-28
>
> 当前代码事实见 [系统架构](ARCHITECTURE.md)

本文回答四个问题：框架提供什么，项目封装什么，封装解决什么问题，以及新增能力应放在哪里。它不重复记录每个配置项和业务算法。

## 1. 设计目标

后端骨架追求以下性质：

- 复用 FastAPI、Pydantic、HTTPStatus 和各 SDK 的现有能力。
- 业务层只编排正确流程与业务规则，不包装所有技术异常。
- 数据和外部服务错误在发现问题的边界直接抛出，由 HTTP 边界统一翻译。
- 同一模型和同一错误文案只定义一次。
- 共享连接按应用生命周期复用，业务服务通过依赖图按请求组装。
- 对外响应小而稳定，内部诊断留在日志与受控健康接口。
- 新增封装必须有明确复用对象或边界问题，不能只为增加目录层次。

## 2. 框架能力与项目封装

| 能力 | 直接复用 | 项目封装 | 解决的问题与影响 |
| --- | --- | --- | --- |
| HTTP 语义 | `http.HTTPStatus` | 中文状态文案、`AppError` | 不维护业务数字码；HTTP 状态与 body code 一致 |
| 路由与校验 | FastAPI、Pydantic | 业务模块拥有的输入/输出模型 | 自动校验、序列化和 OpenAPI；避免 API 与服务重复模型 |
| 依赖注入 | `Depends`、请求缓存、`dependency_overrides` | `api/dependencies.py` 的资源和服务 provider | 明确对象来源、生命周期和测试替换点 |
| 生命周期 | FastAPI lifespan、`AsyncExitStack` | `main.py` 组合根 | 共享长连接，逆序关闭，启动失败直接终止 |
| 响应 | Pydantic 泛型、`JSONResponse` | `ApiResponse[T]` 与构造函数 | JSON 接口统一四字段；204 和重定向保留 HTTP 原义 |
| 异常 | Python 原生异常、SDK 异常、FastAPI handler | 状态映射与安全中文响应 | 业务不重复捕获；内部详情不泄露 |
| 请求追踪 | ContextVar、中间件 | request ID 生成、响应头与日志字段 | 一次请求可跨日志定位 |
| 数据访问 | aiosqlite、Qdrant SDK、pathlib | Store 类 | 封装 SQL、集合结构和路径安全，不承担业务决策 |
| 外部调用 | HTTPX、OpenAI SDK | Client 类 | 封装连接、重试、协议与响应校验 |
| 健康检查 | `asyncio.gather`、`wait_for` | 探针清单、必选策略与公开视图 | readiness 可配置且不会泄露完整内部错误 |

判断是否需要项目封装时，先问：是否存在项目特有策略、协议适配、生命周期或安全边界。如果答案都是否，应直接使用框架或 SDK。

## 3. 层级职责

### 3.1 API 层

允许：

- 声明路径、HTTP 方法、状态码和 `response_model`。
- 使用 `Depends` 获取服务。
- 将 HTTP 输入交给服务，将服务结果放入统一响应。
- 做明确的公开字段投影。

禁止：

- 编写 SQL、文件路径或第三方协议。
- 实现检索、解析、重排和业务判断。
- 捕获通用 `Exception` 后重写错误。
- 为与服务结果完全相同的字段复制一份 schema。

### 3.2 服务层

允许：

- 编排多个 Store/Client。
- 表达论文重名、不存在、引用规则等业务判断。
- 协调跨资源补偿。
- 定义能力所属的输入、输出和领域模型。

禁止：

- 依赖 FastAPI 的 Request、Depends 或 HTTPException。
- 把任意技术错误包装成业务错误。
- 直接读取 `app.state`。
- 为了“统一”吞掉原异常堆栈。

### 3.3 基础设施层

允许：

- 调用数据库、文件系统和外部服务。
- 校验第三方响应格式、向量维度和集合结构。
- 实现有边界的重试与连接复用。
- 抛出原生异常或精确的数据异常。

禁止：

- 决定论文是否允许重复、删除不存在论文应提示什么。
- 构造 API 响应。
- 导入服务或路由。

### 3.4 Core 与 Middleware

`core` 只保存真正跨业务的稳定能力：响应外壳、异常类型、状态文案、异常映射和日志配置。`middleware` 只处理 request ID 与访问日志。

不要重新创建 `codes.py`。状态文案和 `AppError` 在 `core/exceptions.py` 内形成一个小而完整的错误定义单元。

## 4. 模型归属规则

新增模型时依次判断：

1. 它是否只属于一个业务能力？放入该能力的 `models.py` 或 `model.py`。
2. 服务输入/结果是否与 HTTP 契约完全一致？路由直接复用。
3. HTTP 是否必须隐藏内部字段或改变结构？在同一业务模块建立明确的公开投影，并说明裁剪原因。
4. 它是否跨所有业务共享？只有这时才放入 `core`。

当前约定：

```text
services/papers/models.py       论文领域与接口结果
services/chat/model.py          聊天请求、候选与回答
services/health/models.py       健康领域结果与公开视图
core/responses.py               HTTP 通用外层与分页结果
```

不设置空泛的 `api/schemas` 汇总目录。模型位置按所有权决定，而不是按 Pydantic 或 dataclass 技术类型决定。

健康检查保留 `ReadinessData` 投影是合理重复边界：完整 `HealthCheckResult` 含探针、延迟和错误字段，ready 接口只需要 `status/required`，避免扩大公开面。

## 5. 依赖注入与生命周期

### 5.1 生命周期

应用级资源由 lifespan 创建：数据库连接、HTTP 客户端、Qdrant 客户端和可关闭服务。创建成功后写入 `app.state`，并注册到 `AsyncExitStack`。

启动必须完成本地基础资源初始化。远端资源是否阻断启动由其实现和 `HEALTH_REQUIRED_COMPONENTS` 共同决定。关闭顺序与创建顺序相反。

### 5.2 Provider

资源 provider 从 `app.state` 读取对象。缺失资源抛 `ServiceUnavailableError`，它是固定 503 的 `AppError` 子类。

服务 provider 使用嵌套 `Depends`：

```text
get_embedding_client ─┬─> get_paper_service
                      └─> get_retriever_service ─> get_chat_service
```

因此覆盖底层 provider 会自然影响所有上层消费者，同一请求内相同依赖只解析一次。

依赖注入解决的是对象来源、生命周期和替换，不以“被多少文件复用”作为成立条件。CLI 或离线脚本可直接用构造函数创建服务，不需要模拟 FastAPI。

## 6. 响应契约

JSON 响应统一为：

```text
ApiResponse[T]
├─ code: int
├─ message: str
├─ data: T | null
└─ request_id: str
```

规则：

- `code` 等于 HTTP 状态码。
- 成功响应通过 `ok()` 或 `created()` 构造。
- 错误响应只由全局处理器通过 `fail()` 构造。
- 204 不返回 JSON；重定向不包 envelope。
- `message` 是中文用户提示，不能包含 SDK 原文和内部路径。
- `request_id` 同时写入 `X-Request-ID` 响应头。
- `data` 只保留调用方完成下一步所需字段；研究调试接口可保留分数，但应在契约中明确。

新增路由不得手写另一种错误 body，也不得在 HTTP 200 中用自定义 code 表示失败。

## 7. 异常设计

### 7.1 AppError

`AppError` 只用于可预期、可安全表达的应用拒绝：

```text
status_code    真实 HTTP 状态
message        可返回给客户端的中文提示
context        只写日志的诊断信息
```

典型场景：论文不存在、论文冲突、文件格式不支持、上传过大。

`ServiceUnavailableError` 只是 503 的便捷子类。它复用 `AppError` handler，不单独注册，不参与原生异常类型判断。

### 7.2 原生异常

下列错误直接传播：

- HTTPX、OpenAI、gRPC、Qdrant SDK 错误。
- SQLite 错误。
- `OSError`、`FileNotFoundError`、`PermissionError`。
- 内部数据不满足协议时的 `ValueError`、`TypeError`。

保留原异常能让全局映射区分连接失败与程序错误，并保留真实堆栈。不要创建笼统的 `UpstreamError`，它会把服务不可用、依赖坏数据和本地程序错误混为一种语义。

### 7.3 HTTP 映射

默认原则：

- 明确的业务拒绝按 `AppError.status_code` 返回。
- 当前无法提供服务且可能恢复时返回 503。
- 其他服务内部错误返回 500。
- 不把外部服务的 401/403 透传成当前用户的认证错误。
- 不默认使用 502/504；只有当前应用真的承担网关语义或路由显式决定时才使用。

连接失败、传输错误、超时、依赖 408/429/502/503/504、SQLite busy/locked 和特定 gRPC 不可用状态映射为 503。非预期 HTTP 状态、无效依赖数据、一般 SQLite/File I/O 和未知错误映射为 500。

## 8. 日志责任

同一异常传播链只应产生一条异常日志。

| 场景 | 记录位置 | 级别与堆栈 |
| --- | --- | --- |
| `AppError` 4xx | 全局异常处理器 | WARNING，无堆栈 |
| `AppError` 5xx | 全局异常处理器 | ERROR，有堆栈 |
| SDK/数据库/文件/未知异常 | 全局异常处理器 | ERROR，有堆栈 |
| 客户端重试后继续抛出 | 不在客户端记录；给原异常附加重试说明 | 由全局处理器记录 |
| 健康探针消费异常 | 探针处记录 | WARNING，有堆栈 |
| 补偿失败但继续抛原始异常 | 补偿处记录 | ERROR，有堆栈 |
| 请求开始/结束 | 访问中间件 | INFO，无异常堆栈 |

为什么 4xx 是 WARNING、5xx 是 ERROR：4xx 通常表示系统按预期拒绝了输入或业务操作；5xx 表示服务未能完成合法请求，需要运维关注。这是本项目的可观测性策略，不是 HTTP 协议硬性要求。

业务层可以记录阶段成功、数量和耗时等 INFO 日志，但不要在 `raise AppError(...)` 前再记录同一失败。异常处理器日志必须包含安全 message、HTTP 状态、context 和 request ID。

## 9. Store 与 Client 设计

### 9.1 Store

- `MetadataStore` 返回记录、空值或数据库操作结果，不抛带业务文案的异常。
- `FileStore` 封装目录结构、原子文件操作和路径边界，使用原生文件异常。
- `VectorStore` 封装 Qdrant 集合结构、读写和混合查询，使用 SDK/数据异常。

Store 不进行跨资源补偿。补偿属于拥有完整流程上下文的服务层。

### 9.2 Client

- 连接池和 HTTP 客户端按应用复用。
- 重试只覆盖明确的瞬时失败，采用有界次数和退避。
- 重试耗尽时重新抛出原异常；可使用异常备注附加尝试次数。
- 协议响应在客户端边界校验，失败时抛出精确的数据异常。
- API Key、上游响应体和内部地址不得进入客户端响应。

活动文本向量实现是 `infrastructure/clients/embedding_client.py` 中的本地 TEI 客户端。旧 `text_embedding_client.py` 已删除；`app.state.text_embedding_client` 是资源变量名，不代表该旧文件仍存在。

## 10. 健康检查设计

健康能力作为独立业务模块放在 `services/health/`，因为它包含状态模型、组件策略、并发探测和总体状态计算，而不只是一个 API schema。

三种端点含义：

- live：进程能否应答。
- ready：流量是否可以进入，只探测必选组件。
- details：诊断所有启用组件，返回完整结果，可关闭。

组件状态：`ok`、`error`、`disabled`、`unchecked`。只有 required 组件参与总体 ready 计算。探针必须有硬超时，且不能在 `/ready` 中调用未要求的昂贵模型服务。

新增依赖时必须同时说明：

1. 是否默认 required。
2. 使用什么只读或轻量探针。
3. 探针超时。
4. disabled、未配置和连接失败分别如何表达。
5. 是否影响应用启动，还是只影响 readiness。

## 11. 业务流程边界

### 11.1 上传

PaperService 负责顺序、业务校验和补偿。解析、清洗、切块、向量协议和数据库写入由各自模块负责。

预检查可以提供友好的论文重名提示，但数据库唯一约束必须保留以应对并发。若要让并发窗口内的唯一冲突也返回 409，应由 Store 返回明确的“名称冲突”结果，再由 PaperService 转为 `AppError`；不能在 Store 内直接抛业务文案，也不能通过匹配任意数据库错误字符串把所有完整性错误伪装成重名。

### 11.2 删除

不存在判断由 PaperService 处理。Store 的 `get_paper_by_id()` 返回 `None`，不提供 `require_paper()` 这类带业务语义的方法。

跨资源删除需要明确顺序和幂等策略。当前实现不是事务性的，后续应增加恢复任务或对账工具。

### 11.3 问答

LLM 客户端只理解补全协议。工具白名单、检索次数、证据编号和引用完整性属于 ChatService，因为这些规则依赖当前问答业务。

## 12. 配置原则

- 配置由 `Settings` 集中加载和跨字段校验。
- 密钥使用 `SecretStr`，禁止写入日志。
- 相对路径统一相对于项目根目录解析。
- `.env.example` 只保存非敏感示例。
- 配置项必须对应活动实现；历史 provider 或已删除组件的字段应在兼容期后移除。
- 默认 required 健康组件必须与部署期望一致，修改时同步文档与契约测试。

当前需要继续清理的配置债务：DashScope 文本向量选项仍在 `Settings`，但活动客户端只接受 `local_tei`；PyMuPDF 配置仍存在，但对应客户端已删除。

## 13. 新增能力的放置决策

```text
是否处理 HTTP 路径、状态、公开投影？
  是 → api/routes
  否
是否表达业务规则或编排多个资源？
  是 → services/<capability>
  否
是否访问数据库、文件系统、模型服务或第三方协议？
  是 → infrastructure/stores 或 infrastructure/clients
  否
是否被多个业务无差别复用，且与业务语义无关？
  是 → core 或 middleware
  否 → 放回最接近其所有者的业务模块
```

不要因为函数被两个文件调用就创建抽象；也不要因为目前只有一个调用点就把生命周期、外部协议或安全边界塞进路由。

## 14. 验收规则

后端骨架变更至少满足：

1. HTTP 状态与响应 `code` 一致。
2. JSON 响应保持 `code/message/data/request_id`；204 无 body。
3. 不增加无必要的业务数字码或逐服务异常类。
4. 同一异常传播链只记录一次。
5. 4xx 不输出无意义堆栈，5xx 保留完整堆栈和 request ID。
6. SDK/数据库/文件错误不在业务层重复包装。
7. 业务不存在、冲突等判断位于服务层。
8. 完全相同的服务模型和 API schema 不重复定义。
9. 新资源通过 lifespan 管理，通过 Depends 图提供。
10. 健康探针有超时，required/optional 语义明确。
11. 错误响应不泄露密钥、路径、SDK 原文或上游响应体。
12. 离线契约测试和相关业务回归通过。

当前验证命令：

```powershell
python -m pytest app/backend/tests -q -p no:cacheprovider
```

## 15. 演进优先级

建议按以下顺序继续：

1. 清理与运行实现不一致的历史配置项。
2. 明确并发论文重名冲突的 Store 结果协议。
3. 为跨存储上传/删除增加幂等恢复与对账。
4. 增加日志敏感字段脱敏测试。
5. 实现认证、授权和多用户数据隔离。
6. 在真实部署环境校验健康探针成本、超时与必选集合。
