# Research Journey Agent 当前系统架构

> 文档状态：当前实现快照
>
> 核对日期：2026-09-28
>
> 适用范围：单用户、单研究课题、后端技术 MVP

本文只描述仓库当前实现。后端的约束、扩展方式和验收规则见 [后端骨架设计](ARCHITECTURE_BACKEND_SKELETON_REVISED.md)，项目启动方式见 [README](README.md)。

## 1. 系统目标与边界

当前系统负责四类能力：

1. 上传 PDF，调用 MinerU 解析并规范化论文内容。
2. 将文本切块，生成稠密向量与 BM25 稀疏向量，写入 Qdrant。
3. 对问题进行混合召回、重排，并返回可检查的候选段落。
4. 让 LLM 基于检索证据生成带引用的中文回答。

当前实现不是多用户知识库平台，不包含认证授权、任务队列、分布式事务、后台管理和完善的偏好系统。`preferences` 路由目前只是占位。

## 2. 总体结构

```text
客户端
  │ HTTP
  ▼
FastAPI 路由
  ├─ /health/*                 健康检查
  └─ /api/*                    业务接口
       │ Depends 组装
       ▼
业务服务
  ├─ PaperService              论文入库与删除编排
  ├─ Retriever                 混合召回与重排
  ├─ ChatService               检索代理与证据回答
  └─ HealthService             组件探测与状态汇总
       │ 构造函数注入
       ▼
基础设施适配器
  ├─ SQLite / MetadataStore
  ├─ FileStore
  ├─ Qdrant / VectorStore
  ├─ EmbeddingClient / BM25Encoder
  ├─ RerankerClient
  ├─ MinerUClient
  ├─ LLMClient
  └─ VisualEmbeddingClient
```

依赖方向固定为：

```text
api → services → infrastructure
          ↓
        models

main → api + services + infrastructure
core / middleware 为横切能力
```

服务层不导入 FastAPI。基础设施层不解释“论文已存在”“论文不存在”等业务语义。

## 3. 后端目录

```text
app/backend/
├─ main.py
├─ config.py
├─ api/
│  ├─ router.py
│  ├─ dependencies.py
│  └─ routes/
│     ├─ health.py
│     ├─ papers.py
│     ├─ chat.py
│     └─ preferences.py
├─ core/
│  ├─ responses.py
│  ├─ exceptions.py
│  ├─ exception_handlers.py
│  └─ logging.py
├─ middleware/
│  ├─ request_context.py
│  └─ access_log.py
├─ services/
│  ├─ health/
│  │  ├─ health_service.py
│  │  └─ models.py
│  ├─ papers/
│  │  ├─ paper_service.py
│  │  ├─ models.py
│  │  └─ ingestion/
│  │     ├─ normalizer.py
│  │     ├─ content_cleaner.py
│  │     ├─ document_builder.py
│  │     └─ chunker.py
│  └─ chat/
│     ├─ chat.py
│     ├─ retriver.py
│     └─ model.py
└─ infrastructure/
   ├─ clients/
   │  ├─ embedding_client.py
   │  ├─ reranker_client.py
   │  ├─ mineru_client.py
   │  ├─ llm_client.py
   │  └─ visual_embedding_client.py
   └─ stores/
      ├─ sqlite.py
      ├─ metadata_store.py
      ├─ vector_store.py
      └─ file_store.py
```

`api/schemas` 已取消。请求和响应模型归属于提供该能力的业务模块，例如聊天模型位于 `services/chat/model.py`，健康模型位于 `services/health/models.py`。这样路由和服务不再维护两份同字段定义。

## 4. 应用生命周期与依赖注入

`main.py` 是组合根。应用启动时按顺序创建：

1. 文件目录与可写性检查。
2. SQLite 连接和元数据表。
3. Qdrant 向量存储。
4. Embedding、BM25、Reranker、LLM、MinerU 和可选视觉向量客户端。
5. 将共享资源写入 `app.state`，最后设置 `app.state.ready = True`。

可关闭资源注册到 `AsyncExitStack`，关闭时先撤销 ready 状态，再按逆序关闭。

`api/dependencies.py` 只做两件事：

- 从 `app.state` 提供应用级共享资源；资源缺失时抛出固定 503 的 `ServiceUnavailableError`。
- 通过原生 `Depends` 组合请求所需服务。

业务类继续使用普通构造函数注入，因此可以在测试、脚本或未来 CLI 中脱离 FastAPI 创建。FastAPI 在一次请求内缓存相同依赖，并允许使用 `dependency_overrides` 替换任意节点。

## 5. 核心业务流程

### 5.1 论文上传

```text
POST /api/papers
  → PaperService 校验 PDF 类型、签名和大小
  → FileStore 保存临时文件
  → MinerU 标题预解析
  → MetadataStore 查询论文名称
  → MinerU 全文解析
  → normalizer / document_builder / chunker
  → EmbeddingClient + BM25Encoder
  → VectorStore 写入混合向量
  → FileStore 保存解析产物并归档原 PDF
  → MetadataStore 写入论文与切块元数据
  → 返回 paper_id、paper_name、page_count
```

业务层对可预见的重名返回 409。SQLite 的唯一约束仍是并发安全的最后防线；当前并发窗口内发生的底层唯一约束错误作为非预期数据库错误进入全局 500 处理，这是后续可单独优化的事务边界。

上传失败时，`PaperService` 尝试删除本次已写入的向量和文件，并始终清理临时目录。补偿失败会在本地记录，因为异常被消费；它不会覆盖原始失败。

### 5.2 检索与重排

```text
POST /api/chat/query
  → 查询文本生成稠密向量和 BM25 稀疏向量
  → Qdrant 混合召回
  → Reranker 重排
  → 返回 Candidate 列表
```

候选结果包含论文、章节、切块、正文、页码、混合分数和重排分数，便于当前研究阶段检查召回质量。

### 5.3 带证据问答

```text
POST /api/chat/chat_query
  → ChatService 调用 LLM
  → LLM 通过 retrieve_paper 工具请求检索
  → Retriever 返回候选证据
  → 最多执行限定次数的补充检索
  → 校验引用编号
  → 返回 answer 与 sources
```

每个答案结论必须引用已注册证据。无证据时返回固定拒答文案；未知工具、非法工具参数、无效引用等属于内部模型输出校验，使用原生数据异常进入统一处理。

### 5.4 删除论文

`DELETE /api/papers/{paper_id}` 先由业务层确认论文存在，再依次删除向量、论文文件和 SQLite 元数据。成功返回 HTTP 204，无 JSON 响应体。当前跨 SQLite、Qdrant 和文件系统的删除不是原子事务。

## 6. 数据与模型所有权

| 模型 | 位置 | 用途 |
| --- | --- | --- |
| `PaperParseResult`、`PaperChunk`、`PaperRecordResult` | `services/papers/models.py` | 论文服务结果、切块和存储传输 |
| `ChatQueryRequest`、`Candidate`、`ChatAnswerResult` | `services/chat/model.py` | 聊天输入、检索输出和回答结果 |
| `HealthCheckResult`、`ComponentCheckResult` | `services/health/models.py` | 完整健康检查结果 |
| `LivenessData`、`ReadinessData` | `services/health/models.py` | 健康接口的公开视图 |
| `ApiResponse[T]`、分页模型 | `core/responses.py` | 跨业务的 HTTP 外层结构 |

同一语义、同一字段集合只定义一次。只有当公开接口必须隐藏内部字段时，才建立显式投影，例如 `/health/ready` 不返回探针地址和错误详情，而 `/health/details` 返回完整健康结果。

## 7. API 契约

除 204、重定向等无 JSON 场景外，响应外层固定为：

```json
{
  "code": 200,
  "message": "请求成功",
  "data": {},
  "request_id": "..."
}
```

- `code` 与 HTTP 状态一致，不另造业务数字码。
- `message` 是可向用户展示的中文摘要。
- `data` 只承载该接口需要的业务数据。
- `request_id` 与响应头 `X-Request-ID` 一致，用于关联日志。

当前端点：

| 方法与路径 | 成功状态 | 数据 |
| --- | --- | --- |
| `GET /` | 200 | 应用名称、版本、运行状态、健康地址 |
| `GET /api` | 200 | 业务路由状态 |
| `GET /health/live` | 200 | 进程存活信息 |
| `GET /health/ready` | 200 / 503 | 总体状态及各组件的 `status/required` |
| `GET /health/details` | 200 / 503 / 404 | 完整探针结果；可由配置关闭 |
| `POST /api/papers` | 201 | `paper_id/paper_name/page_count` |
| `DELETE /api/papers/{paper_id}` | 204 | 无响应体 |
| `POST /api/chat/query` | 200 | 检索候选列表 |
| `POST /api/chat/chat_query` | 200 | 答案与引用来源 |

## 8. 异常与状态码

### 8.1 项目异常

`core/exceptions.py` 同时保存中文 HTTP 文案、`message_for_http_status()` 和两个异常类型：

- `AppError`：预期的应用拒绝，携带 HTTP 状态、安全中文 `message` 和仅用于日志的 `context`。
- `ServiceUnavailableError`：`AppError` 的 503 快捷子类，用于资源尚未配置或尚未初始化；它复用 `AppError` 处理器，没有单独注册。

文件系统、SQLite、HTTPX、OpenAI、gRPC 和 Qdrant 错误优先保留原异常类型，统一在 HTTP 边界映射。

### 8.2 映射规则

| 情况 | HTTP 状态 |
| --- | --- |
| FastAPI 请求校验失败 | 400 |
| 业务资源不存在、冲突、文件过大、格式不支持 | 404 / 409 / 413 / 415 |
| 资源未配置或未初始化 | 503 |
| 连接错误、传输错误、超时 | 503 |
| 依赖明确返回 408、429、502、503、504 | 503 |
| SQLite busy/locked、gRPC unavailable/deadline/resource-exhausted | 503 |
| 文件 I/O、非预期数据库错误、依赖数据格式错误、程序错误 | 500 |

502 和 504 仍有中文文案，供显式 `HTTPException` 或未来真正的网关场景使用；它们不是底层依赖错误的默认值。错误响应不包含 SDK 原文、文件路径、上游响应体或异常上下文。

## 9. 日志与请求追踪

每个 HTTP 请求由两层中间件处理：

1. `request_context_middleware` 生成 request ID，写入 ContextVar、`request.state` 和响应头。
2. `access_log_middleware` 记录请求开始、结束状态和耗时。

异常日志遵循“一个失败路径只记录一次”：

- 会继续传播到 HTTP 边界的异常，由全局异常处理器统一记录。
- `AppError` 的 4xx 使用 WARNING，不带堆栈；它表示预期的请求拒绝。
- `AppError` 的 5xx、依赖异常和未知异常使用 ERROR，并记录堆栈。
- 客户端重试耗尽时不重复打印；重试说明附加到原异常，保留原类型和堆栈。
- 健康探针和补偿清理会消费异常，因此在消费处记录。
- 访问日志记录状态和耗时，不重复记录异常堆栈。

## 10. 健康检查

健康能力位于 `services/health/`：

- `/health/live` 只确认 FastAPI 进程可应答。
- `/health/ready` 只执行配置为必选的组件；其他组件标记为 `unchecked`。
- `/health/details` 探测所有启用组件并返回诊断字段，可通过 `HEALTH_DETAILS_ENABLED` 关闭。

当前默认必选组件为：

```text
filesystem, sqlite, qdrant, text_embedding, reranker
```

MinerU、LLM 和视觉向量默认不阻断 readiness，但部署可以通过 `HEALTH_REQUIRED_COMPONENTS` 修改。每个探针有独立超时。可选组件失败不会使整体状态变为 `not_ready`；必选组件失败会返回 HTTP 503。

## 11. 存储与索引

- SQLite 保存论文、文档元数据和切块元数据，启用外键，可配置 WAL 与 busy timeout。
- FileStore 管理临时上传、原始 PDF 和 MinerU 解析产物，并阻止删除数据根目录以外的路径。
- Qdrant 保存命名稠密向量 `dense` 与启用 IDF 的稀疏向量 `sparse`，集合结构在初始化时校验。
- BM25 模型按首次使用惰性加载。
- 远端且非必选的 Qdrant 可以延迟到首次使用时初始化；必选或本地 Qdrant 在启动期检查。

## 12. 当前限制与技术债

1. 上传和删除跨 SQLite、Qdrant、文件系统，只有尽力补偿，没有事务一致性保证。
2. 同名论文的预检查存在并发窗口；数据库约束能防重复，但晚到冲突目前返回 500。
3. 配置仍保留 DashScope 和 PyMuPDF 的历史字段，当前运行时只创建本地 TEI `EmbeddingClient`，且 PyMuPDF 客户端已删除。
4. `preferences` 只有空路由。
5. 认证授权和多用户隔离尚未实现。
6. 日志已有 request ID、分级和轮转，尚无独立的敏感字段脱敏 Filter。
7. 删除论文的跨存储操作失败时可能留下部分资源，需要后续增加幂等恢复或定期对账。

## 13. 验证基线

后端测试分为业务单元测试、HTTP 契约测试和混合检索集成测试，覆盖问答编排、论文流程、统一响应、request ID、异常映射、健康检查及内存 Qdrant 检索。当前相关回归结果为 46 项通过。

```powershell
python -m pytest app/backend/tests -q -p no:cacheprovider
```
