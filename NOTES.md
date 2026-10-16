# OpsFlow AI — Learning Notes

> Har step ke baad is file mein `concept → kahan use hua → gotcha` likhte hain.
> Yeh doc ke "Learning Outcomes" table ko tumhare actual code se map karta hai.

---

## Step 1 — Project scaffold + Ollama connectivity

**Kya banaya**
- `.venv` — isolated Python environment.
- `requirements.txt` — minimal deps (abhi sirf connectivity).
- `.env` / `.env.example` — config code se alag (git-safe).
- `app/config.py` — central typed settings (`pydantic-settings`).
- `scripts/smoke_ollama.py` — proves the LLM is reachable.

**Concepts**
| Concept | Kahan | Kyun |
|---|---|---|
| Virtual environment | `.venv/` | Project ke packages global Python se isolated |
| 12-factor config | `.env` + `config.py` | Secrets code mein nahi; ek source of truth |
| Typed settings | `Settings(BaseSettings)` | Galat config pe startup pe hi error mile |
| LLM client | `ChatOllama(model=...)` | Ollama = local, free "brain" |

**Gotchas**
- `.env` file `.gitignore` mein rakhna MUST.
- `pydantic-settings` alag package hai (`pydantic` ke saath comes installed nahi).
- Python 3.14 naya hai; `chromadb` (Step 15) pe dikkat aa sakti hai — us waqt handle karenge.

**Run command**
```
.\.venv\Scripts\python.exe -m scripts.smoke_ollama
```

**Status:** ✅ done — Ollama responded `OPSFLOW_OK`.

---

## Step 2 — Shared state + Pydantic schemas

**Kya banaya**
- `app/state.py` — `OpsFlowState` (TypedDict) + Pydantic models
  (`Diagnosis`, `ResearchResult`, `Remediation`, `ExecutionResult`, `AuditEvent`)
  + `new_incident()` helper.
- `scripts/check_state.py` — validation + JSON schema + reducer metadata dikhata hai.
- `scripts/reducer_demo.py` — chhota 2-node graph jo reducer live dikhata hai.

**Concepts**
| Concept | Kahan | Kyun |
|---|---|---|
| Shared state (whiteboard) | `OpsFlowState` | Nodes direct call nahi karte; state se communicate karte hain |
| `TypedDict` | state | Sirf shape batata hai; runtime enforce nahi |
| Reducer `operator.add` | `research`, `audit` | Multiple nodes append karein, overwrite na karein |
| Reducer `add_messages` | `messages` | Chat history append/update-by-id |
| Default (no reducer) | `confidence`, `status` | Last write wins |
| Pydantic validation | `Diagnosis` etc. | LLM ka galat shape silently pass na ho |
| `Field(default_factory=...)` | `AuditEvent.ts` | Har event ko apna timestamp mile |

**Gotchas**
- Reducer **sirf tab** matter karta hai jab ek hi step mein multiple updates aayein
  (parallel nodes / loop). Single writer pe difference dikhta nahi.
- `Annotated[list[X], operator.add]` mein **naya** list return karna hai; purane
  list ko mutate karke return karoge to double-append ho sakta hai.
- `total=False` state -> har key optional; seed karne ke liye `new_incident()`.

**Run**
```
.\.venv\Scripts\python.exe -m scripts.check_state
.\.venv\Scripts\python.exe -m scripts.reducer_demo
```

**Status:** ✅ done — schemas validate, reducers verified.

---

## Step 3 — Structured LLM output

**Kya banaya**
- `app/llm.py` — `get_llm()` + `get_structured_llm(schema, method="json_schema")`.
- `app/nodes/analyzer.py` — pehla real node: prompt + structured `Diagnosis`.
- `scripts/check_structured.py` — bina graph ke structured output verify.
- Model `qwen2.5:7b` pe switch (`.env`).

**Concepts**
| Concept | Kahan | Kyun |
|---|---|---|
| `with_structured_output` | `get_structured_llm` | LLM se seedha typed object, freeform text nahi |
| `method="json_schema"` | llm.py | Ollama native structured outputs; local models ke liye reliable |
| Prompt-injection defense | analyzer prompt | Log = untrusted data, instructions nahi |
| Partial state update | `analyze()` return dict | Node poora state nahi, sirf apne keys return karta hai |

**Gotchas**
- Schema **shape** enforce karta hai, **content quality** nahi (qwen ne `diagnosis` mein
  paragraph daal diya jabki short summary chahiye thi). Prompt + evals se tighten karo.
- Model chhota (3B) ho to JSON todne/inconsistent severity ke chances zyada.
- `.env` override env var se hota hai: `$env:OLLAMA_MODEL="llama3.2"` (testing ke liye).

**Run**
```
.\.venv\Scripts\python.exe -m scripts.check_structured
```

**Status:** ✅ done — qwen2.5:7b valid `Diagnosis` deta hai (grounded evidence ke saath).

---

## Step 4 — Pehla real graph (+ checkpointer)

**Kya banaya**
- `app/graph.py` — `StateGraph(OpsFlowState)`, `START -> analyzer -> END`, `compile()`.
  Explicit serde allowlist (custom Pydantic types) wala `InMemorySaver`.
- `app/cli.py` — `python -m app.cli "<error log>"`.
- `scripts/check_graph.py` — same `thread_id` pe 2 runs se checkpoint memory prove.
- `app/state.py` — `evidence: list[str]` key add ki.

**Concepts**
| Concept | Kahan | Kyun |
|---|---|---|
| `StateGraph` + `add_node` + `add_edge` | graph.py | Graph = nodes + edges + state |
| `START` / `END` | edges | Special markers: entry/exit |
| `compile(checkpointer=...)` | graph.py | Runnable graph; har node ke baad state save |
| Checkpointer + `thread_id` | cli.py config | Ek incident = ek thread; restart pe resume |
| `graph.get_state(config)` | cli.py | Saved checkpoint padho (audit/debug/time-travel) |
| Custom-type allowlist | `JsonPlusSerializer` | Warning/future-block fix + safer deserialization |

**Gotchas**
- Windows console (cp1252) emoji pe crash -> `sys.stdout.reconfigure(encoding="utf-8")`.
- Custom Pydantic types state mein ho to checkpointer ko allowlist dena better
  (`allowed_msgpack_modules`), warna warning + future strict mode todega.
- `thread_id` pehli invoke pe diya to aage same thread pe *sirf naya input* bhejo;
  purana state khud load hota hai.

**Run**
```
.\.venv\Scripts\python.exe -m scripts.check_graph
.\.venv\Scripts\python.exe -m app.cli "Error: ... exited 137 OOM"
```

**Status:** ✅ done — graph + durable-in-memory checkpointing working.

---

## Step 5 — Researcher node + web search

**Kya banaya**
- `app/tools/web_search.py` — `@tool web_search(query, max_results)` via `ddgs`.
- `app/nodes/researcher.py` — `root_cause+diagnosis+evidence` -> query -> results
  as `ResearchResult[]` (append via reducer).
- Graph: `START -> analyzer -> researcher -> END`.
- `scripts/check_research.py` — tool + node isolate test.
- `requirements.txt` — `ddgs`. `app/config.py` — `web_max_results`.

**Concepts**
| Concept | Kahan | Kyun |
|---|---|---|
| LangChain `@tool` | web_search.py | Function ko tool banao (direct call abhi, ToolNode baad mein) |
| Reducer ka asli use | researcher return `research` | Nayi list append hoti hai, overwrite nahi (KB+web parallel-friendly) |
| Graceful degradation | try/except in `research` | Web fail ho to empty + audit warning, crash nahi |
| Untrusted content | comment + model | Search snippets kabhi instructions nahi |
| Query construction | `_build_query` | Concrete tokens (evidence) >> abstract root cause |

**Gotchas**
- **Query quality = research quality.** Sirf root_cause se "insufficient memory
  allocation" -> Java results. Evidence (exit 137, OOMKilled) milane se Docker
  results aaye. Yehi Step 6 Critic ko challenge karne ka signal dega.
- `score=0.5` abhi placeholder hai; real relevance Step 15 (KB + rerank) mein.
- `web_search.invoke({"query":...})` return karta hai function ka actual value
  (list[dict]); LLM tool-calling mein ye stringify hota hai.

**Run**
```
.\.venv\Scripts\python.exe -m scripts.check_research
.\.venv\Scripts\python.exe -m app.cli "Error: ... exited 137 OOM"
```

**Status:** ✅ done — grounded web research with citations, appended via reducer.

---

## Step 6 — Critic + conditional-edge loop (self-correction) ⭐

**Kya banaya**
- `app/nodes/critic.py` — `critique()` node + `route_after_critic()` router.
- `app/nodes/researcher.py` — ab proposal bhi deta hai (`Remediation`) + `refined_query` use karta hai.
- `app/state.py` — `Critique` model + `refined_query` field.
- `app/graph.py` — conditional edge `critic -> {accept|refine|escalate}`.
- `scripts/check_router.py` — router ka deterministic unit test.

**Concepts**
| Concept | Kahan | Kyun |
|---|---|---|
| Cyclic graph | `critic -> researcher` edge | Self-correction: fix kaafi accha na ho to dobara research |
| `add_conditional_edges` | graph.py | State ke basis pe next node choose karo |
| Router = pure function | `route_after_critic` | Sirf next-node name return; state modify NAHI |
| Loop cap | `loop_count >= max_loops` | Infinite loop / blind guessing se safety |
| Feedback loop | `refined_query` | Critic ka `suggested_query` agla search drive karta hai |
| Escalation | `status="escalated"` + route | Cap khatam -> insaan ko de do |

**Gotchas**
- **Router state modify nahi kar sakta.** `loop_count`/`status` node mein set karo, router sirf padhe.
- Original design flaw (`confidence < 70 -> Researcher`) galat tha kyunki confidence Analyzer deta hai.
  Sahi: **Critic** evaluate kare, aur loop ko naya query + counterarguments mile.
- `research` reducer loop mein accumulate hota hai -> list badhti jaati hai (intended).
- Forced loop demo: `$env:CONFIDENCE_THRESHOLD="95"; $env:MAX_LOOPS="2"`.

**Run**
```
.\.venv\Scripts\python.exe -m scripts.check_router
.\.venv\Scripts\python.exe -m app.cli "Error: ... OOM"
```

**Status:** ✅ done — cyclic self-correction + cap + escalation working.

---

## Step 7 — Risk classifier + mock executor

**Kya banaya**
- `app/nodes/risk.py` — `classify_risk()` (pure) + `classify()` node + `route_after_risk()`.
- `app/nodes/executor.py` — `execute()` (mock; pseudo argv + `ExecutionResult`).
- `app/graph.py` — `critic --accept--> risk -> {executor | END}`.
- `app/config.py` — `dry_run` (default True) + `auto_approve` (demo knob).
- `scripts/check_risk.py` — classifier + executor isolate test.

**Concepts**
| Concept | Kahan | Kyun |
|---|---|---|
| Risk-based routing | `route_after_risk` | safe auto; medium/high approval |
| Pure classifier | `classify_risk(rem, sev)` | Test-friendly, deterministic, no LLM |
| Dry-run default | `settings.dry_run` | Blind execution se safety |
| Mock executor | `execute()` | Execution ko graph mein jodna; real Step 9 |
| Awaiting status | `status="awaiting_approval"` | Pause point prepare (Step 10: interrupt) |

**Risk rules (abhi heuristic; Step 9 catalog authoritative)**
- id `inspect_/check_/get_/...` -> **safe** (auto)
- id mein `delete/drop/rm/...` -> **high**
- severity `critical` + mutating -> **high**
- baaki mutating -> **medium**

**Gotchas**
- Classifier abhi `remediation_id` ke words pe based hai -> Step 9 mein catalog
  ke `risk`/`reversible` fields se replace hoga.
- `auto_approve=true` sirf demo ke liye; production mein HITL (Step 10).
- CLI ki "Critic" line mein `status` final state dikhata hai (risk ke baad set hua),
  isliye wahan `awaiting_approval` dikh sakta hai -- cosmetic.

**Run**
```
.\.venv\Scripts\python.exe -m scripts.check_risk
.\.venv\Scripts\python.exe -m app.cli "Error: ... OOM"                 # awaiting_approval
$env:AUTO_APPROVE="true"; .\.venv\Scripts\python.exe -m app.cli "..."  # mock execute
```

**Status:** ✅ done — risk decision + mock execution wired.

---

## Step 8 — Intake / redaction node

**Kya banaya**
- `app/safety/redact.py` — `redact(text) -> (clean, counts)` (pure, regex-based).
- `app/nodes/intake.py` — Node 0: redact + thread_id + audit.
- `app/state.py` — `redactions: dict[str,int]`.
- `app/graph.py` — `START -> intake -> analyzer -> ...`.
- `scripts/check_redact.py`.
- **Loop improvement:** proposer ko `previous_critique` bhi diya (feedback decision mein jaye).

**Concepts**
| Concept | Kahan | Kyun |
|---|---|---|
| Defense-in-depth | intake before LLM | Secrets LLM/audit tak na pahunche |
| Pure redactor | `redact()` | Testable; patterns alag rakho |
| Categories + counts | `counts` dict | Audit: kitne/kis tarah ke secrets |
| Feedback into decision | `_propose` + prior critique | Retrieval kaafi nahi; decision bhi correct ho |

**Redacted patterns:** private key, AWS key, JWT, bearer token, `password/secret/token/api_key=...`, email.

**Gotchas**
- Regex redaction 100% nahi; isliye least-privilege bhi (sirf zaroori data bhejo).
- `\bpassword` "_password" (underscore) ko miss karta hai -> leading `\b` hataya.
- **Loop insight:** sirf search query refine karne se score nahi badha (proposal same
  rehta tha). **Critique proposal-mein feed karne se** score 75 -> 85 hua aur loop
  converge kiya. Self-correction = retrieval + decision dono.

**Run**
```
.\.venv\Scripts\python.exe -m scripts.check_redact
.\.venv\Scripts\python.exe -m app.cli "Error: ... password=... api_key=AKIA..."
```

**Status:** ✅ done — redaction + improved self-correction loop.

---

## Step 9 — Remediation catalog + validator ⭐

**Kya banaya**
- `app/catalog/remediations.yaml` — 7 vetted actions (risk, reversible, template, params).
- `app/catalog/__init__.py` — `ParamSpec`/`RemediationSpec`/`Catalog`, `load_catalog()`,
  `describe()` (LLM prompt ke liye), cross-check validation.
- `app/safety/validate.py` — `validate_proposal()` + `build_command()` (pure).
- `app/nodes/risk.py` — catalog-driven risk + proposal validation.
- `app/nodes/executor.py` — template -> argv (ab heuristic mock nahi).
- `app/nodes/researcher.py` — prompt mein catalog inject (LLM sirf vetted ids chune).
- `scripts/check_catalog.py`, `scripts/check_risk.py` (updated).

**Concepts**
| Concept | Kahan | Kyun |
|---|---|---|
| Constrained action space | `remediations.yaml` | LLM invent nahi kar sakta; blast radius collapse |
| Authoritative risk | `spec.risk`/`reversible` | LLM ke andaaze nahi |
| Param validation | `validate_proposal` | id/required/extra/type/enum/pattern |
| Template -> argv | `build_command` | `shell=False`, no shell injection |
| Defense-in-depth | executor dobara validate | Risk node pe bharosa nahi |
| Catalog-grounded prompt | `describe()` | LLM sirf allowed ids use kare |

**Gotchas**
- Template placeholders aur declared params cross-check hone chahiye (warna typo silent).
- **Threshold calibration:** qwen2.5:7b ka adversarial critic "reasonable fix" ko ~75
  deta hai -> `CONFIDENCE_THRESHOLD=70`. Threshold model ke against tune karo.
- `2GiB` jaisi value ke liye pattern `^[0-9]+[kKmMgG]?[iI]?[bB]?$`.
- Invalid proposal -> `status=escalated`, route `reject` (execute never).

**Run**
```
.\.venv\Scripts\python.exe -m scripts.check_catalog
.\.venv\Scripts\python.exe -m scripts.check_risk
$env:AUTO_APPROVE="true"; .\.venv\Scripts\python.exe -m app.cli "Error: ... OOM"
```

**Status:** ✅ done — full pipeline: intake -> analyze -> research -> propose -> critique ->
risk -> validate -> executor (catalog template).

---

## Step 10 — interrupt() HITL (human approval)

**Kya banaya**
- `app/nodes/approval.py` — `approval()` node (`interrupt(payload)`) + `route_after_approval()`.
- `app/graph.py` — `risk --await_approval--> approval -> {executor | END}`.
- `app/nodes/executor.py` — approval guard (bina approval execute block).
- `app/cli.py` — interrupt loop: `while "__interrupt__" in result: ... Command(resume=...)`.
- `scripts/check_hitl.py` — minimal graph pe interrupt/resume test.

**Concepts**
| Concept | Kahan | Kyun |
|---|---|---|
| `interrupt(payload)` | approval node | Graph ko pause karo, human ko context do |
| Node re-run on resume | approval node | Resume pe node start se chalta hai; interrupt value return karta hai |
| `Command(resume=...)` | CLI | Paused graph ko decision ke saath continue karo |
| Checkpoint = pause point | `get_state(config).next` | `('approval',)` dikhata hai kahan ruka |
| Defense-in-depth | executor guard | Approval ke bina execution block |
| Durable pause | checkpointer | Page reload/restart ke baad bhi pending approval (Step 11: SQLite) |

**Flow (medium/high):** risk -> `approval` -> interrupt -> **PAUSE** ->
`Command(resume={"approved":..,"approver":..})` -> approval sets `human_approval`/`status`
-> approved ? executor : END.

**Gotchas**
- `interrupt()` ke baad ka code FIRST pass pe nahi chalta; resume pe hi chalta hai.
- Checkpointer/thread_id ke bina interrupt possible nahi.
- Node interrupt se pehle **deterministic** hona chahiye (warna resume pe alag payload).
- CLI non-interactive (piped) ho to `input()` EOF -> default reject.
- `AUTO_APPROVE=true` ab sirf demo shortcut hai; asli flow interrupt hai.

**Run**
```
.\.venv\Scripts\python.exe -m scripts.check_hitl
"y" | .\.venv\Scripts\python.exe -m app.cli "Error: ... OOM"   # approve
"n" | .\.venv\Scripts\python.exe -m app.cli "Error: ... OOM"   # reject
```

**Status:** ✅ done — durable human-in-the-loop approval.

---

<!-- Agle step yahan add hote jayenge -->
