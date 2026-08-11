# Research Journey Agent

面向计算型科研人员的个人文献研究助手。

## 项目简介

Research Journey Agent 是一个以个人研究课题为中心的文献管理与知识问答系统。

用户可以上传科研论文，系统将自动完成 PDF 解析、文本分块、向量化和知识库索引。用户随后可以基于个人论文库进行问答，并获得带有论文名称、页码和原文片段的可追溯回答。

项目当前聚焦于单用户、单研究课题场景，优先实现稳定、可解释的文献入库和知识问答流程。

## 项目价值

本项目主要解决以下问题：

1. 科研论文数量增加后难以统一管理；
2. 阅读过的论文内容容易遗忘；
3. 查找论文中的具体方法、数据集和评价指标耗时较长；
4. 通用大模型回答科研问题时缺少个人论文库背景；
5. 普通 RAG 问答缺少可靠的页码和原文证据。

## 目标功能

### 基础功能

- [ ] PDF 文件上传
- [ ] PDF 文件列表展示
- [ ] PDF 删除和重新索引
- [ ] PDF 文本解析
- [ ] 章节感知 + 字符递归文本分块
- [ ] 文本索引 + 视觉索引双嵌入模型
- [ ] Qdrant 向量存储
- [ ] 稠密检索
- [ ] 基于个人论文库的知识问答
- [ ] 论文名称和页码引用
- [ ] 原文证据片段展示
- [ ] 对话历史持久化
- [ ] 用户研究方向和回答偏好设置

### 计划功能

- [ ] 自动生成论文简要概述,包括核心方法、数据集、评价指标和主要结果等
- [ ] 多论文结构化对比
- [ ] 论文主题相关性分析
- [ ] 谷歌学术、arxiv和知网三个平台论文的检索和自动推荐
- [ ] 多模态图表检索与理解
- [ ] RAG 自动化评估
- [ ] “稠密+稀疏”混合检索

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

Qdrant
├── 文本 Chunk
├── Embedding
├── 论文 ID
├── 页码
└── 章节信息

## 技术栈

+ Python 3.11
+ FastAPI
+ SQLite
+ Qdrant
+ PyMuPDF和MinerU
+ LangChain
+ text-embedding-v4和bge-visualized-m3
+ OpenAI-compatible LLM API
+ Jinja2
+ 原生 HTML、CSS 和 JavaScript

## 环境配置

### 创建主应用环境
1. 虚拟环境创建
conda create -n RJagent python=3.11 -y
conda activate RJagent
2. python包依赖安装
python -m pip install --upgrade pip
pip install -r requirements.txt
3. 保存依赖快照
pip check
pip freeze > requirements-lock.txt

### mineru独立环境配置（mineru[all]==3.4.4）
1. 虚拟环境创建
conda create -n rjagent-mineru python=3.11 -y
conda activate rjagent-mineru
2. mineru安装
python -m pip install --upgrade pip
pip install "mineru[all]==3.4.4"
3. 保存依赖快照
pip check
pip freeze > requirements-mineru-lock.txt

### 启动mineru服务
conda activate rjagent-mineru
mineru-api --host 127.0.0.1 --port 8001
访问 http://127.0.0.1:8001/docs 验证服务

### 配置主应用 
1. 配置env 环境变量
linux：cp .env.example app/backend/.env
cmd：copy /Y .env.example app\backend\.env
PowerShell: Copy-Item .env.example app\backend\.env
2. 访问阿里云平台获取LLM和text embedding的url、api、model
https://help.aliyun.com/zh/model-studio/embedding-interfaces-compatible-with-openai?spm=a2c4g.11186623.help-menu-2400256.d_2_10_7.3f65609f9VYUnR
3. 若启用 Cookie Session，生成 APP_SECRET_KEY(可选)
python -c "import secrets; print(secrets.token_urlsafe(48))"

### 启动qdrant服务（本地服务模式）
docker volume create qdrant_storage
docker run -d --name qdrant -p 127.0.0.1:6333:6333 -p 127.0.0.1:6334:6334 -v qdrant_storage:/qdrant/storage qdrant/qdrant:latest

### 启动主应用
conda activate RJagent
uvicorn app.backend.main:app --reload --host 127.0.0.1 --port 8000
访问 http://127.0.0.1:8000/docs 验证服务
访问 http://127.0.0.1:8000/health/live、 http://127.0.0.1:8000/health/ready、http://127.0.0.1:8000/health/details 检查程序健康状态
访问 http://127.0.0.1:6333/dashboard 查看qdrant数据库

### 单元/集成测试
1. 设置环境变量（集成单元全测试）
cmd：set RUN_DASHSCOPE_INTEGRATION_TEST=1
powershell：$env:RUN_DASHSCOPE_INTEGRATION_TEST="1"
Linux：RUN_DASHSCOPE_INTEGRATION_TEST=1
2. 测试
python -m app.backend.units.check_text_embedding
3. 清除环境变量（仅单元测试）
cmd：set RUN_DASHSCOPE_INTEGRATION_TEST=
powershell：Remove-Item Env:RUN_DASHSCOPE_INTEGRATION_TEST
Linux：unset RUN_DASHSCOPE_INTEGRATION_TEST

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
hello-agents: agent 系统框架设计

本项目将独立实现文献管理、数据存储、上下文管理和论文分析功能，不直接复制现有项目代码。