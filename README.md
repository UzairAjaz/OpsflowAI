# OpsFlow AI

Autonomous IT troubleshooting agent: error analyze karta hai → grounded research →
apne fix ko critique karta hai (self-correction) → risk ke hisaab se human approval
leta hai → **vetted catalog** se safe action execute karta hai.

> Built step-by-step as a **learning project** (LangGraph concepts first).
> Progress + concept ledger: [`NOTES.md`](./NOTES.md)

## Current status

- [x] **Step 1** — Scaffold + Ollama connectivity
- [x] **Step 2** — Shared state + Pydantic schemas
- [x] **Step 3** — Structured LLM output
- [x] **Step 4** — First graph (START → Analyzer → END)
- [x] **Step 5** — Researcher node + web search
- [x] **Step 6** — Critic + conditional-edge loop
- [x] **Step 7** — Risk classifier + mock executor
- [x] **Step 8** — Intake / redaction node
- [x] **Step 9** — Remediation catalog + validator
- [x] **Step 10** — `interrupt()` HITL (human approval)
- [ ] Step 11 — `SqliteSaver` durable checkpoints
- [ ] ... (dekho `NOTES.md`)

## How to run

### Prerequisites

- **Python 3.11+** (tested on 3.14)
- **[Ollama](https://ollama.com)** installed and running (`ollama list` should work)
- A model pulled:
  ```powershell
  ollama pull qwen2.5:7b      # recommended (~4.7 GB)
  # or: ollama pull llama3.2   # lighter fallback
  ```

### 1. Setup (Windows / PowerShell)

```powershell
# Virtual environment
python -m venv .venv

# Dependencies
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Config
Copy-Item .env.example .env
```

### 2. Verify the install

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_ollama       # LLM reachable?
.\.venv\Scripts\python.exe -m scripts.check_catalog      # catalog + validator
.\.venv\Scripts\python.exe -m scripts.check_hitl         # interrupt/resume
```

### 3. Run the agent

One-shot (recommended):

```powershell
.\.venv\Scripts\python.exe -m app.cli "Error: Docker container retriva-backend exited with code 137 (OOM Killed), memory limit 512MiB"
```

Interactive (paste a multi-line log, blank line to finish):

```powershell
.\.venv\Scripts\python.exe -m app.cli
```

Flow: `intake → analyzer → researcher ⇄ critic → risk → [approval] → executor`.

### 4. Approval (medium/high risk)

The graph **pauses** and asks:

```
⚠️  APPROVAL REQUIRED
  Remediation: increase_memory_limit({'container_name': 'retriva-backend', 'new_memory_limit': '2GiB'})
  Approve? (y/n):
```

Non-interactive testing (pipe the answer):

```powershell
"y" | .\.venv\Scripts\python.exe -m app.cli "Error: ... OOM"   # approve
"n" | .\.venv\Scripts\python.exe -m app.cli "Error: ... OOM"   # reject
```

### Configuration knobs (`.env` or env vars)

| Var | Default | Meaning |
|---|---|---|
| `OLLAMA_MODEL` | `qwen2.5:7b` | Which local model to use |
| `MAX_LOOPS` | `3` | Max critic↔researcher iterations |
| `CONFIDENCE_THRESHOLD` | `70` | Below this → refine / escalate |
| `WEB_MAX_RESULTS` | `5` | Web results per query |
| `DRY_RUN` | `true` | Simulate only (no real command) |
| `AUTO_APPROVE` | `false` | Demo only: skip approval for medium/high |

Override per-run: `$env:MAX_LOOPS="2"; .\.venv\Scripts\python.exe -m app.cli "..."`.

### Troubleshooting

- **Ollama connection error** → make sure the Ollama app / `ollama serve` is running.
- **Model not found** → `ollama pull qwen2.5:7b` (or set `OLLAMA_MODEL` to an available model).
- **Emoji/console crash on Windows** → the CLI forces UTF-8; run from the project root.

### Verification scripts

`scripts/smoke_ollama.py`, `check_state.py`, `reducer_demo.py`, `check_structured.py`,
`check_graph.py`, `check_research.py`, `check_router.py`, `check_risk.py`,
`check_catalog.py`, `check_redact.py`, `check_hitl.py`.

Requirements: Python 3.11+ (tested 3.14), [Ollama](https://ollama.com) running locally
with a model available (`ollama list`).
