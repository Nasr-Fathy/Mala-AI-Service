# Financial AI Service -- Cheat Sheet

## 1. Project Summary

- **What:** FastAPI microservice that extracts and structures data from financial PDF documents using LLM (Gemini).
- **Stack:** Python 3.11 · FastAPI · Vertex AI (Gemini) · PyMuPDF · Pydantic · structlog · LangSmith · Docker
- **Role:** Receives PDFs from a Django backend, runs OCR + multi-pass financial mapping, returns structured JSON.

---

## 2. Architecture Snapshot

**Microservice + Clean Architecture** -- four layers, no Django dependency.

```
┌─────────────────────────────────────────────────┐
│  API Layer         (endpoints, routing, deps)   │
├─────────────────────────────────────────────────┤
│  Pipeline Layer    (orchestrator, steps)         │
├─────────────────────────────────────────────────┤
│  Service Layer     (capture, mapping, LLM, PDF) │
├─────────────────────────────────────────────────┤
│  Core Layer        (config, logging, tracing,   │
│                     exceptions, validation)      │
└─────────────────────────────────────────────────┘
```

---

## 3. Key Flow (End-to-End)

```
PDF upload ──► /api/v1/pipeline/execute
                 │
                 ├─► CaptureStep ──► CaptureService ──► LLM (OCR) ──► validated JSON
                 │
                 └─► MappingStep ──► FinancialMapperService
                       ├─► Pass 1: metadata        (1 LLM call)
                       ├─► Pass 2: period detection (1 LLM call)
                       ├─► Pass 3: statements       (N LLM calls, parallel)
                       └─► Pass 4: notes            (0-1 LLM call)
                 │
                 ▼
           Structured JSON response
```

---

## 4. Pipeline Quick Breakdown

| Pass | Name | What It Does | LLM Calls |
|------|------|-------------|-----------|
| 1 | Metadata Extraction | Company name, fiscal year, audit info, language | 1 |
| 2 | Period Detection | Identifies statements, page ranges, columns | 1 |
| 3 | Statement Structuring | Extracts line items per statement (**parallel**) | N (one per statement) |
| 4 | Notes Extraction | Extracts footnotes if a notes section exists | 0 or 1 |

After Pass 3, a **keyword-based category mapper** assigns categories to line items (no LLM needed).

---

## 5. Important Files & Where to Look

| File | Purpose |
|------|---------|
| `app/main.py` | App factory, lifespan (service init), middleware |
| `app/core/config.py` | All settings via `pydantic-settings` + `.env` |
| `app/core/tracing.py` | LangSmith tracing setup |
| `app/core/exceptions.py` | Exception hierarchy + FastAPI error handlers |
| `app/services/llm/vertex.py` | Gemini client with retry, JSON parsing, token estimation |
| `app/services/llm/base.py` | Abstract `BaseLLMClient` interface |
| `app/services/capture/capture_service.py` | OCR: PDF in, structured text + tables out |
| `app/services/mapping/financial_mapper.py` | 4-pass mapping logic (concrete implementation) |
| `app/services/mapping/base_mapper.py` | Abstract mapper with orchestration framework |
| `app/services/mapping/category_mapper.py` | Keyword-based category assignment (CSV-driven) |
| `app/services/pdf/layout_service.py` | Page extraction, counting, validation (PyMuPDF) |
| `app/pipeline/orchestrator.py` | Runs steps sequentially, collects results |
| `app/pipeline/steps/capture_step.py` | Adapts CaptureService into a pipeline step |
| `app/pipeline/steps/mapping_step.py` | Adapts FinancialMapperService into a pipeline step |
| `app/api/v1/endpoints/` | All HTTP endpoint handlers |
| `app/validation/schemas/` | JSON schemas for validating LLM outputs |

---

## 6. Key Concepts Used

- **Pipeline Pattern** -- Each AI task is a `BasePipelineStep` with `validate_input()` + `execute()`. Steps are registered in a `StepRegistry` and run by the orchestrator.
- **Orchestrator** -- `PipelineOrchestrator` iterates steps sequentially, stops on first failure, aggregates results.
- **LLM Abstraction** -- `BaseLLMClient` interface lets you swap Gemini for another provider without touching services.
- **Async + Thread Executor** -- Endpoints are `async`. The sync Vertex AI SDK runs in `loop.run_in_executor()` to avoid blocking.
- **Parallel Pass 3** -- Multiple statements are processed concurrently via `asyncio.gather()`.
- **Schema Validation** -- Every LLM output is validated against a JSON schema before use. Catches hallucinations early.
- **Retry with Backoff** -- LLM calls retry up to 5 times with exponential backoff + jitter on transient errors.
- **Request-ID Middleware** -- Propagates/generates `X-Request-ID` for log correlation across services.
- **LangSmith Tracing** -- `@traceable` decorators on all key methods. Enabled by setting `LANGSMITH_API_KEY`. Zero overhead when disabled.

---

## 7. How to Run

### Local

```bash
gcloud auth application-default login
cd ai-service
cp .env.example .env          # edit GOOGLE_CLOUD_PROJECT_ID
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload
```

### Docker

```bash
cd ai-service
cp .env.example .env          # edit GOOGLE_CLOUD_PROJECT_ID
docker network create mala_network
docker compose up --build -d
docker logs -f --tail 200 mala_ai_service
```

### Base URL

```
http://localhost:8090
```

### Health Check

```bash
curl http://localhost:8090/api/v1/health
# {"status":"ok","version":"1.0.0","environment":"development"}
```

---

## 8. How to Test

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/health` | Liveness check |
| `GET` | `/api/v1/ready` | Readiness (pings Gemini) |
| `POST` | `/api/v1/capture` | OCR only |
| `POST` | `/api/v1/mapping` | Mapping only (needs OCR output as JSON body) |
| `POST` | `/api/v1/pipeline/execute` | Full pipeline (PDF in, structured data out) |

### curl: Full Pipeline

```bash
curl -X POST http://localhost:8090/api/v1/pipeline/execute \
  -F "file=@report.pdf" \
  -F 'config={"page_numbers":[1,2,3],"apply_category_mapping":true}'
```

### curl: Capture Only

```bash
curl -X POST http://localhost:8090/api/v1/capture \
  -F "file=@report.pdf" \
  -F 'page_numbers=[1,2,3]'
```

### Unit Tests

```bash
cd ai-service
pytest -v
```

---

## 9. Debugging Tips

- **First check:** logs -- structured JSON in prod, colored console in dev. Every log has `request_id`.
- **LLM failures:** look for `llm_retryable_error` or `llm_parse_retry` in logs. Check `LLM_MAX_RETRIES`.
- **Schema validation errors:** `capture_schema_invalid` or `PassExecutionError` in logs. Compare LLM output against schemas in `app/validation/schemas/`.
- **Startup crashes:** usually a missing env var. Check `.env` against `.env.example`.
- **500 with no details:** the generic error handler logs the full traceback server-side (`unhandled_exception` event). The response body is intentionally vague.
- **LangSmith:** if `LANGSMITH_API_KEY` is set, every request is a trace at [smith.langchain.com](https://smith.langchain.com). Inspect individual LLM calls, latency, and inputs/outputs.

---

## 10. Common Pitfalls

| Pitfall | What Happens | Fix |
|---------|-------------|-----|
| `GOOGLE_CLOUD_PROJECT_ID` empty | 500 on first LLM call | Set it in `.env` |
| PDF > 50 MB | `PDFError` (422) | Increase `MAX_UPLOAD_SIZE_MB` or split the PDF |
| Malformed `page_numbers` | `PDFError` (422) with clear message | Send valid JSON array: `[1,2,3]` |
| Gemini rate limit | Retries with backoff, then `LLMRetryExhaustedError` (502) | Wait or increase quota |
| LLM returns non-JSON | `LLMResponseParseError`, retries automatically | Usually transient; if persistent, check prompt |
| Schema validation fails | `SchemaValidationError` or `PassExecutionError` | LLM hallucinated structure; retry or adjust prompt |
| No `__init__.py` in new package | Import errors | Always create `__init__.py` in new directories |
| GCP credentials missing | Auth error at Vertex AI init | Mount `~/.config/gcloud` or set `GOOGLE_APPLICATION_CREDENTIALS` |

---

## 11. Performance Notes

- **Biggest latency source:** LLM calls (2-30s each depending on document size).
- **Pass 3 is parallel:** N statements processed concurrently via `asyncio.gather()`. This is the single biggest optimization.
- **Token usage scales with document size.** Large PDFs = more tokens = higher cost + latency.
- **PDF page extraction:** subset pages with `page_numbers` to reduce tokens sent to the LLM.
- **Retry overhead:** transient LLM errors add 1-60s delay per retry (exponential backoff).
- **Tracing overhead:** zero when `LANGSMITH_API_KEY` is empty. Minimal (async HTTP POST) when enabled.

---

## 12. If You Want to Extend

### Add a new pipeline step

1. Create `app/pipeline/steps/my_step.py` -- subclass `BasePipelineStep`, implement `validate_input()` + `execute()`.
2. Create the service in `app/services/my_service/`.
3. Register in `app/main.py` lifespan: `registry.register(MyStep(my_service))`.
4. Add `@traceable` for LangSmith visibility.

### Add a new API endpoint

1. Create `app/api/v1/endpoints/my_endpoint.py` with a FastAPI `router`.
2. Add Pydantic models in `app/schemas/`.
3. Include the router in `app/api/v1/router.py`.

### Change the LLM model

Edit `.env`:
```
VERTEX_MODEL=gemini-2.0-flash-001
```

### Switch LLM provider entirely

1. Create `app/services/llm/my_provider.py` -- subclass `BaseLLMClient`.
2. Update `app/services/llm/factory.py` to return your client.
3. Set `LLM_PROVIDER=my_provider` in `.env`.

### Add a new JSON validation schema

1. Add the `.json` schema file to `app/validation/schemas/`.
2. Use `SchemaValidator.validate("my_schema", data)` in your service.

### Enable LangSmith tracing

Set in `.env`:
```
LANGSMITH_API_KEY=lsv2_pt_xxxxx
LANGSMITH_PROJECT=financial-ai-service
```

---

## Quick Reference: Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `GOOGLE_CLOUD_PROJECT_ID` | **Yes** | `""` | GCP project for Vertex AI |
| `VERTEX_MODEL` | No | `gemini-1.5-pro-002` | Gemini model name |
| `VERTEX_LOCATION` | No | `us-central1` | GCP region |
| `ENVIRONMENT` | No | `development` | `development` / `staging` / `production` |
| `LOG_LEVEL` | No | `INFO` | Python log level |
| `PORT` | No | `8090` | Server port |
| `MAX_UPLOAD_SIZE_MB` | No | `50` | Max PDF upload size |
| `LLM_MAX_RETRIES` | No | `5` | Retry attempts for LLM calls |
| `LANGSMITH_API_KEY` | No | `""` | LangSmith API key (empty = tracing off) |
| `LANGSMITH_PROJECT` | No | `financial-ai-service` | LangSmith project name |
