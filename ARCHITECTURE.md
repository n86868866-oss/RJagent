# 系统流程

## 文献入库流程

上传 PDF
    ↓
格式校验与重复判断
    ↓
PDF 解析
    ↓
数据清洗，正文、图、表分流
    ↓
章节识别与文本分块
    ↓
元数据入SQLite
    ↓
生成 Embedding
    ↓
写入 Qdrant
    ↓
更新论文处理状态

## 知识问答流程

用户问题
    ↓
加载用户偏好和近期对话
    ↓
从 Qdrant 检索相关文本
    ↓
构建 LLM Context
    ↓
生成回答
    ↓
返回论文名称、页码和原文证据

## 项目架构
research-journey-agent/
├── app/
│   ├── backend/
│   │   ├── main.py                 # FastAPI 入口
│   │   ├── config.py               # 环境变量与配置
│   │   │
│   │   ├── clients/
│   │   │   ├── llm_client.py
│   │   │   ├── mineru_client.py
│   │   │   ├── text_embedding_client.py
│   │   │   └── visual_embedding_client.py
│   │   │
│   │   ├── stores/
│   │   │   ├── metadata_store.py
│   │   │   ├── vector_store.py
│   │   │   └── file_store.py
│   │   │
│   │   ├── services/
│   │   │   ├── papers/
│   │   │   │   ├── router.py
│   │   │   │   ├── schemas.py
│   │   │   │   ├── service.py
│   │   │   │   └── ingestion/
│   │   │   │       ├── pipeline.py
│   │   │   │       ├── models.py
│   │   │   │       ├── normalizer.py
│   │   │   │       ├── chunker.py
│   │   │   │       ├── embedder.py
│   │   │   │       └── indexer.py
│   │   │   │
│   │   │   ├── chat/
│   │   │   │   ├── router.py
│   │   │   │   ├── schemas.py
│   │   │   │   ├── service.py
│   │   │   │   ├── retrieval.py
│   │   │   │   └── agent/
│   │   │   │       ├── runner.py
│   │   │   │       ├── state.py
│   │   │   │       ├── tools.py
│   │   │   │       ├── prompts.py
│   │   │   │       └── validators.py
│   │   │   │
│   │   │   └── preferences/
│   │   │       ├── router.py
│   │   │       ├── schemas.py
│   │   │       └── service.py
│   │   │
│   │   └── .env
│   │
│   └── frontend/
│       ├── templates/index.html
│       └── static/
│           ├── app.js
│           └── styles.css
│
├── data/
│   ├── raw/
│   ├── parsed/
│   ├── assets/
│   ├── app.db
│   └── vectors/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── ARCHITECTURE.md

## 对话智能体MVP

### agent loop

结束条件: 理由是否充分能够生成回答/达到最大循环数量
    若否, 重新检索匹配, LLM推理
    若是, LLM输出回答

### 结果生成的三种情况

1. 系统正常运行，但论文库没有答案，正常业务结果；
2. Qdrant、数据库、Embedding 或模型调用失败，是运行错误；
3. 找到证据并通过引用校验．

### 证据足够判断条件（程序硬判断＋LLM 语义判断）

Harness 判断：

是否有检索结果；
分数是否达到经过评测校准的最低要求；
是否至少有一个有效 chunk_id；
引用是否来自检索结果；
引用页码、论文 ID 是否存在；
是否超过最大检索次数；
是否超过 Token 和调用预算。

LLM 判断：

证据是否真正回答用户的问题；
证据之间是否冲突；
是否缺少某个关键方面；
应如何改写下一次查询；
应回答、部分回答还是拒绝。

### 上下文设计

prompts + messages + tools

tools为数据库检索, messages暂时考虑最近三次的对话
prompts包含长期不变的规则：
+ 只能依据提供的论文证据回答；
+ 不允许虚构引用；
+ 引用必须指向给定 chunk_id；
+ 无证据时明确拒绝；
+ 区分论文原文与模型总结；
+ 不将对话历史当作论文证据。

### 启动自检
[ ] data/raw、parsed、assets、vectors 目录可写
[ ] SQLite 可连接并启用 WAL
[ ] Qdrant 可连接或本地目录可打开
[ ] collection 的向量维度与 embedding 配置一致
[ ] LLM API 配置完整
[ ] Embedding API 配置完整
[ ] MinerU 服务可访问
[ ] 必需的数据表和 schema version 存在

## 最低限度自检清单
1. 上传正常文本 PDF；
2. 上传扫描版 PDF；
3. 上传损坏文件和伪造 .pdf；
4. 上传重复论文；
5. MinerU 超时后状态正确；
6. chunk 保留页码和章节；
7. embedding 维度不一致时启动失败；
8. 删除论文后 SQLite、文件和向量都被清理；
9. 重新索引失败时旧索引仍可使用；
10. 问题无相关证据时明确拒答；
11. 返回的引用只允许来自检索结果；
12. Qdrant、SQLite、MinerU、LLM 失败时返回 runtime_error。


## 文本检索安全兜底处理(单元测试)

### Embedding Client

#### 正常路径
1. 单条 query 返回正确维度
2. 多条 document 保持数量和顺序
3. 324 条文本正确分批
4. text_index 乱序可以恢复
5. 真实 DashScope 集成调用成功
#### 输入错误
6. 空文本和纯空白文本被拒绝
#### 网络与 HTTP
7. 429 可以重试
8. 401 不重试
9. 连接超时可以重试
#### 响应协议
10. 向量维度错误
11. 返回数量错误
12. text_index 缺失
13. text_index 不连续
14. 返回不是 JSON

Ingestion Service
处理：
- 重复上传同一 PDF
- 重复 Chunk
- Chunk 与 paper_id、页码的关系
- 入库失败后的论文状态

Qdrant Store / Retrieval Service
处理：
- 按 Chunk 检索
- 重复检索结果
- Top-K
- 分数阈值
- 同一论文相邻 Chunk 合并

Agent / RAG 主循环
处理：
- 是否需要重新检索
- 证据是否充分
- 是否拒绝回答
- 如何组织引用

## FastAPI/Pydantic 提供的机制
| 能力                  | 框架提供程度 |
| ------------------- | ------ |
| ASGI 应用和路由          | 直接提供   |
| `APIRouter` 多文件路由   | 直接提供   |
| 请求参数提取              | 直接提供   |
| Pydantic 参数验证       | 直接提供   |
| 响应模型和 OpenAPI       | 直接提供   |
| 默认 422 验证错误         | 直接提供   |
| `HTTPException`     | 直接提供   |
| 全局异常处理器机制           | 直接提供   |
| `Depends` 依赖注入      | 直接提供   |
| 生命周期 `lifespan`     | 直接提供   |
| 中间件机制               | 直接提供   |
| CORS 等常见中间件         | 直接提供   |
| Swagger UI / ReDoc  | 直接提供   |
| OAuth2/API Key 基础工具 | 直接提供   |

## 自定义机制
| 能力                       | 项目自行定义 |
| ------------------------ | ------ |
| URL 命名规则                 | 是      |
| 什么是 Paper、Chunk、Citation | 是      |
| 论文处理状态机                  | 是      |
| 业务错误码                    | 是      |
| HTTP 状态码映射               | 是      |
| 重复上传规则                   | 是      |
| 删除和重新索引语义                | 是      |
| SQLite、文件和 Qdrant 一致性    | 是      |
| 哪些错误可以重试                 | 是      |
| 健康检查检查哪些组件               | 是      |
| 日志字段和脱敏规则                | 是      |
| 用户权限规则                   | 是      |
| Agent 预算和终止条件            | 是      |
| 目录结构                     | 是      |
