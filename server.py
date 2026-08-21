import json
import os
import re
import urllib.parse
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

import faiss
import numpy as np
import requests
from docx import Document
from sentence_transformers import SentenceTransformer

import config

DOCS_FOLDER = "./docs"
ALLOW_SUFFIX = {".txt", ".md", ".docx"}


def read_docx(file_path):
    """读取docx word文档文本"""
    doc = Document(file_path)
    full_text = []
    for para in doc.paragraphs:
        full_text.append(para.text)
    return "\n".join(full_text)


def load_documents_from_directory(folder_path: str):
    """读取文件夹下 .txt .md .docx 文件"""
    documents = []
    sources = []
    errors = []
    # 如果文件夹不存在，自动创建docs文件夹
    if not os.path.exists(folder_path):
        os.mkdir(folder_path)
        errors.append(f"文件夹不存在，已自动新建：{folder_path}")
        return documents, sources, errors

    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if os.path.isdir(file_path):
            continue
        suffix = os.path.splitext(filename)[1].lower()
        if suffix not in ALLOW_SUFFIX:
            continue
        try:
            if suffix == ".docx":
                content = read_docx(file_path)
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            content = re.sub(r"\n+", "\n", content).strip()
            documents.append(content)
            sources.append(file_path)
        except Exception as e:
            errors.append(f"{file_path} 读取失败: {str(e)}")
    return documents, sources, errors


# ---------------------- 文件路径 ----------------------
index_file_path = "m3e_faiss_index.bin"
chunks_map_path = "chunks_mapping.npy"

# ---------------------- 2.文本分块函数 ----------------------
def chunk_document(text, chunk_size=400 , overlap=20):
    """简单滑动窗口分块"""
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end]
        chunks.append(chunk)
        start = start + chunk_size - overlap
    return chunks

# ---------------------- 3.向量模型 + FAISS检索 ----------------------
model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
dim = model.get_sentence_embedding_dimension()

all_chunks = []
doc_to_chunks = dict()
chunks_to_doc = dict()
sources = []
index = faiss.IndexFlatIP(dim)


def load_index_from_file():
    """从本地磁盘加载已有索引"""
    global index, doc_to_chunks, chunks_to_doc, all_chunks, sources
    print(f"从本地加载索引: {index_file_path}")
    index = faiss.read_index(index_file_path)
    mapping_data = np.load(chunks_map_path, allow_pickle=True).item()
    doc_to_chunks = mapping_data["doc_to_chunks"]
    chunks_to_doc = mapping_data["chunks_to_doc"]
    all_chunks = mapping_data["all_chunks"]
    sources = mapping_data.get("sources", [])


def rebuild_index(folder_path: str = DOCS_FOLDER):
    """读取文档目录并重建 FAISS 索引"""
    global index, doc_to_chunks, chunks_to_doc, all_chunks, sources

    documents, new_sources, errors = load_documents_from_directory(folder_path)
    all_chunks = []
    doc_to_chunks = {}
    chunks_to_doc = {}
    sources = new_sources

    if len(documents) == 0:
        index = faiss.IndexFlatIP(dim)
        print("当前没有可用文档，索引为空")
        return errors

    for doc_id, doc in enumerate(documents):
        chunks = chunk_document(doc)
        doc_to_chunks[doc_id] = []
        for chunk in chunks:
            chunk_id = len(all_chunks)
            all_chunks.append(chunk)
            doc_to_chunks[doc_id].append(chunk_id)
            chunks_to_doc[chunk_id] = doc_id

    chunk_embeds = model.encode(all_chunks, normalize_embeddings=True)
    chunk_embeds = np.array(chunk_embeds, dtype=np.float32)

    index = faiss.IndexFlatIP(dim)
    index.add(chunk_embeds)

    faiss.write_index(index, index_file_path)
    mapping_save = {
        "doc_to_chunks": doc_to_chunks,
        "chunks_to_doc": chunks_to_doc,
        "all_chunks": all_chunks,
        "sources": sources,
    }
    np.save(chunks_map_path, mapping_save)
    print("索引与分块映射文件保存完成")
    return errors


def list_documents(folder_path: str = DOCS_FOLDER):
    """列出 docs 目录下的文档"""
    if not os.path.exists(folder_path):
        os.mkdir(folder_path)
        return []

    files = []
    for filename in sorted(os.listdir(folder_path)):
        file_path = os.path.join(folder_path, filename)
        if os.path.isdir(file_path):
            continue
        suffix = os.path.splitext(filename)[1].lower()
        if suffix not in ALLOW_SUFFIX:
            continue
        stat = os.stat(file_path)
        files.append({
            "name": filename,
            "path": file_path.replace("\\", "/"),
            "size": stat.st_size,
        })
    return files


if os.path.exists(index_file_path) and os.path.exists(chunks_map_path):
    load_index_from_file()
else:
    print("本地索引不存在，读取 ./docs 文档并创建新索引")
    init_errors = rebuild_index()
    for err in init_errors:
        print("读取警告：", err)
    if len(all_chunks) == 0:
        print("警告：暂无文档，可通过 /api/upload 上传")




def retrieve_context(query: str, top_k=2, score_threshold=None):
    """检索最相关文本块；返回 context、scores、sources 及原始检索结果"""
    threshold = score_threshold if score_threshold is not None else config.RAG_SCORE_THRESHOLD
    if len(all_chunks) == 0:
        return "", np.array([]), [], False

    top_k = min(top_k, len(all_chunks))
    q_emb = model.encode(query, normalize_embeddings=True)
    q_emb = np.array([q_emb], dtype=np.float32)
    scores, ids = index.search(q_emb, k=top_k)

    max_score = float(scores[0][0]) if len(scores[0]) else 0.0
    if max_score < threshold:
        return "", scores[0], [], False

    context_parts = []
    source_names = []
    for chunk_id in ids[0]:
        context_parts.append(all_chunks[chunk_id])
        doc_id = chunks_to_doc[chunk_id]
        file_path = sources[doc_id]
        source_names.append(file_path)

    context_text = "\n".join(context_parts)
    return context_text, scores[0], source_names, True


# ---------------------- 4.联网搜索 + 大模型 ----------------------


def web_search(query: str, max_results: int | None = None) -> list[dict]:
    """联网搜索，优先 Tavily（需 API Key），否则 DuckDuckGo"""
    max_results = max_results or config.WEB_SEARCH_MAX_RESULTS
    if config.TAVILY_API_KEY:
        results = _web_search_tavily(query, max_results)
        if results:
            return results
    return _web_search_duckduckgo(query, max_results)


def _web_search_tavily(query: str, max_results: int) -> list[dict]:
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": config.TAVILY_API_KEY,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
            timeout=config.WEB_SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
            }
            for item in data.get("results", [])
            if item.get("url")
        ]
    except Exception as e:
        print(f"Tavily 搜索失败: {e}")
        return []


def _web_search_duckduckgo(query: str, max_results: int) -> list[dict]:
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible; RAGBot/1.0)"},
            timeout=config.WEB_SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
        html = resp.text
        results = []
        blocks = re.split(r'<div class="result results_links', html)
        for block in blocks[1 : max_results + 1]:
            title_m = re.search(
                r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                block,
                re.S,
            )
            snippet_m = re.search(r'class="result__snippet"[^>]*>(.*?)</', block, re.S)
            if not title_m:
                continue
            url = title_m.group(1)
            title = re.sub(r"<.*?>", "", title_m.group(2)).strip()
            snippet = re.sub(r"<.*?>", "", snippet_m.group(1)).strip() if snippet_m else ""
            if url.startswith("//"):
                url = "https:" + url
            results.append({"title": title, "url": url, "snippet": snippet})
        return results
    except Exception as e:
        print(f"DuckDuckGo 搜索失败: {e}")
        return []


def format_web_context(search_results: list[dict]) -> str:
    blocks = []
    for i, item in enumerate(search_results, 1):
        blocks.append(
            f"[{i}] {item.get('title', '无标题')}\n"
            f"链接：{item.get('url', '')}\n"
            f"摘要：{item.get('snippet', '')}"
        )
    return "\n\n".join(blocks)


def build_system_message(kb_context: str = "", web_context: str = "") -> str:
    kb_block = kb_context.strip() or "（无）"
    web_block = web_context.strip() or "（无）"
    return f"""你是本系统的知识库问答助手，请自然、简洁地回复用户。

规则：
- 优先使用「知识库资料」；若无相关内容，再用「联网资料」；都没有则用常识回答；
- 结合对话历史理解用户追问（如「北京呢」「继续」等）；
- 禁止拒答，禁止介绍自己是 DeepSeek 或其他模型；
- 问候语（如你好）简短友好即可，不要展开自我介绍。

知识库资料：
{kb_block}

联网资料：
{web_block}"""


def normalize_history(raw_messages: list | None) -> list[dict]:
    result = []
    for item in raw_messages or []:
        role = item.get("role")
        if role not in ("user", "assistant"):
            continue
        content = (item.get("content") or "").strip()
        if not content or content.startswith("[错误]"):
            continue
        result.append({"role": role, "content": content})
    return result


def trim_history(messages: list[dict], max_turns: int | None = None) -> list[dict]:
    limit = max_turns if max_turns is not None else config.CHAT_MEMORY_MAX_TURNS
    if limit <= 0:
        return []
    max_messages = limit * 2
    if len(messages) <= max_messages:
        return messages
    return messages[-max_messages:]


def build_chat_messages(
    history: list | None,
    question: str,
    kb_context: str = "",
    web_context: str = "",
) -> list[dict]:
    messages = [{"role": "system", "content": build_system_message(kb_context, web_context)}]
    messages.extend(trim_history(normalize_history(history)))
    messages.append({"role": "user", "content": question})
    return messages


def build_prompt(question: str, kb_context: str = "", web_context: str = "") -> str:
    system = build_system_message(kb_context, web_context)
    return f"{system}\n\n用户：{question}"


def prepare_chat(
    question: str,
    top_k: int = 5,
    enable_web: bool = False,
    model_id: str | None = None,
    history: list | None = None,
):
    """决定回答模式；组装含历史的多轮 messages"""
    model = config.resolve_model(model_id)
    context, scores, _, hit = retrieve_context(question, top_k)
    kb_context = context if hit and context else ""
    web_context = ""
    mode = "llm"

    if hit and context:
        mode = "rag"
    elif enable_web:
        search_results = web_search(question)
        if search_results:
            web_context = format_web_context(search_results)
            mode = "web_search"

    messages = build_chat_messages(history, question, kb_context, web_context)
    return {
        "mode": mode,
        "messages": messages,
        "sources": [],
        "scores": scores,
        "model": model,
    }


def llm_headers():
    return {
        "Authorization": f"Bearer {config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }


def llm_answer(question: str, context: str, model_id: str | None = None):
    messages = build_chat_messages([], question, kb_context=context)
    return llm_answer_messages(messages, model_id)


def llm_answer_messages(messages: list, model_id: str | None = None):
    model = config.resolve_model(model_id)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
    }
    resp = requests.post(
        f"{config.LLM_BASE_URL}/chat/completions",
        json=payload,
        headers=llm_headers(),
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def llm_answer_prompt(prompt: str, model_id: str | None = None):
    return llm_answer_messages([{"role": "user", "content": prompt}], model_id)


def llm_stream(question: str, context: str, model_id: str | None = None):
    messages = build_chat_messages([], question, kb_context=context)
    yield from llm_stream_messages(messages, model_id)


def llm_stream_messages(messages: list, model_id: str | None = None):
    """流式生成回答，逐块 yield 文本"""
    model = config.resolve_model(model_id)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "stream": True,
    }
    resp = requests.post(
        f"{config.LLM_BASE_URL}/chat/completions",
        json=payload,
        headers=llm_headers(),
        stream=True,
        timeout=120,
    )
    resp.raise_for_status()

    for raw_line in resp.iter_lines(decode_unicode=True):
        if not raw_line or not raw_line.startswith("data: "):
            continue
        data_str = raw_line[6:].strip()
        if data_str == "[DONE]":
            break
        chunk = json.loads(data_str)
        delta = chunk["choices"][0].get("delta", {})
        content = delta.get("content")
        if content:
            yield content


def llm_stream_prompt(prompt: str, model_id: str | None = None):
    yield from llm_stream_messages([{"role": "user", "content": prompt}], model_id)


# ---------------------- 5.主流程运行 ----------------------
if __name__ == "__main__":
    user_query = "数字孪生这个项目核心技术栈具体有哪些"
    context, score, source_list, hit = retrieve_context(user_query, top_k=5)

    print("===检索来源文件===")
    print(source_list)
    print("===检索到的上下文===")
    print(context)
    print("\n===AI回答===")
    ans = llm_answer(user_query, context)
    print(ans)