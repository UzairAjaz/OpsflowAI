from __future__ import annotations

from langchain_ollama import ChatOllama

from app.config import settings

def main() -> None:
    print(f"[config] model      = {settings.ollama_model}")
    print(f"[config] base_url   = {settings.ollama_base_url}")

    llm = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=settings.llm_temperature,
    )

    print("[llm] Ollama ko call kar raha hoon...")
    response = llm.invoke("Reply with exactly the single word: OPSFLOW_OK")

    print(f"[llm] response     = {response.content!r}")
    assert "OPSFLOW_OK" in response.content, "Unexpected response - connectivity ok par model odd."
    print("[ok]  Step 1 complete - Ollama connected.")

if __name__ == "__main__":
    main()
