# 系统流程

## 文献入库流程

上传 PDF
    ↓
文件校验与去重
    ↓
PDF 解析
    ↓
章节识别与文本分块
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
│   │   │   ├── pymupdf_client.py
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