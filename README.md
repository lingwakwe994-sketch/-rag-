# RAG 智能问答系统

一个基于 FastAPI、Vue 3、FAISS 和 Sentence Transformers 的本地知识库问答项目。用户可以上传文档，系统将文档切分并建立向量索引，再结合大语言模型生成回答。

## 功能

- 本地知识库文档管理
- 基于 FAISS 的向量检索
- DeepSeek 等 OpenAI 兼容接口的模型问答
- 流式对话输出
- 多会话历史记录
- 可选联网搜索
- 支持 `.txt`、`.md`、`.docx` 文档上传

> 当前版本默认不读取 PDF。PDF 请先转换为 `.docx`、`.md` 或 `.txt`，再上传。

## 项目结构

```text
rag/
├── ap.py                  # FastAPI 应用入口
├── server.py              # 文档读取、切分、向量检索和模型调用
├── database.py            # SQLite 会话和文档数据
├── config.py              # 配置加载
├── config.example.json    # 配置模板
├── requirements.txt       # Python 依赖
├── start.bat              # Windows 一键启动脚本
├── docs/                  # 知识库文档目录
├── frontend/              # Vue + Vite 前端源码
├── static/                # 前端构建产物
└── rag.db                 # SQLite 数据库（运行后生成或更新）
```

## 环境要求

- Windows 10/11
- Python 3.10 或更高版本
- Node.js 18 或更高版本（仅前端开发或重新构建时需要）
- 可访问模型服务 API

## 快速开始

### 1. 准备 Python 环境

在项目根目录执行：

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果项目已经包含 `venv`，可以直接执行第二条命令。

### 2. 配置模型 API

复制配置模板：

```powershell
Copy-Item config.example.json config.json
```

编辑 `config.json`，填写模型服务密钥：

```json
{
  "llm": {
    "api_key": "你的模型API密钥",
    "base_url": "https://api.deepseek.com/v1",
    "default_model": "deepseek-v4-flash"
  }
}
```

也可以使用环境变量，避免把密钥写入文件：

```powershell
$env:LLM_API_KEY = "你的模型API密钥"
```

不要把真实 API Key 提交到 GitHub。建议将 `config.json` 加入 `.gitignore`。

### 3. 启动后端

打开第一个 PowerShell 窗口：

```powershell
cd C:\Users\lenovo\Desktop\rag
.\venv\Scripts\python.exe .\ap.py
```

后端地址：`http://127.0.0.1:8000`

首次启动可能会下载 `BAAI/bge-small-zh-v1.5` 向量模型，需要网络连接。

### 4. 启动前端开发服务器

打开第二个 PowerShell 窗口：

```powershell
cd C:\Users\lenovo\Desktop\rag\frontend
npm install
npm run dev
```

浏览器访问：`http://localhost:5173`

Vite 会将 `/api` 和 `/chat` 请求代理到后端 `127.0.0.1:8000`，因此两个窗口都必须保持运行。

## 一键启动

如果前端已经构建到 `static/`，可以在项目根目录双击 `start.bat`。脚本会检查依赖、必要时构建前端，然后启动后端。

如果提示找不到 Vite，请先执行：

```powershell
cd frontend
npm install
npm run build
```

然后重新运行 `start.bat`，访问 `http://127.0.0.1:8000`。

## 使用知识库

1. 打开网页后点击“文档管理”。
2. 上传 `.txt`、`.md` 或 `.docx` 文件，或者将文件放入项目的 `docs/` 目录。
3. 如果是手动放入的文件，点击知识库面板的刷新按钮。
4. 建立索引后，在聊天框提问。

上传接口会自动重建 FAISS 索引。已有索引文件为 `m3e_faiss_index.bin` 和 `chunks_mapping.npy`。

## 常见问题

### 前端提示 `ECONNREFUSED 127.0.0.1:8000`

后端没有运行。请在另一个窗口执行：

```powershell
.\venv\Scripts\python.exe .\ap.py
```

### 输入 `ap.py` 后打开了 VS Code

这是 Windows 的文件关联行为。请使用 Python 显式运行：

```powershell
.\venv\Scripts\python.exe .\ap.py
```

### 知识库显示 0 个文档

检查文件扩展名是否为 `.txt`、`.md` 或 `.docx`，并点击刷新。PDF 当前不会被识别。

### 后端启动时下载模型失败

请检查网络连接，确保可以访问 Hugging Face 模型仓库；也可以预先下载模型并配置本地模型路径。

## API 健康检查

后端启动后访问：

```text
http://127.0.0.1:8000/api/health
```

正常时会返回 JSON 状态信息。

## 安全说明

- 不要提交 `config.json`、API Key、数据库文件或个人文档。
- 生产环境请限制 CORS 来源，不要使用 `allow_origins=["*"]`。
- 使用联网搜索时，注意第三方 API 的额度和隐私政策。

## 停止服务

在运行后端或前端的终端窗口按 `Ctrl+C`。

