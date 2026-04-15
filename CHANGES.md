# Post-Implementation Review: Changes and Decisions

This document records every issue found during the production-readiness audit
of the Financial AI Microservice, the fix applied, and why.

---

## 1. Race Condition in `BaseMapperService` (Critical -- Correctness)

### Problem

`BaseMapperService.__init__()` declared two mutable instance attributes:

```python
self._raw_llm_outputs: dict[str, Any] = {}
self._start_time: float = 0
```

`FinancialMapperService` is created once during the FastAPI lifespan and stored
on `app.state`. Every incoming request calls `process()` on that same singleton.
`process()` immediately clears `_raw_llm_outputs` and overwrites `_start_time`:

```python
self._start_time = time.time()
self._raw_llm_outputs.clear()
```

If two requests arrive concurrently (which is the normal case in production
when multiple Celery workers hit the service simultaneously):

- Request A sets `_start_time` to T1.
- Request B sets `_start_time` to T2, overwriting A's value.
- Request A finishes and computes elapsed time using T2, not T1.
- Both requests interleave writes to `_raw_llm_outputs`, corrupting both.

This is a textbook data race in async Python. Although asyncio uses cooperative
multitasking (no preemption within a single `await`), each `await self._llm.generate()`
yields control, allowing the other coroutine to run and mutate the shared state.

### Additional Sub-Bug

`_raw_llm_outputs` did not even preserve raw LLM output correctly. In Pass 1:

```python
result = resp.content
self._raw_llm_outputs["pass_1"] = result  # stores reference
result = self._normalize_pass_1(result)   # mutates the same dict
```

Since `_normalize_pass_1()` mutates the dict in-place, the "raw" stored value
is identical to the normalised one. The raw output was lost at the moment of
normalisation.

### Fix

- Removed `_raw_llm_outputs` and `_start_time` from `__init__`.
- `start_time` is now a local variable in `process()`.
- All `self._raw_llm_outputs[...] = ...` writes in `FinancialMapperService`
  were removed. The raw data was never exposed via the API (the `MappingResponse`
  Pydantic model does not include a `raw_llm_outputs` field) and was silently
  dropped by Pydantic serialisation.
- Added a docstring to `BaseMapperService` stating the concurrency contract.

### Files Changed

- `app/services/mapping/base_mapper.py`
- `app/services/mapping/financial_mapper.py`

---

## 2. Incorrect Per-Request LLM Statistics (Important -- Data Accuracy)

### Problem

`process()` read the LLM client's cumulative global statistics:

```python
stats = getattr(self._llm, "get_stats", lambda: {})()
```

`VertexLLMClient.get_stats()` returns totals since the process started (e.g.
`total_calls: 500` after 100 requests). This number was placed in every
response's `metadata.total_llm_calls`, making it useless for per-request
analysis and confusing for the Django backend.

### Fix

Replaced with a deterministic per-request count computed from the actual
pipeline results:

```python
non_notes = [s for s in pass_2.get("statements", [])
             if s.get("statement_type") != "NOTES"]
llm_call_count = 2 + len(non_notes) + (1 if pass_2.get("notes_section") else 0)
```

This is always correct: 1 call for Pass 1 + 1 for Pass 2 + N for Pass 3
(one per non-notes statement) + 0 or 1 for Pass 4 (depends on whether a
notes section was detected).

The `total_tokens` field was removed from the returned metadata dict because
there is no reliable way to compute per-request token usage from the current
global stats without a race condition. The `MappingMetadata` Pydantic model
defaults `total_tokens` to 0, so the response remains valid.

### Files Changed

- `app/services/mapping/base_mapper.py`

---

## 3. Missing `__init__.py` Files (Critical -- Packaging)

### Problem

Only 2 out of 17 Python packages had `__init__.py` files:
- `app/services/mapping/prompts/__init__.py` (had exports)
- `app/api/v1/__init__.py` (empty)

The remaining 15 packages relied on Python's implicit namespace package
mechanism (PEP 420). While CPython allows this, it causes problems with:
- **pytest**: test discovery can fail or produce import errors.
- **mypy / pyright**: type checkers may not resolve imports correctly.
- **Docker builds**: some build tools skip directories without `__init__.py`.
- **IDE support**: autocompletion and go-to-definition may break.

### Fix

Created empty `__init__.py` files in all 15 missing locations:

```
app/__init__.py
app/core/__init__.py
app/api/__init__.py
app/api/v1/endpoints/__init__.py
app/schemas/__init__.py
app/services/__init__.py
app/services/llm/__init__.py
app/services/pdf/__init__.py
app/services/capture/__init__.py
app/services/mapping/__init__.py
app/pipeline/__init__.py
app/pipeline/steps/__init__.py
app/validation/__init__.py
app/middleware/__init__.py  (new package)
tests/__init__.py
```

---

## 4. Unhandled `json.JSONDecodeError` in Endpoints (Critical -- User Experience)

### Problem

The `/capture` and `/pipeline/execute` endpoints receive configuration as
JSON-encoded strings in form-data text fields (`page_numbers` and `config`).
The code parsed them with bare `json.loads()`:

```python
# capture.py
pages = json.loads(page_numbers)   # JSONDecodeError -> 500

# pipeline.py
cfg = PipelineConfig(**json.loads(config))  # JSONDecodeError -> 500
```

If a user sends malformed JSON (e.g. `[1,2,` or `{invalid}`), `json.loads()`
raises `json.JSONDecodeError`. This was caught by the generic exception
handler, which returned:

```json
{"error_code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}
```

No indication of what was wrong. The user would have no idea that their
`page_numbers` value was malformed.

### Fix

**`capture.py`**: Wrapped `json.loads()` in a try/except that raises
`PDFError` with a descriptive message. Added type validation: the parsed
value must be a list of integers.

**`pipeline.py`**: Wrapped `json.loads()` and `PipelineConfig(**...)` in
try/except blocks that raise `PipelineError` with the parse/validation
error message.

Both now return 422 with clear error messages like:
`"Invalid page_numbers format: Expecting value: line 1. Expected a JSON array like [1,2,3]."`

### Files Changed

- `app/api/v1/endpoints/capture.py`
- `app/api/v1/endpoints/pipeline.py`

---

## 5. Request-ID Middleware (Important -- Observability)

### Problem

No request tracing existed. In production, when multiple requests are
processed concurrently, log lines from different requests interleave.
Without a correlation ID, it is impossible to group logs from a single
request for debugging.

The Django backend generates request IDs for its pipeline runs. Without
propagation, the Django logs and AI service logs cannot be correlated.

### Fix

Created `app/middleware/request_id.py` with a pure-ASGI middleware
(`RequestIDMiddleware`) that:

1. Checks for an incoming `X-Request-ID` header. If the Django backend
   sends its pipeline run ID or Celery task ID in this header, the value
   is reused.
2. If no header is present, generates a UUID4.
3. Binds the ID to `structlog.contextvars` so every log message emitted
   during request handling automatically includes `request_id`.
4. Returns the ID in the `X-Request-ID` response header so the caller
   can correlate the response with logs.

The middleware is added in `main.py` via `app.add_middleware(RequestIDMiddleware)`.

### Why pure ASGI instead of `BaseHTTPMiddleware`

Starlette's `BaseHTTPMiddleware` has documented issues with streaming
responses and exception handling. A pure ASGI middleware is more reliable
and has no extra overhead.

### Files Created

- `app/middleware/__init__.py`
- `app/middleware/request_id.py`

### Files Changed

- `app/main.py`

---

## 6. Generic Error Handler Swallowed Exceptions (Important -- Debuggability)

### Problem

The fallback exception handler returned a generic 500 response without
logging the actual exception:

```python
async def generic_error_handler(_request, exc):
    return JSONResponse(status_code=500, content={...})
```

In production, any unexpected exception (e.g. a `TypeError` from a code
bug) would be silently swallowed. The only evidence would be a 500
response with no way to find the cause.

### Fix

Added structured logging of the exception before returning the response:

```python
_handler_logger.error(
    "unhandled_exception",
    exc_type=type(exc).__name__,
    exc_message=str(exc),
    traceback=traceback.format_exc(),
)
```

The response body is deliberately left generic (no exception details) to
avoid leaking internal information to callers. The full traceback is only
in the server-side logs.

### Files Changed

- `app/core/exceptions.py`

---

## 7. Unused Import in `config.py` (Minor -- Hygiene)

### Problem

`from pydantic import Field` was imported but never used. The `Settings`
class uses type annotations with defaults, not `Field()` descriptors.

### Fix

Removed the import.

### Files Changed

- `app/core/config.py`

---

## 8. Resource Leak in `LayoutService` (Minor -- Reliability)

### Problem

`LayoutService.get_page_count()` and `validate_pdf()` opened PyMuPDF
documents with `fitz.open()` and called `.close()` at the end:

```python
doc = fitz.open(stream=pdf_bytes, filetype="pdf")
count = len(doc)
doc.close()
return count
```

If `len(doc)` (or any operation between open and close) raised an
exception, `doc.close()` would never execute, leaking the file handle.

### Fix

Restructured both methods to use `try/finally`:

```python
doc = fitz.open(stream=pdf_bytes, filetype="pdf")
try:
    return len(doc)
finally:
    doc.close()
```

The `extract_pages_to_bytes()` method already had proper `finally` cleanup
and was not changed.

### Files Changed

- `app/services/pdf/layout_service.py`

---

## Summary of All Changes

| # | Severity | Category | What | Files |
|---|---|---|---|---|
| 1 | Critical | Correctness | Race condition: mutable instance state on a singleton service | `base_mapper.py`, `financial_mapper.py` |
| 2 | Important | Data accuracy | Per-request LLM stats showed global cumulative numbers | `base_mapper.py` |
| 3 | Critical | Packaging | 15 missing `__init__.py` files | 15 new files |
| 4 | Critical | User experience | `json.JSONDecodeError` returned bare 500 with no details | `capture.py`, `pipeline.py` |
| 5 | Important | Observability | No request-ID tracing | `request_id.py` (new), `main.py` |
| 6 | Important | Debuggability | Generic error handler swallowed exceptions silently | `exceptions.py` |
| 7 | Minor | Hygiene | Unused `Field` import | `config.py` |
| 8 | Minor | Reliability | PyMuPDF documents not closed on error | `layout_service.py` |

### What Was NOT Changed (in the initial audit)

- **No endpoint signatures changed.** All API contracts remain identical.
- **No Pydantic schema changes.** Request and response models are untouched.
- **No test changes needed.** All existing tests remain valid because they
  do not assert on removed fields (`raw_llm_outputs`, global stats).
- **No Django integration changes.** The Django backend does not need to
  be updated. It can optionally start sending `X-Request-ID` headers to
  benefit from request tracing, but this is not required.

---

## 9. LangSmith Tracing Integration (Feature -- Observability)

### Motivation

Production AI services require full observability into every LLM call:
latency per step, token consumption, cost attribution, prompt/response
inspection, and end-to-end request tracing. Structured logs provide some
of this, but lack the hierarchical trace visualization and the ability to
replay or compare runs across time. LangSmith provides all of these
capabilities out of the box.

### Approach

The integration uses the `langsmith` SDK's `@traceable` decorator, which
is designed to be zero-overhead when tracing is not configured:

1. **When `LANGSMITH_API_KEY` is empty** (the default): all `@traceable`
   decorators are transparent no-ops. No data is collected, no network
   calls are made, and there is no measurable performance impact.

2. **When `LANGSMITH_API_KEY` is set**: every decorated function creates
   a span in LangSmith. Nested calls automatically form parent-child
   relationships, producing a full trace tree.

### What Was Added

#### New file: `app/core/tracing.py`

Centralised configuration module with two functions:

- `configure_tracing()` -- called once during FastAPI lifespan startup.
  Sets the `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`,
  and (optionally) `LANGCHAIN_ENDPOINT` environment variables that the
  `langsmith` SDK reads at call time.

- `build_trace_metadata()` -- builds a standard metadata dict for
  `langsmith_extra`, ensuring every trace carries `service` and
  `environment` keys plus any endpoint-specific data.

#### New settings in `app/core/config.py`

```
LANGSMITH_API_KEY   -- API key from LangSmith (empty = tracing disabled)
LANGSMITH_PROJECT   -- LangSmith project name (default: "financial-ai-service")
LANGSMITH_ENDPOINT  -- LangSmith API URL (default: empty, SDK uses public endpoint)
```

#### Instrumentation points

| Layer | Function / Method | Trace Name | `run_type` |
|-------|-------------------|------------|------------|
| Pipeline | `PipelineOrchestrator.run()` | `pipeline_execution` | `chain` |
| Step | `CaptureStep.execute()` | `capture_step` | `chain` |
| Step | `MappingStep.execute()` | `mapping_step` | `chain` |
| Service | `CaptureService.process()` | `capture_ocr` | `chain` |
| Service | `BaseMapperService.process()` | `financial_mapping` | `chain` |
| Mapper | `FinancialMapperService._run_pass_1()` | `pass_1_metadata_extraction` | `chain` |
| Mapper | `FinancialMapperService._run_pass_2()` | `pass_2_period_detection` | `chain` |
| Mapper | `FinancialMapperService._run_pass_3()` | `pass_3_statement_structuring` | `chain` |
| Mapper | `FinancialMapperService._process_statement()` | `pass_3_single_statement` | `chain` |
| Mapper | `FinancialMapperService._run_pass_4()` | `pass_4_notes_extraction` | `chain` |
| LLM | `VertexLLMClient.generate()` | `llm_generate` | `llm` |
| LLM | `VertexLLMClient.generate_from_pdf()` | `llm_generate_pdf` | `llm` |

#### Request-level metadata via `langsmith_extra`

Each API endpoint passes `langsmith_extra` to the first traced function
call, attaching metadata such as:

- `environment` (dev / staging / prod)
- `endpoint` (e.g. `POST /api/v1/capture`)
- `file_name`, `file_size_bytes` (for file-upload endpoints)
- `pipeline_type` (`financial`)
- `page_numbers` (requested pages, if any)

Tags (`["capture", "development"]`, `["pipeline", "production"]`, etc.)
are also attached for filtering in the LangSmith dashboard.

### Trace hierarchy example

For a `POST /api/v1/pipeline/execute` request, LangSmith shows:

```
pipeline_execution                      [chain]  -- total request
├── capture_step                        [chain]
│   └── capture_ocr                     [chain]
│       └── llm_generate_pdf            [llm]   -- Gemini OCR call
└── mapping_step                        [chain]
    └── financial_mapping               [chain]
        ├── pass_1_metadata_extraction  [chain]
        │   └── llm_generate            [llm]
        ├── pass_2_period_detection     [chain]
        │   └── llm_generate            [llm]
        ├── pass_3_statement_structuring[chain]
        │   ├── pass_3_single_statement [chain]  -- parallel
        │   │   └── llm_generate        [llm]
        │   └── pass_3_single_statement [chain]  -- parallel
        │       └── llm_generate        [llm]
        └── pass_4_notes_extraction     [chain]
            └── llm_generate            [llm]
```

Each span includes: inputs, outputs, latency, error status, and
(for `llm` spans) token usage estimates.

### Design decisions

1. **`@traceable` over manual `RunTree` management**: The decorator
   approach keeps tracing declarative -- one line per function. Manual
   `RunTree` would scatter tracing logic across the codebase.

2. **No endpoint-level decorators**: FastAPI endpoints are NOT decorated
   with `@traceable` because the decorator wraps the function with
   `*args, **kwargs`, which can interfere with FastAPI's signature
   introspection for dependency injection. Instead, metadata is passed
   via `langsmith_extra` to the first traced call.

3. **LLM methods use `run_type="llm"`**: This tells LangSmith to render
   these spans in the specialized LLM call view with prompt/response
   panels and token tracking.

4. **Configuration via environment variables**: LangSmith reads
   `LANGCHAIN_*` env vars at function call time, not at decoration time.
   This means `configure_tracing()` can be called during lifespan startup
   (after decorators are applied) and still activate tracing for all
   subsequent calls.

### Files Changed

- `app/core/tracing.py` (new)
- `app/core/config.py` (3 new settings)
- `app/main.py` (call `configure_tracing` in lifespan)
- `app/services/llm/vertex.py` (`@traceable` on `generate`, `generate_from_pdf`)
- `app/services/capture/capture_service.py` (`@traceable` on `process`)
- `app/services/mapping/base_mapper.py` (`@traceable` on `process`)
- `app/services/mapping/financial_mapper.py` (`@traceable` on 5 methods)
- `app/pipeline/orchestrator.py` (`@traceable` on `run`)
- `app/pipeline/steps/capture_step.py` (`@traceable` on `execute`)
- `app/pipeline/steps/mapping_step.py` (`@traceable` on `execute`)
- `app/api/v1/endpoints/capture.py` (`langsmith_extra` metadata)
- `app/api/v1/endpoints/mapping.py` (`langsmith_extra` metadata + `settings` dep)
- `app/api/v1/endpoints/pipeline.py` (`langsmith_extra` metadata)
- `requirements.txt` (added `langsmith>=0.2.0`)
- `.env.example` (3 new LangSmith variables)

### What Was NOT Changed

- **No existing API contracts changed.** The `langsmith_extra` keyword is
  intercepted by the `@traceable` wrapper and never reaches the original
  function.
- **No existing tests need updating.** When `LANGCHAIN_TRACING_V2` is not
  set, `@traceable` is a no-op. The `langsmith_extra` argument is silently
  stripped even when tracing is disabled.
- **No Django integration impact.** The Django backend does not need any
  changes. LangSmith tracing is entirely internal to the AI service.
