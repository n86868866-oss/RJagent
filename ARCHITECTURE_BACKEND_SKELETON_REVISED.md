# Research Journey Agent 后端最小骨架技术设计

> 文档状态：后端代码实施基线  
> 适用范围：单用户、单研究课题 MVP  
> 当前阶段：正式业务开发前的最小后端骨架搭建  
> 架构方式：按技术职责分层，业务服务按业务域继续细分

---

## 1. 文档结论

本项目后端采用 FastAPI，并以“成熟框架优先、项目策略自定义、不过度抽象”为原则搭建最小骨架。

最终结构采用以下技术分层：

```text
main / config 
        ↓
middleware
        ↓
api
        ↓
services
        ↓
infrastructure
```

横切能力集中在：

```text
core
```

其中：

- `main.py` 负责创建和组装 FastAPI 应用。
- `config.py` 负责加载和校验运行配置。
- `lifespan.py` 负责创建、挂载和关闭共享 Client/Store。
- `middleware/` 负责 HTTP 请求进入和离开时的全局处理。
- `api/` 负责路由、请求/响应 Schema 和依赖注入。
- `services/` 负责业务规则、业务状态和流程编排。
- `infrastructure/` 负责数据库、文件系统、向量库和外部 API。
- `core/` 负责日志、统一响应、错误码、异常和安全规则。

健康检查采用：

```text
api/routes/health.py
        ↓
services/health_service.py
        ↓
infrastructure
```

因此不存在重复的健康检查实现：

- `health.py` 只处理 HTTP 路由和响应。
- `health_service.py` 执行组件检查和状态汇总。

---

## 2. 关于 `/api` 和接口版本

`/api` 是 HTTP 业务接口的命名空间，与 Embedding 模型、LLM 模型或模型版本没有关系。

例如：

```text
/api/papers
/api/chat/messages
/api/preferences
```

这些路径分别代表论文、对话和偏好等多个业务接口。

当前规则是：

- 业务接口统一挂载到固定 `/api` 前缀。
- 健康检查使用 `/health`，不放入 `/api`。
- 不添加 `API_PREFIX` 环境变量。
- 不添加 `API_VERSION` 环境变量。
- `/api` 前缀直接在 `api/router.py` 中声明。
- 只有未来出现不兼容接口变更时，才考虑 `/api/v2`。

---

## 3. 应用生命周期总图

## 3.1 应用启动生命周期

```text
加载并校验配置
        ↓
配置统一日志
        ↓
创建 FastAPI 应用
        ↓
注册中间件
        ↓
注册异常处理器
        ↓
注册 API 路由
        ↓
进入 lifespan
        ↓
创建数据目录
        ↓
创建数据库、向量库和 HTTP Client
        ↓
执行启动自检
        ↓
保存共享资源到 app.state
        ↓
应用进入 ready 状态
        ↓
Uvicorn 开始处理请求
```

## 3.2 单次请求生命周期

```text
客户端请求
   ↓
HTTP 中间件
- 请求 ID
- 访问日志开始
- CORS
- 后续链路追踪预留
   ↓
API 层
- 路由匹配
- 请求 Schema 解析
- 参数校验
- 认证和授权依赖
- 获取 Service 依赖
   ↓
业务层
- 业务规则
- 业务状态校验
- 业务流程编排
- 一致性和补偿策略
   ↓
基础设施层
- SQLite
- Qdrant
- 文件系统
- MinerU
- 阿里云 Embedding API
- OpenAI-compatible LLM API
   ↑
业务层
- 转换基础设施错误
- 生成业务结果或抛出 AppError
   ↑
API 层
- 响应 Schema
- 异常映射
- HTTP 状态码
   ↑
HTTP 中间件
- 记录状态码
- 记录耗时
- 写入 X-Request-ID
   ↑
客户端响应
```

该请求生命周期可重复执行，不重复创建全局 Client/Store。

## 3.3 应用关闭生命周期

```text
Uvicorn 请求应用关闭
        ↓
停止接收新请求
        ↓
进入 lifespan 清理阶段
        ↓
将应用标记为 not ready
        ↓
关闭 HTTP Client
        ↓
关闭 SQLite 等持久连接
        ↓
释放 Qdrant 和其他资源
        ↓
记录 application_stopped
        ↓
应用结束
```

---

## 4. 技术选型与自定义边界

| 能力 | 采用方案 | 框架或成熟库提供 | 项目自行定义 |
|---|---|---|---|
| Web 应用 | FastAPI | ASGI 应用、路由、OpenAPI | 应用组装顺序 |
| 应用服务器 | Uvicorn | 进程启动和请求监听 | 启动参数 |
| 生命周期 | FastAPI `lifespan` | 启动/关闭机制 | 创建哪些资源、失败策略 |
| 请求校验 | FastAPI + Pydantic | Body/Query/Path/Header 校验 | 字段语义和业务限制 |
| 配置 | pydantic-settings | 环境变量、`.env`、类型校验 | 配置字段和环境约束 |
| 路由拆分 | `APIRouter` | 多文件路由 | 路径和模块划分 |
| 依赖注入 | FastAPI `Depends` | 依赖执行和覆盖 | Service/Store/Client 获取方式 |
| 响应模型 | Pydantic + `response_model` | 序列化、过滤、OpenAPI | 统一成功/失败格式 |
| 参数异常 | `RequestValidationError` | 框架异常类型 | 统一错误响应 |
| HTTP 异常 | `HTTPException` | HTTP 异常机制 | 错误码映射 |
| 业务异常 | Python 异常 | 语言机制 | `AppError` 和业务错误码 |
| 中间件 | Starlette/FastAPI | 请求前后拦截 | request_id 和访问日志 |
| CORS | `CORSMiddleware` | CORS 协议 | 允许来源 |
| HTTP Client | HTTPX | 异步连接池、超时 | 上游协议和错误转换 |
| 重试 | Tenacity | 退避和停止条件 | 可重试错误范围 |
| SQLite | aiosqlite | 异步数据库访问 | Schema、事务和 Store |
| Qdrant | qdrant-client | 向量写入和检索 | Collection、Payload 和一致性 |
| PDF | PyMuPDF、MinerU | PDF 解析能力 | 主备解析策略 |
| 日志 | Python `logging` | Logger/Handler/Formatter | 格式、字段和脱敏 |
| 测试 | pytest、HTTPX | fixture、异步测试、HTTP 测试 | 项目测试场景 |
| 代码质量 | Ruff | 格式化和 lint | 项目规则 |
| 目录结构 | 无强制标准 | FastAPI 支持多文件 | 本项目自行设计 |

### 4.1 不自建的能力

当前阶段不自建：

- Web 框架。
- 路由器。
- 参数校验器。
- 依赖注入容器。
- HTTP 客户端。
- 数据库驱动。
- 向量数据库。
- 重试框架。
- JSON 序列化协议。
- OAuth2 服务端。
- 通用 ORM。
- 通用 CRUD 框架。
- `BaseService`。
- `BaseRepository`。

### 4.2 暂不引入的组件

当前阶段暂不引入：

- Celery、RQ 等任务队列。
- Redis。
- JWT 签发系统。
- 多用户账号系统。
- Prometheus。
- OpenTelemetry。
- 分布式锁。
- 第三方依赖注入容器。
- 复杂 DDD 分层。
- 全局响应包装中间件。

Redis 仅作为未来可能的基础设施，不属于当前最小骨架。

---

## 5. 最终目录结构

标记说明：

- `[F]`：主要使用 FastAPI、Starlette 或 Pydantic。
- `[M]`：主要使用成熟第三方库。
- `[P]`：项目自行定义的规则或胶水代码。

```text
research-journey-agent/
├── app/
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── main.py                         # [F+P] 创建并组装 FastAPI 应用  lifespan共享资源创建、自检和关闭
│   │   ├── config.py                       # [M+P] 环境变量与配置校验
│   │   │
│   │   ├── core/                           # 横切骨架规则
│   │   │   ├── __init__.py
│   │   │   ├── logging.py                  # [M+P] 日志配置、格式和脱敏
│   │   │   ├── responses.py                # [F+P] 统一成功/失败响应模型
│   │   │   ├── error_codes.py              # [P] 稳定业务错误码
│   │   │   ├── exceptions.py               # [P] AppError 和项目异常
│   │   │   ├── exception_handlers.py       # [F+P] 全局异常到 HTTP 的映射
│   │   │   └── security.py                 # [F+P] Principal、认证和权限规则
│   │   │
│   │   ├── middleware/                     # HTTP 全局请求处理
│   │   │   ├── __init__.py
│   │   │   ├── request_context.py          # [F+P] request_id 和请求上下文
│   │   │   └── access_log.py               # [F+P] 状态码、耗时和访问日志
│   │   │
│   │   ├── api/                            # HTTP 接口层
│   │   │   ├── __init__.py
│   │   │   ├── router.py                   # [F+P] /api 业务路由聚合
│   │   │   ├── dependencies.py             # [F+P] 获取 Store/Client/Service/Principal
│   │   │   │
│   │   │   ├── routes/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── health.py               # live、ready、details
│   │   │   │   ├── papers.py               # 论文 HTTP 接口
│   │   │   │   ├── chat.py                 # 问答 HTTP 接口
│   │   │   │   └── preferences.py          # 偏好 HTTP 接口
│   │   │   │
│   │   │   └── schemas/
│   │   │       ├── __init__.py
│   │   │       ├── request.py               # 通用请求模型，如分页参数
│   │   │       ├── health.py                # 健康检查响应数据
│   │   │       ├── papers.py                # 论文请求/响应数据
│   │   │       ├── chat.py                  # 问答请求/响应数据
│   │   │       └── preferences.py           # 偏好请求/响应数据
│   │   │
│   │   ├── infrastructure/                 # 外部系统和持久化适配
│   │   │   ├── __init__.py
│   │   │   ├── clients/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── llm_client.py
│   │   │   │   ├── mineru_client.py
│   │   │   │   ├── pymupdf_client.py
│   │   │   │   ├── text_embedding_client.py
│   │   │   │   └── visual_embedding_client.py
│   │   │   │
│   │   │   └── stores/
│   │   │       ├── __init__.py
│   │   │       ├── sqlite.py
│   │   │       ├── metadata_store.py
│   │   │       ├── vector_store.py
│   │   │       └── file_store.py
│   │   │
│   │   ├── services/                       # 业务层和流程编排
│   │   │   ├── __init__.py
│   │   │   ├── health_service.py
│   │   │   │
│   │   │   ├── papers/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── paper_service.py
│   │   │   │   └── ingestion/
│   │   │   │       ├── __init__.py
│   │   │   │       ├── pipeline.py
│   │   │   │       ├── models.py
│   │   │   │       ├── normalizer.py
│   │   │   │       ├── chunker.py
│   │   │   │       ├── embedder.py
│   │   │   │       └── indexer.py
│   │   │   │
│   │   │   ├── chat/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── chat_service.py
│   │   │   │   ├── retrieval_service.py
│   │   │   │   └── agent/
│   │   │   │       ├── __init__.py
│   │   │   │       ├── runner.py
│   │   │   │       ├── state.py
│   │   │   │       ├── tools.py
│   │   │   │       ├── prompts.py
│   │   │   │       └── validators.py
│   │   │   │
│   │   │   └── preferences/
│   │   │       ├── __init__.py
│   │   │       └── preference_service.py
│   │   │
│   │   └── .env                            # 本地配置，不提交 Git
│   │
│   └── frontend/
│       ├── templates/
│       │   └── index.html
│       └── static/
│           ├── app.js
│           └── styles.css
│
├── data/
│   ├── raw/
│   ├── parsed/
│   ├── assets/
│   ├── qdrant/
│   └── app.db
│
├── tests/
│   ├── unit/
│   │   ├── core/
│   │   ├── middleware/
│   │   ├── api/
│   │   ├── services/
│   │   └── infrastructure/
│   │
│   ├── integration/
│   │   ├── startup/
│   │   ├── api/
│   │   └── infrastructure/
│   │
│   ├── contract/
│   │   ├── test_success_response_contract.py
│   │   └── test_error_response_contract.py
│   │
│   └── fixtures/
│
├── scripts/
│   └── smoke_test.py
│
├── .env.example
├── .gitignore
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── requirements-lock.txt
├── requirements-mineru-lock.txt
├── README.md
└── ARCHITECTURE.md
```

## 6. 文件职责

## 6.1 顶层启动文件

| 文件 | 职责 | 不应包含 |
|---|---|---|
| `main.py` | 定义 `create_app()`、创建 FastAPI、注册中间件、异常处理器和路由，并导出 `app` | Store/Client 的实际连接、SQL、业务流程 |
| `config.py` | Settings、环境变量、路径解析和跨字段校验 | 资源连接、HTTP 请求、业务查询 |
| `lifespan.py` | 创建目录、Store、Client；执行启动自检；写入 `app.state`；关闭资源 | HTTP 路由、业务响应格式 |

## 6.2 Core

| 文件 | 职责 | 边界 |
|---|---|---|
| `core/logging.py` | 日志初始化、Formatter、Filter、敏感字段脱敏 | 不处理业务日志内容 |
| `core/responses.py` | `ApiResponse`、`ListResponse`、`ErrorResponse`、分页元数据 | 不定义具体论文或问答字段 |
| `core/error_codes.py` | 通用和业务错误码常量/枚举 | 不保存用户文案和堆栈 |
| `core/exceptions.py` | `AppError` 及基础异常类型 | 不依赖 Router 或 Store |
| `core/exception_handlers.py` | 注册 FastAPI 全局异常处理器 | 不编写业务流程 |
| `core/security.py` | Principal、API Key 提取、权限检查函数 | 不建立完整用户系统 |

## 6.3 Middleware

| 文件 | 职责 |
|---|---|
| `middleware/request_context.py` | 生成或校验 request_id；保存到 ContextVar/Request；写回响应头 |
| `middleware/access_log.py` | 记录 method、route、status_code、duration_ms 和 request_id |

CORS 直接使用 FastAPI/Starlette 的 `CORSMiddleware`，无需新建自定义 `cors.py`。

## 6.4 API

| 文件 | 职责 |
|---|---|
| `api/router.py` | 聚合业务 Router，并统一添加 `/api` 前缀；单独挂载 `/health` |
| `api/dependencies.py` | 从 `app.state` 获取 Store/Client；构建 Service；暴露 Principal 依赖 |
| `api/routes/health.py` | 声明 `/health/live`、`/health/ready`、`/health/details` |
| `api/routes/papers.py` | 论文上传、列表、详情、删除、重新索引的 HTTP 接口 |
| `api/routes/chat.py` | 会话和问答 HTTP 接口 |
| `api/routes/preferences.py` | 偏好读取和更新 HTTP 接口 |
| `api/schemas/request.py` | 通用分页、查询和过滤请求模型 |
| `api/schemas/health.py` | 健康检查的数据结构 |
| `api/schemas/papers.py` | 论文请求和响应 DTO |
| `api/schemas/chat.py` | 问答请求和响应 DTO |
| `api/schemas/preferences.py` | 偏好请求和响应 DTO |

## 6.5 Services

| 文件 | 职责 |
|---|---|
| `services/health_service.py` | 检查应用状态和各基础设施组件，汇总健康结果 |
| `services/papers/paper_service.py` | 论文业务入口、状态校验、Store 和 pipeline 编排 |
| `services/papers/ingestion/pipeline.py` | 论文入库总流程 |
| `normalizer.py` | 解析结果标准化 |
| `chunker.py` | 章节感知和递归文本分块 |
| `embedder.py` | 调用 Embedding Client |
| `indexer.py` | 写入 Qdrant 并处理索引一致性 |
| `services/chat/chat_service.py` | 问答业务入口、会话记录和回答生成编排 |
| `retrieval_service.py` | Qdrant 检索、去重、阈值、相邻 Chunk 合并 |
| `services/chat/agent/*` | Agent 状态、工具、Prompt、终止和引用校验 |
| `preference_service.py` | 偏好读取、校验和保存 |

## 6.6 Infrastructure

| 文件 | 职责 |
|---|---|
| `stores/sqlite.py` | SQLite 连接、WAL、busy timeout、事务、schema version |
| `stores/metadata_store.py` | 论文、会话、偏好等结构化数据读写 |
| `stores/vector_store.py` | Qdrant Collection、upsert、search、delete |
| `stores/file_store.py` | PDF、解析结果和资源文件读写 |
| `clients/llm_client.py` | OpenAI-compatible LLM 协议适配 |
| `clients/mineru_client.py` | MinerU 服务协议适配 |
| `clients/pymupdf_client.py` | 本地 PDF 校验、文本提取和页面渲染 |
| `clients/text_embedding_client.py` | 文本 Embedding 请求和响应协议校验 |
| `clients/visual_embedding_client.py` | 视觉 Embedding 服务适配 |

---

## 7. Main 实现设计

## 7.1 main.py 不再依赖 application.py

`main.py` 内部直接定义：

```text
create_app(settings: Settings | None = None) -> FastAPI
```

然后导出：

```text
app = create_app()
```

保留 `create_app()` 的理由不是拆文件，而是便于：

- 测试时传入 test Settings。
- 测试不同中间件和路由配置。
- 避免测试只能使用全局生产配置。
- 保持应用创建过程可重复。

## 7.2 main.py 的固定组装顺序

```text
1. settings = settings or get_settings()
2. configure_logging(settings)
3. app = FastAPI(..., lifespan=lifespan)
4. 注册 CORS
5. 注册 request_context 中间件
6. 注册 access_log 中间件
7. register_exception_handlers(app)
8. app.include_router(root_router)
9. return app
```

中间件实际执行顺序需通过测试确认，不只依靠注册顺序猜测。

## 7.3 main.py 禁止事项

禁止：

- `print(settings...)`
- 直接创建 `httpx.AsyncClient`
- 直接连接 SQLite
- 直接连接 Qdrant
- 调用 Embedding 或 LLM
- 写入文件
- 实现论文业务
- 实现健康检查细节

---

## 8. Lifespan 实现设计

## 8.1 共享资源策略

`lifespan.py` 直接创建共享对象并写入：

```text
app.state.settings
app.state.sqlite
app.state.metadata_store
app.state.vector_store
app.state.file_store
app.state.text_embedding_client
app.state.llm_client
app.state.mineru_client
app.state.visual_embedding_client
app.state.ready
```

是否创建某个可选 Client 由 Settings 决定。

API 路由不直接散乱访问这些字段，而是统一通过 `api/dependencies.py` 获取。

## 8.2 启动步骤

```text
1. 从 app.state 或 get_settings() 获取配置
2. 创建 data/raw、data/parsed、data/assets、data/qdrant
3. 验证目录可写
4. 创建 SQLite 连接
5. 设置 WAL 和 busy timeout
6. 校验 schema version
7. 创建 metadata_store
8. 创建 file_store
9. 创建 vector_store
10. 校验 Qdrant Collection 和向量维度
11. 创建 TextEmbeddingClient
12. 创建 LLMClient
13. 创建 MinerUClient
14. 按配置创建 VisualEmbeddingClient
15. 将共享对象写入 app.state
16. 运行启动自检
17. 设置 app.state.ready = True
18. 记录 application_started
19. yield
```

## 8.3 关闭步骤

关闭顺序采用创建顺序的反向顺序：

```text
1. app.state.ready = False
2. 关闭 visual_embedding_client
3. 关闭 mineru_client
4. 关闭 llm_client
5. 关闭 text_embedding_client
6. 关闭 vector_store（如实现需要）
7. 关闭 metadata_store（如实现需要）
8. 关闭 SQLite
9. 记录 application_stopped
```

所有关闭操作应尽量执行，不能因为前一个 Client 关闭失败而跳过后续资源。

建议使用：

```text
contextlib.AsyncExitStack
```

管理多个异步资源，避免手写复杂清理分支。该工具属于 Python 标准库，不是自建资源容器。

## 8.4 启动硬失败

以下情况阻止应用启动：

- Settings 校验失败。
- 数据目录不可创建或不可写。
- SQLite 无法连接。
- SQLite schema version 不兼容。
- Qdrant 本地目录无法打开。
- 必需 Collection 配置冲突。
- Collection 向量维度与 Embedding 配置不一致。
- 必需 Client 无法完成构造。
- production 环境安全配置不满足要求。

## 8.5 启动降级

以下外部服务暂时不可访问时，默认允许进程启动，但 readiness 必须准确反映：

- 可选视觉 Embedding 服务。

是否严格阻止启动由：

```text
STARTUP_STRICT_EXTERNALS
```

控制。

---

## 9. 健康检查设计

## 9.1 职责分离

```text
api/routes/health.py
```

负责：

- HTTP path。
- HTTP status code。
- response_model。
- 获取 `HealthService`。
- 将 Service 结果返回给客户端。

```text
services/health_service.py
```

负责：

- 执行组件检查。
- 聚合状态。
- 判断 ready、not_ready。
- 控制检查超时。
- 对外隐藏敏感错误。


## 9.2 GET /health/live

只检查应用进程能否响应。

规则：

- 不查询 SQLite。
- 不访问 Qdrant。
- 不调用 MinerU。
- 不调用 Embedding。
- 不调用 LLM。
- 返回 200。

示例：

```json
{
  "status": "ok"
}
```

## 9.3 GET /health/ready

检查应用是否可接收核心业务请求。

最小检查：

- lifespan 已完成。
- `app.state.ready` 为 true。
- 运行目录可用。
- SQLite 可执行轻量查询。
- Qdrant 可访问。
- Collection 维度匹配。
- 必需 Store/Client 已创建且可应用。

返回：

- ready：200。
- not_ready：503。
- degraded：根据项目策略返回 200 或 503；MVP 默认返回 200，并明确组件状态。

## 9.4 GET /health/details

用于人工排障。

访问条件：

- development/test 环境可启用。
- production 默认关闭。
- production 开启时要求管理权限。

允许返回：

- 组件名称。
- 状态。
- 最近检查时间。
- 检查耗时。
- 简化错误类型。
- 非敏感建议。

禁止返回：

- API Key。
- Token。
- Authorization。
- 完整连接串。
- 完整文件绝对路径。
- Python 堆栈。
- 上游响应全文。

---

## 10. API 路由设计

## 10.1 Router 聚合

`api/router.py` 建立两个 Router：

```text
health_router
business_router(prefix="/api")
```

挂载效果：

```text
/health/live
/health/ready
/health/details

/api/papers
/api/chat
/api/preferences
```

## 10.2 业务路由建议

```text
GET    /api/papers
POST   /api/papers
GET    /api/papers/{paper_id}
DELETE /api/papers/{paper_id}
POST   /api/papers/{paper_id}/reindex

POST   /api/chat/messages
GET    /api/chat/sessions/{session_id}

GET    /api/preferences
PUT    /api/preferences
```

## 10.3 Router 职责

Router 只负责：

1. 声明 method/path。
2. 声明输入 Schema。
3. 声明响应模型。
4. 声明 HTTP 状态码。
5. 声明认证和权限依赖。
6. 获取 Service。
7. 调用 Service。
8. 构建统一成功响应。

Router 不负责：

- SQL。
- Qdrant 操作。
- 文件读写。
- HTTPX 调用。
- 重试。
- 事务编排。
- 论文状态机。
- Agent 循环。
- 大段 try/except。

---

## 11. API Schema 设计

## 11.1 通用请求模型

`api/schemas/request.py` 只放多个业务共用的请求模型，例如：

```text
PaginationRequest
├── page
└── page_size
```

不把所有业务请求都堆入 `request.py`。

## 11.2 业务 Schema

分别保存在：

```text
api/schemas/papers.py
api/schemas/chat.py
api/schemas/preferences.py
```

它们只描述 API 输入和输出，不描述数据库表结构。

例如：

```text
PaperResponse
PaperListItem
PaperUploadResponse
ChatMessageRequest
ChatAnswerResponse
PreferenceResponse
PreferenceUpdateRequest
```

## 11.3 健康 Schema

`api/schemas/health.py` 保存：

```text
LivenessData
ReadinessData
HealthComponentData
HealthDetailsData
```

最终仍可被 `core/responses.py` 的统一 envelope 包装。

---

## 12. 统一成功响应

## 12.1 core/responses.py

统一定义：

```text
ResponseMeta
PaginationMeta
ApiResponse[T]
ListResponse[T]
ErrorItem
ErrorBody
ErrorResponse
```

### 对象响应

```json
{
  "success": true,
  "data": {
    "id": "paper_123",
    "title": "Example"
  },
  "meta": {
    "request_id": "..."
  }
}
```

### 列表响应

```json
{
  "success": true,
  "data": [
    {
      "id": "paper_123",
      "title": "Example"
    }
  ],
  "meta": {
    "request_id": "...",
    "pagination": {
      "page": 1,
      "page_size": 20,
      "total": 63,
      "has_next": true
    }
  }
}
```

## 12.2 分页规则

MVP 使用页码分页：

```text
page >= 1
1 <= page_size <= 100
默认 page_size = 20
```

Service 或 Store 内部可转换为：

```text
limit
offset
```

## 12.3 例外响应

以下响应不强制统一 JSON envelope：

- `204 No Content`
- 文件下载
- StreamingResponse
- Server-Sent Events
- 静态资源
- HTML 页面

不使用全局响应包装中间件。

---

## 13. 统一错误处理

## 13.1 错误传播方向

```text
Infrastructure 异常
        ↓
Service 转换为 AppError
        ↓
Router 不捕获或只处理局部清理
        ↓
core/exception_handlers.py
        ↓
统一 ErrorResponse
```

## 13.2 AppError

`core/exceptions.py` 定义：

```text
AppError
├── code
├── message
├── http_status
├── details
└── log_level
```

基础子类：

```text
AuthenticationError
PermissionDeniedError
ResourceNotFoundError
ConflictError
DependencyUnavailableError
DependencyTimeoutError
DependencyProtocolError
InvariantViolationError
```

业务可进一步定义：

```text
PaperNotFoundError
DuplicatePaperError
PaperStateConflictError
InsufficientEvidenceError
```

业务错误必须继承 `AppError`。

## 13.3 全局异常处理器

`core/exception_handlers.py` 统一注册：

1. `RequestValidationError`
2. `StarletteHTTPException`
3. `AppError`
4. `Exception`

### 参数验证错误

保留 HTTP 422。

响应示例：

```json
{
  "success": false,
  "error": {
    "code": "REQUEST_VALIDATION_ERROR",
    "message": "请求参数不合法。",
    "details": [
      {
        "field": "body.title",
        "reason": "Field required",
        "type": "missing"
      }
    ]
  },
  "meta": {
    "request_id": "..."
  }
}
```

### 未知异常

规则：

- 日志记录完整堆栈。
- 客户端返回 HTTP 500。
- 错误码固定为 `INTERNAL_ERROR`。
- 不返回内部异常文本。
- 响应包含 request_id。

## 13.4 HTTP 状态和业务码

| 场景 | HTTP | 错误码 |
|---|---:|---|
| 参数失败 | 422 | `REQUEST_VALIDATION_ERROR` |
| 未认证 | 401 | `AUTHENTICATION_REQUIRED` |
| 无权限 | 403 | `PERMISSION_DENIED` |
| 论文不存在 | 404 | `PAPER_NOT_FOUND` |
| 重复论文 | 409 | `PAPER_ALREADY_EXISTS` |
| 状态冲突 | 409 | `PAPER_STATE_CONFLICT` |
| 文件过大 | 413 | `UPLOAD_TOO_LARGE` |
| 类型错误 | 415 | `UNSUPPORTED_MEDIA_TYPE` |
| 上游协议错误 | 502 | `DEPENDENCY_PROTOCOL_ERROR` |
| 上游不可用 | 503 | `DEPENDENCY_UNAVAILABLE` |
| 上游超时 | 504 | `DEPENDENCY_TIMEOUT` |
| 未知错误 | 500 | `INTERNAL_ERROR` |

---

## 14. API Dependencies 设计

`api/dependencies.py` 统一处理依赖获取。

## 14.1 基础设施依赖

例如：

```text
get_settings(request)
get_metadata_store(request)
get_vector_store(request)
get_file_store(request)
get_text_embedding_client(request)
get_llm_client(request)
get_mineru_client(request)
```

这些函数从 `request.app.state` 读取资源，并进行类型/存在性检查。

## 14.2 Service 依赖

例如：

```text
get_health_service(...)
get_paper_service(...)
get_chat_service(...)
get_preference_service(...)
```

Service 可以按请求构造，但其内部使用的 Client/Store 是 lifespan 创建的共享对象。

不要求把 Service 也做成全局单例。

## 14.3 测试覆盖

FastAPI 的依赖覆盖用于测试：

```text
app.dependency_overrides[get_metadata_store] = fake_store
```

因此不需要自建 DI 容器。

---

## 15. 业务层设计

## 15.1 固定调用方向

```text
Router
  ↓
Service
  ↓
Store / Client
```

禁止反向依赖：

```text
Store → Service
Client → Router
Service → FastAPI Request
```

## 15.2 Service 职责

Service 负责：

- 业务规则。
- 业务状态校验。
- 流程编排。
- 幂等性。
- 事务边界。
- 跨 Store/Client 协作。
- 一致性和补偿。
- 基础设施异常转换。
- Agent 预算和终止条件。
- 证据校验。

Service 不应：

- 返回 `JSONResponse`。
- 抛 `HTTPException`。
- 读取 Header/Cookie。
- 生成统一响应 envelope。
- 直接依赖 FastAPI `Request`。

## 15.3 业务和 API 是否分开

本目录明确将业务和 API 分开：

```text
api/routes/papers.py
api/schemas/papers.py
services/papers/paper_service.py
```

分别代表：

- Router：HTTP 接口。
- Schema：HTTP 数据契约。
- Service：论文业务规则。

因此不再采用每个业务目录内部同时放 `router.py`、`schemas.py`、`service.py` 的功能模块结构。

该分离更适合当前“按技术职责优先”的架构目标。

## 15.4 Service 内部按业务继续细分

技术分层不代表把所有 Service 塞入一个文件。

复杂业务仍可分目录：

```text
services/papers/
services/chat/
services/preferences/
```

论文入库和 Agent 因为内部步骤较多，可继续保留子目录。

---

## 16. 基础设施层设计

## 16.1 Store

Store 只处理持久化。

### sqlite.py

负责：

- 连接。
- WAL。
- busy timeout。
- 事务辅助。
- schema version。
- 关闭。

### metadata_store.py

负责：

- 论文元数据。
- 论文状态。
- 会话。
- 对话记录。
- 用户偏好。

### vector_store.py

负责：

- Collection。
- 维度和距离函数检查。
- upsert。
- search。
- delete。
- payload 校验。

### file_store.py

负责：

- 原始 PDF。
- 解析 JSON/Markdown。
- 图片和表格。
- 临时文件。
- 原子替换。
- 清理。

Store 不决定：

- HTTP 状态。
- 业务错误文案。
- 是否允许重新索引。
- Agent 是否继续循环。

## 16.2 Client

每个 Client 只负责一个外部协议。

共同要求：

- 明确连接超时和读取超时。
- 复用异步连接池。
- 输入校验。
- 响应协议校验。
- 错误分类。
- 重试策略。
- `close()`。
- 日志脱敏。

当前 `TextEmbeddingClient` 中以下能力保留：

- 空文本拒绝。
- 批次拆分。
- `text_index` 排序。
- 数量校验。
- 索引连续性校验。
- 向量维度校验。
- 网络错误分类。
- HTTP 状态分类。
- 非 JSON 错误。

---

## 17. 安全设计

## 17.1 MVP 范围

当前是单用户系统，不建设完整账号中心。

只建立可替换的安全接入点：

```text
Principal
├── subject
├── auth_type
├── permissions
└── is_authenticated
```

配置：

```text
AUTH_MODE=disabled | api_key
API_KEY_HEADER_NAME=X-API-Key
APP_API_KEY=
```

## 17.2 API Key

使用 FastAPI `APIKeyHeader`。

项目自定义：

- 常量时间比较。
- Principal 构造。
- 权限名称。
- 401/403 错误码。
- 日志脱敏。

## 17.3 权限

权限通过 `Depends` 或 `Security`：

```text
paper:read
paper:write
chat:ask
preferences:read
preferences:write
admin:diagnostics
```

不使用通用权限中间件。

原因：

- 权限随路由和动作变化。
- 需要明确出现在 OpenAPI。
- 未来可能涉及资源所有权。
- 依赖覆盖更容易测试。

---

## 18. 日志和中间件

## 18.1 日志

第一阶段使用 Python `logging`。

环境策略：

```text
development → 可读文本
test        → 简化文本
production  → 单行 JSON
```

必要字段：

```text
timestamp
level
event
logger
request_id
method
path
route
status_code
duration_ms
principal
component
error_code
```

不记录：

- API Key。
- Authorization。
- Cookie。
- SecretStr。
- 论文全文。
- 完整 Prompt。
- 完整模型上下文。
- SQL 参数中的敏感正文。

## 18.2 Request Context

`middleware/request_context.py`：

1. 读取可选 `X-Request-ID`。
2. 校验长度和字符集。
3. 不可信或不合法时生成新 ID。
4. 保存到 Request/ContextVar。
5. 响应写入 `X-Request-ID`。
6. 统一响应 meta 使用该 ID。

## 18.3 Access Log

`middleware/access_log.py`：

```text
request_received
request_completed
```

完成日志至少包含：

```text
method
route
status_code
duration_ms
request_id
```

异常请求也必须产生完成日志。

避免同时开启格式重复的 Uvicorn access log 和项目 access log。

---

## 19. 配置新增

在现有 `Settings` 基础上增加：

```text
LOG_FORMAT=text | json
LOG_ACCESS_ENABLED=true
TRUST_INBOUND_REQUEST_ID=false

AUTH_MODE=disabled | api_key
API_KEY_HEADER_NAME=X-API-Key
APP_API_KEY=

STARTUP_STRICT_EXTERNALS=false
HEALTH_DETAILS_ENABLED=false

DOCS_ENABLED=true
```

明确不新增：

```text
API_PREFIX
API_VERSION
```

## 19.1 配置约束

- `AUTH_MODE=api_key` 时 `APP_API_KEY` 必填。
- production 且监听非回环地址时，不允许 `AUTH_MODE=disabled`。
- production 推荐 `LOG_FORMAT=json`。
- `HEALTH_DETAILS_ENABLED` 在 production 默认 false。
- CORS 使用凭据时，不允许来源为无约束通配符。
- 只有启用 Cookie Session 时才要求 `APP_SECRET_KEY`。

---

## 20. 测试结构

## 20.1 Unit

### core

- ErrorResponse 格式。
- 错误码稳定性。
- AppError 属性。
- 参数错误路径转换。
- 日志脱敏。
- API Key 比较。
- 权限检查。

### middleware

- 请求自动获得 request_id。
- 非法入站 request_id 被替换。
- 响应头包含 request_id。
- access log 包含状态和耗时。
- 路由异常时仍记录日志。

### api

- Router path。
- Schema 验证。
- Dependency 获取。
- Service dependency override。
- 权限依赖。

### services

- HealthService 状态聚合。
- PaperService 业务状态。
- Ingestion 流程。
- Retrieval 阈值和合并。
- Agent 终止和引用校验。
- PreferenceService 规则。

### infrastructure

- Embedding Client 现有测试。
- SQLite WAL。
- schema version。
- Qdrant 维度。
- 文件原子写入。
- Client close。
- 重试和错误转换。

## 20.2 Integration

### startup

- TestClient 正确进入 lifespan。
- 所有共享资源被创建。
- 退出时所有 Client 被关闭。
- 配置错误阻止启动。
- Qdrant 维度错误阻止启动。

### api

- `/health/live` 返回 200。
- `/health/ready` 根据状态返回 200/503。
- `/health/details` 受配置和权限控制。
- 业务路由位于 `/api`。
- 参数错误返回统一 422。
- 未知异常返回统一 500。
- API Key 缺失返回 401。
- 权限不足返回 403。

### infrastructure

- SQLite 真实文件。
- Qdrant Local Mode。
- 可选真实 DashScope。
- 可选真实 MinerU。

## 20.3 Contract

固定：

- 对象成功响应。
- 列表成功响应。
- 分页字段。
- 参数错误响应。
- AppError 响应。
- 未知错误响应。
- request_id 字段。
- 204 无响应体。

---

## 21. 实施顺序

正式代码实施按以下顺序执行。

## 阶段 0：整理目录和依赖

1. 创建最终目录。
2. 为 Python 包补充 `__init__.py`。
3. 将现有 `config.py` 保留在 `app/backend/config.py`。
4. 将现有 `text_embedding_client.py` 移至 `infrastructure/clients/`。
5. 将现有测试移至 `tests/unit/infrastructure/clients/` 或保持可运行后再迁移。
6. 新增 `requirements-dev.txt`。
7. 新增 `pyproject.toml` 中 pytest 和 Ruff 配置。
8. 每次移动后运行现有 Embedding 测试。

### 阶段验收

- Import 全部正常。
- 现有 Embedding 单元测试仍通过。
- `get_settings()` 路径正确。
- `.env` 仍能加载。

---

## 阶段 1：启动线最小实现

实施文件：

```text
main.py
config.py
lifespan.py
core/logging.py
api/router.py
```

步骤：

1. 移除 `main.py` 中所有调试 `print()`。
2. 在 `main.py` 内定义 `create_app()`。
3. 配置日志。
4. 创建 FastAPI。
5. 注册 lifespan。
6. 注册根 Router。
7. 先让 lifespan 只创建必要目录并设置 ready。
8. 添加启动/关闭日志。

### 阶段验收

- `uvicorn app.backend.main:app` 可启动。
- 进程退出无异常。
- 无导入阶段调试输出。
- `create_app(test_settings)` 可用于测试。

---

## 阶段 2：健康检查

实施文件：

```text
api/routes/health.py
api/schemas/health.py
services/health_service.py
api/dependencies.py
```

步骤：

1. 实现 `/health/live`。
2. 实现 `HealthService`。
3. 实现 `/health/ready`。
4. 实现受配置控制的 `/health/details`。
5. 增加 ready 状态。
6. 增加组件检查超时。
7. 编写 unit/integration tests。

### 阶段验收

- live 不访问外部组件。
- ready 能反映资源未初始化。
- details 不泄漏密钥和堆栈。
- 健康接口路径不带 `/api`。

---

## 阶段 3：共享基础设施生命周期

实施文件：

```text
lifespan.py
infrastructure/stores/sqlite.py
infrastructure/stores/metadata_store.py
infrastructure/stores/vector_store.py
infrastructure/stores/file_store.py
infrastructure/clients/*
api/dependencies.py
```

步骤：

1. 创建 SQLite。
2. 设置 WAL 和 busy timeout。
3. 建立 schema version。
4. 创建 FileStore。
5. 创建 Qdrant VectorStore。
6. 校验 Collection 维度。
7. 创建所有必需 HTTP Client。
8. 写入 `app.state`。
9. 通过 dependencies 读取。
10. 使用 AsyncExitStack 确保关闭。
11. 更新 ready 检查。

### 阶段验收

- 所有共享 Client/Store 由 lifespan 创建。
- 所有可关闭资源在退出时关闭。
- Router 不直接创建 Client。
- Qdrant 维度不一致时启动失败。
- 外部软依赖失败时按配置降级或失败。

---

## 阶段 4：统一接口失败线

实施文件：

```text
core/error_codes.py
core/exceptions.py
core/responses.py
core/exception_handlers.py
middleware/request_context.py
```

步骤：

1. 定义 `AppError`。
2. 定义初始错误码。
3. 定义 `ErrorResponse`。
4. 实现 RequestValidationError handler。
5. 实现 HTTPException handler。
6. 实现 AppError handler。
7. 实现 Exception handler。
8. 实现 request_id。
9. 所有错误响应加入 request_id。
10. 编写错误 contract tests。

### 阶段验收

- 422、401、403、404、409、500 格式一致。
- 未知异常不泄漏内部信息。
- Service 可以只抛 AppError。
- 日志可通过 request_id 定位错误。

---

## 阶段 5：统一接口成功线

实施文件：

```text
core/responses.py
api/schemas/request.py
api/schemas/papers.py
api/schemas/chat.py
api/schemas/preferences.py
api/routes/*
```

步骤：

1. 定义 `ApiResponse[T]`。
2. 定义 `ListResponse[T]`。
3. 定义分页模型。
4. 为 Router 声明 `response_model`。
5. 固定对象和列表响应。
6. 固定创建、更新、删除状态码。
7. 保证 204 无响应体。
8. 编写成功 contract tests。

### 阶段验收

- OpenAPI 显示准确响应模型。
- 对象和列表响应格式稳定。
- 文件和流式响应未被包装。
- 业务接口统一位于 `/api`。

---

## 阶段 6：日志与访问链路

实施文件：

```text
core/logging.py
middleware/request_context.py
middleware/access_log.py
main.py
```

步骤：

1. 实现 development/test/production 格式。
2. 实现 request_id Filter。
3. 实现 access log。
4. 统一 Uvicorn 日志配置。
5. 实现敏感字段脱敏。
6. 验证异常请求也有完成日志。
7. 编写 middleware tests。

### 阶段验收

- 每个请求均有 request_id。
- 响应头包含 `X-Request-ID`。
- 完成日志包含 route、status、duration。
- 不记录密钥或论文全文。
- 不产生两套重复访问日志。

---

## 阶段 7：基础认证和权限接入点

实施文件：

```text
core/security.py
api/dependencies.py
config.py
api/routes/*
```

步骤：

1. 定义 Principal。
2. 定义 disabled/api_key 模式。
3. 使用 `APIKeyHeader`。
4. 实现常量时间比较。
5. 实现 `require_permissions()`。
6. 保护 `/health/details`。
7. 为业务 Router 预留权限。
8. 编写 401/403 测试。

### 阶段验收

- 开发模式可明确关闭认证。
- 生产模式安全约束有效。
- API Key 不出现在日志。
- 401 和 403 语义分离。
- 权限不通过中间件实现。

---

## 阶段 8：业务 Service 骨架

实施文件：

```text
services/papers/paper_service.py
services/chat/chat_service.py
services/chat/retrieval_service.py
services/preferences/preference_service.py
api/dependencies.py
```

步骤：

1. 创建 Service 构造函数。
2. 通过构造参数接收 Store/Client。
3. 定义 Service 方法签名。
4. 暂不实现完整业务。
5. Router 只调用 Service。
6. 使用 fake Store/Client 编写 Service 单元测试。
7. 确认 Service 不依赖 FastAPI 类型。

### 阶段验收

- Router、Service、Infrastructure 调用方向正确。
- Service 可独立单元测试。
- Service 业务错误使用 AppError。
- 无 `BaseService` 或通用仓储抽象。

---

## 阶段 9：README 和冒烟验证

实施文件：

```text
README.md
scripts/smoke_test.py
requirements-dev.txt
pyproject.toml
```

README 至少包含：

1. 环境创建。
2. 依赖安装。
3. `.env` 配置。
4. MinerU 独立环境。
5. 启动命令。
6. 健康检查命令。
7. Swagger 地址。
8. 单元测试。
9. 集成测试。
10. Ruff。
11. 常见排障。
12. 依赖锁定流程。

`smoke_test.py` 至少验证：

- `/health/live`
- `/health/ready`
- `/openapi.json`
- 一个不存在路由的统一错误行为
- 可选认证模式

---

## 22. P0 实施清单

在正式论文、检索和问答业务开发前完成：

### 启动线

- [ ] `main.py` 内有 `create_app()`。
- [ ] 使用 FastAPI lifespan。
- [ ] Settings 正确加载。
- [ ] 所有共享 Client/Store 由 lifespan 创建和关闭。
- [ ] 共享对象通过 `app.state` 保存。
- [ ] API 通过 dependencies 获取共享对象。
- [ ] 没有模块导入阶段的网络连接。
- [ ] 没有调试 `print()`。

### 接口线

- [ ] 使用 `APIRouter`。
- [ ] 业务接口使用固定 `/api`。
- [ ] 健康接口使用 `/health`。
- [ ] 有统一对象响应。
- [ ] 有统一列表响应。
- [ ] 有统一错误响应。
- [ ] 参数错误保留 422。
- [ ] 204 不返回 JSON。
- [ ] OpenAPI 响应模型准确。

### 业务线

- [ ] Router 不直接访问 Store/Client。
- [ ] Service 不依赖 FastAPI Request/Response。
- [ ] Store/Client 不决定 HTTP 状态。
- [ ] 业务错误通过 `AppError`。
- [ ] Service 可以注入 fake 依赖。

### 运维线

- [ ] `/health/live`。
- [ ] `/health/ready`。
- [ ] 受限 `/health/details`。
- [ ] request_id。
- [ ] access log。
- [ ] 未知异常堆栈日志。
- [ ] 日志脱敏。
- [ ] 骨架 contract tests。
- [ ] startup integration tests。
- [ ] README。
- [ ] smoke test。

### 安全线

- [ ] Principal。
- [ ] disabled/api_key 模式。
- [ ] API Key 不泄漏。
- [ ] 401/403 分离。
- [ ] diagnostics 权限。

---

## 23. 最小骨架验收标准

完成骨架后必须满足：

1. `uvicorn app.backend.main:app` 能正常启动和关闭。
2. 所有共享 Client/Store 只在 lifespan 中创建。
3. 不存在 `application.py` 和 `resources.py` 依赖。
4. 不存在重复的中间件目录。
5. 不存在重复的异常处理器文件。
6. 不存在 `/api/v1` 相关配置或测试。
7. `/health/live` 不访问基础设施。
8. `/health/ready` 能反映 SQLite 和 Qdrant 状态。
9. `/health/details` 默认不对生产环境公开。
10. Router 只负责 HTTP。
11. Service 只负责业务。
12. Infrastructure 只负责外部系统和持久化。
13. 422、401、403、404、409、500 返回统一错误结构。
14. 所有错误响应具有 request_id。
15. 未知异常对外不暴露内部内容。
16. 所有请求有访问日志和耗时。
17. 现有 Embedding Client 测试继续通过。
18. Contract tests 固定统一响应协议。
19. README 可以让新环境独立完成启动和排障。
20. 进入业务开发后不需要再次大范围移动骨架目录。

---

## 24. 最终架构规则

1. `main.py` 负责应用组装，但不创建实际外部连接。
2. `lifespan.py` 是共享 Client/Store 生命周期的唯一入口。
3. `config.py` 只负责配置，不执行基础设施操作。
4. `core/` 只放横切骨架规则，不放论文、问答和偏好业务。
5. `middleware/` 只放 HTTP 全局中间件。
6. `api/` 只放 HTTP 路由、Schema 和 Depends。
7. `services/` 只放业务规则和流程编排。
8. `infrastructure/` 只放数据库、文件系统、向量库和外部 API。
9. Router 不直接调用 SQL、Qdrant、文件系统或 HTTPX。
10. Service 不返回 HTTP Response，也不抛 HTTPException。
11. Store/Client 不决定业务文案和 HTTP 状态。
12. 业务错误统一通过 `AppError` 传播。
13. 成功响应显式建模，失败响应集中处理。
14. 不使用全局响应包装中间件。
15. 权限使用 Depends/Security，不使用通用权限中间件。
16. 健康检查分离 live、ready 和 details。
17. 所有共享资源由 lifespan 创建和关闭。
18. 不为未来假设提前建立通用抽象。
19. 不把 API 版本和模型版本混为一谈。
20. 当前业务接口固定使用 `/api`，直到确实出现不兼容版本需求。
