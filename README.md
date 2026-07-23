# Research Journey Agent

面向计算型科研人员的个人文献研究助手。

## 项目简介

Research Journey Agent 是一个以个人研究课题为中心的文献管理与知识问答系统。

用户可以上传科研论文，系统将自动完成 PDF 解析、文本分块、向量化和知识库索引。用户随后可以基于个人论文库进行问答，并获得带有论文名称、页码和原文片段的可追溯回答。

项目当前聚焦于单用户、单研究课题场景，优先实现稳定、可解释的文献入库和知识问答流程。

## 项目目标

本项目主要解决以下问题：

1. 科研论文数量增加后难以统一管理；
2. 阅读过的论文内容容易遗忘；
3. 查找论文中的具体方法、数据集和评价指标耗时较长；
4. 通用大模型回答科研问题时缺少个人论文库背景；
5. 普通 RAG 问答缺少可靠的页码和原文证据。

## 当前开发阶段

当前项目处于 MVP 开发阶段。

### 基础功能

- [ ] PDF 文件上传
- [ ] PDF 文件列表展示
- [ ] PDF 删除和重新索引
- [ ] PDF 文本解析
- [ ] 章节感知 + 字符递归文本分块
- [ ] Embedding 生成
- [ ] ChromaDB 向量存储
- [ ] 基于个人论文库的知识问答
- [ ] 论文名称和页码引用
- [ ] 原文证据片段展示
- [ ] 对话历史持久化
- [ ] 用户研究方向和回答偏好设置

### 计划功能

- [ ] 自动生成论文摘要
- [ ] 自动提取核心方法、数据集、评价指标和主要结果
- [ ] 多论文结构化对比
- [ ] 论文主题相关性分析
- [ ] OpenAlex 学术论文检索
- [ ] MinerU 复杂 PDF 解析
- [ ] 多模态图表检索与理解
- [ ] RAG 自动化评估

## 数据存储

文件系统
├── 原始 PDF
├── 解析后的 Markdown
├── 解析后的 JSON
└── 提取的图片和表格

SQLite
├── 论文元数据
├── 论文处理状态
├── 对话记录
├── 会话信息
└── 用户偏好

ChromaDB
├── 文本 Chunk
├── Embedding
├── 论文 ID
├── 页码
└── 章节信息

## 技术栈

+ Python 3.11
+ FastAPI
+ SQLite
+ ChromaDB
PyMuPDF
+ LangChain
OpenAI-compatible LLM API
+ Jinja2
原生 HTML、CSS 和 JavaScript

## 环境配置
1. 创建虚拟环境
conda create -n RJagent python=3.11 -y
conda activate RJagent
2. 安装python依赖
python -m pip install --upgrade pip
pip install -r requirements.txt
3. 配置环境变量
cp .env.example app/backend/.env
windows powershell启动：
Copy-Item .env.example app/backend/.env
4. 启动项目
uvicorn app.backend.main:app --reload

## 当前项目边界

为了优先完成可运行的 MVP，当前版本暂不实现：

多用户系统
知识图谱
完整多智能体系统
自动全文翻译
自动执行科研代码
Google Scholar 抓取
CNKI 非授权抓取
完整多模态图表问答

## 参考项目
本项目参考了以下开源项目的设计思想：

Agentic RAG Chatbot Hackathon：RAG、引用、Memory 和测试标准
Simple RAG Chatbot：基础 PDF 入库和 FastAPI 问答流程
All-in-RAG：RAG 基础知识与检索评估方法

本项目将独立实现文献管理、数据存储、上下文管理和论文分析功能，不直接复制现有项目代码。