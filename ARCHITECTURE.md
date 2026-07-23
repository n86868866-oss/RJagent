# 系统流程

## 文献入库流程

```text
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
写入 ChromaDB
    ↓
更新论文处理状态
```

## 知识问答流程

用户问题
    ↓
加载用户偏好和近期对话
    ↓
从 ChromaDB 检索相关文本
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
|   |   |—— main.py            # FastAPI 入口
│   |   ├── config.py          # 环境变量与配置
│   │   ├── routes/
│   │   |   ├── papers.py           # 上传、删除、列表
│   │   |   ├── chat.py             # 问答
│   │   |   └── preferences.py      # 用户设置
│   |   |——services/
│   │   │   ├── ingestion.py        # 解析、分块、入库
│   │   │   └── retrieval.py        # Chroma 检索
│   |   |——agent/
│   │   │   ├── loop.py             # Agent Loop
│   │   │   ├── tools.py            # Tool 定义和分发
│   │   │   └── prompts.py
│   |   |——integrations/
│   │   │   ├── llm_client.py
│   │   │   ├── embedding_client.py
│   │   │   ├── pdf_parser.py
│   │   │   └── academic_search.py  # 后续加入
│   │   |——storage/
│   │   │   ├── metadata_db.py      # SQLite
│   │   │   ├── vector_store.py     # Chroma
│   │   │   └── file_store.py
│   │   └── .env
│   │   
│   └── frontend/
│       ├── templates/
│       │   └── index.html
│       └── static/
│           ├── app.js
│           └── styles.css
|
├── scripts/
│   ├── reindex.py
│   └── sanity.py
│
├── data/
│   ├── raw/
│   ├── parsed/
│   └── chroma/
│
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── ARCHITECTURE.md