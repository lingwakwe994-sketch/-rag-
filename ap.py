import json
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn

import config
import database
import server

API_VERSION = "prompt-v7-memory"
print(f"[RAG] 已加载 server.py，API 版本: {API_VERSION}")

app = FastAPI(title="RAG API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str
    top_k: int = 5
    enable_web: bool = False
    model: str | None = None


class StreamChatRequest(BaseModel):
    question: str
    top_k: int = 5
    session_id: int
    enable_web: bool = False
    model: str | None = None


class SessionCreateRequest(BaseModel):
    title: str = "新对话"


MODE_LABELS = {
    "rag": "知识库",
    "llm": "模型",
    "web_search": "联网",
}


def _format_assistant_content(text: str, sources: list, mode: str) -> str:
    return text


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": API_VERSION}


@app.get("/api/config")
async def get_app_config():
    return config.public_config()


@app.get("/index")
async def show_index():
    return {"message": "RAG 问答服务已启动"}


@app.get("/api/sessions/init")
async def init_sessions():
    conversation_id = database.ensure_default_conversation()
    sessions = database.list_conversations()
    return {"session_id": conversation_id, "sessions": sessions}


@app.get("/api/sessions")
async def list_sessions():
    sessions = database.list_conversations()
    if not sessions:
        conversation_id = database.create_conversation("新对话")
        sessions = database.list_conversations()
        return {"sessions": sessions, "default_id": conversation_id}
    return {"sessions": sessions, "default_id": sessions[0]["id"]}


@app.post("/api/sessions")
async def create_session(req: SessionCreateRequest):
    session_id = database.create_conversation(req.title)
    return {
        "session_id": session_id,
        "title": req.title,
        "sessions": database.list_conversations(),
    }


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: int):
    data = database.get_conversation_messages(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {
        "session": data["conversation"],
        "messages": data["messages"],
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: int):
    remaining = database.list_conversations()
    if len(remaining) <= 1:
        raise HTTPException(status_code=400, detail="至少保留一个对话")
    if not database.delete_conversation(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    new_default = database.ensure_default_conversation()
    return {
        "message": "已删除",
        "session_id": new_default,
        "sessions": database.list_conversations(),
    }


@app.get("/api/documents")
async def list_documents():
    return {"documents": server.list_documents()}


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in server.ALLOW_SUFFIX:
        raise HTTPException(status_code=400, detail="仅支持 txt、md、docx 文件")

    os.makedirs(server.DOCS_FOLDER, exist_ok=True)
    save_path = os.path.join(server.DOCS_FOLDER, file.filename)
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    warnings = server.rebuild_index()
    stat = os.stat(save_path)
    database.upsert_document(
        file.filename,
        save_path.replace("\\", "/"),
        stat.st_size,
    )
    return {
        "message": "上传成功，索引已更新",
        "filename": file.filename,
        "warnings": warnings,
    }


@app.post("/chat")
async def chat(req: ChatRequest):
    chat_ctx = server.prepare_chat(
        req.question,
        req.top_k,
        enable_web=req.enable_web,
        model_id=req.model,
        history=[],
    )
    answer = server.llm_answer_messages(chat_ctx["messages"], chat_ctx["model"])
    scores = chat_ctx["scores"]
    return {
        "answer": answer,
        "mode": chat_ctx["mode"],
        "sources": chat_ctx["sources"],
        "scores": scores.tolist() if len(scores) else [],
    }


@app.post("/api/stream")
async def stream_chat(req: StreamChatRequest):
    session_id = req.session_id
    data = database.get_conversation_messages(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="会话不存在")

    history = data["messages"]

    chat_ctx = server.prepare_chat(
        req.question,
        req.top_k,
        enable_web=req.enable_web,
        model_id=req.model,
        history=history,
    )

    if data["conversation"]["title"] == "新对话" and database.count_messages(session_id) == 0:
        database.update_conversation_title(session_id, req.question.strip()[:40] or "新对话")

    database.add_message(session_id, "user", req.question)

    mode = chat_ctx["mode"]
    sources = chat_ctx["sources"]
    scores = chat_ctx["scores"]
    model = chat_ctx["model"]
    messages = chat_ctx["messages"]

    def event_generator():
        answer_parts = []

        def meta_payload():
            return {
                "type": "meta",
                "session_id": session_id,
                "mode": mode,
                "mode_label": MODE_LABELS.get(mode, mode),
                "model": model,
                "sources": sources,
                "scores": scores.tolist() if len(scores) else [],
            }

        yield f"data: {json.dumps(meta_payload(), ensure_ascii=False)}\n\n"

        try:
            for token in server.llm_stream_messages(messages, model):
                answer_parts.append(token)
                payload = {"type": "token", "content": token}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as e:
            database.add_message(session_id, "assistant", f"[错误] {e}")
            err_payload = {"type": "error", "content": str(e)}
            yield f"data: {json.dumps(err_payload, ensure_ascii=False)}\n\n"
            return

        full_answer = "".join(answer_parts)
        formatted = _format_assistant_content(full_answer, sources, mode)
        database.add_message(session_id, "assistant", formatted)
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


static_dir = os.path.join(os.path.dirname(__file__), "static")
assets_dir = os.path.join(static_dir, "assets")

if os.path.isdir(assets_dir):
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

if os.path.isfile(os.path.join(static_dir, "index.html")):

    @app.get("/")
    async def serve_spa_index():
        return FileResponse(os.path.join(static_dir, "index.html"))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
