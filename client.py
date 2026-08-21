import requests

API_URL = "http://127.0.0.1:8000/chat"

def ask(question: str, top_k: int = 5):
    resp = requests.post(
        API_URL,
        json={"question": question, "top_k": top_k},
        timeout=120,  # LLM 可能较慢，超时设长一点
    )
    resp.raise_for_status()
    return resp.json()

if __name__ == "__main__":
    print("RAG 客户端已连接，输入问题（输入 q 退出）")
    while True:
        question = input("\n你的问题: ").strip()
        if not question:
            continue
        if question.lower() in {"q", "quit", "exit"}:
            break

        try:
            data = ask(question)
            print("\n【回答】")
            print(data["answer"])
            print("\n【来源】")
            for src in data["sources"]:
                print(f"  - {src}")
        except requests.exceptions.ConnectionError:
            print("连接失败，请先运行: python ap.py")
            break
        except Exception as e:
            print(f"请求出错: {e}")