import json
import os
from pathlib import Path

_CONFIG_DIR = Path(__file__).parent
_CONFIG_PATH = _CONFIG_DIR / "config.json"

_DEFAULT = {
    "rag_score_threshold": 0.45,
    "rag_high_confidence_threshold": 0.72,
    "llm": {
        "api_key": "",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-v4-flash",
        "models": [
            {"id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash"},
            {"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
        ],
    },
    "web_search": {
        "max_results": 5,
        "tavily_api_key": "",
        "timeout_seconds": 15,
    },
    "chat_memory": {
        "max_turns": 10,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    data = json.loads(json.dumps(_DEFAULT))
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            file_cfg = json.load(f)
        data = _deep_merge(data, file_cfg)

    llm = data["llm"]
    llm["api_key"] = os.getenv("LLM_API_KEY", llm.get("api_key", ""))
    llm["base_url"] = os.getenv("LLM_BASE_URL", llm.get("base_url", ""))
    llm["default_model"] = os.getenv("LLM_DEFAULT_MODEL", llm.get("default_model", ""))

    if os.getenv("TAVILY_API_KEY"):
        data["web_search"]["tavily_api_key"] = os.getenv("TAVILY_API_KEY")

    threshold = os.getenv("RAG_SCORE_THRESHOLD")
    if threshold:
        data["rag_score_threshold"] = float(threshold)

    return data


_CFG = load_config()

RAG_SCORE_THRESHOLD = float(_CFG["rag_score_threshold"])
RAG_HIGH_CONFIDENCE_THRESHOLD = float(_CFG.get("rag_high_confidence_threshold", 0.72))
LLM_API_KEY = _CFG["llm"]["api_key"]
LLM_BASE_URL = _CFG["llm"]["base_url"]
LLM_DEFAULT_MODEL = _CFG["llm"]["default_model"]
LLM_MODELS = _CFG["llm"]["models"]
WEB_SEARCH_MAX_RESULTS = int(_CFG["web_search"]["max_results"])
TAVILY_API_KEY = _CFG["web_search"].get("tavily_api_key", "")
WEB_SEARCH_TIMEOUT = int(_CFG["web_search"].get("timeout_seconds", 15))
CHAT_MEMORY_MAX_TURNS = int(_CFG.get("chat_memory", {}).get("max_turns", 10))


def get_models() -> list:
    return LLM_MODELS


def get_default_model() -> str:
    return LLM_DEFAULT_MODEL


def resolve_model(model_id: str | None) -> str:
    if not model_id:
        return LLM_DEFAULT_MODEL
    valid_ids = {m["id"] for m in LLM_MODELS}
    if model_id in valid_ids:
        return model_id
    return LLM_DEFAULT_MODEL


def public_config() -> dict:
    return {
        "models": get_models(),
        "default_model": get_default_model(),
        "rag_score_threshold": RAG_SCORE_THRESHOLD,
        "rag_high_confidence_threshold": RAG_HIGH_CONFIDENCE_THRESHOLD,
    }
