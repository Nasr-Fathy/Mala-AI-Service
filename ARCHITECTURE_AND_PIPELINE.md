# Architecture and Pipeline Documentation

**Service:** Financial AI Microservice
**Version:** 1.0.0
**Last Updated:** April 2026

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture Explanation](#2-architecture-explanation)
3. [Pipeline Breakdown](#3-pipeline-breakdown)
4. [Code Walkthrough](#4-code-walkthrough)
5. [Design Decisions](#5-design-decisions)
6. [Assumptions and Gaps](#6-assumptions-and-gaps)
7. [Extensibility](#7-extensibility)
8. [Deployment](#8-deployment)
9. [Running the Service](#9-running-the-service)
10. [Testing the Service](#10-testing-the-service)

---

## 1. Overview

### What This Service Does

The Financial AI Microservice is a standalone FastAPI application that performs AI-powered processing on financial documents (PDFs). It extracts two stages from a larger 5-stage pipeline that lives inside a Django monolith:

- **Stage 1 -- Data Capture (OCR):** Sends PDF bytes to Google Vertex AI (Gemini 1.5 Pro) for multimodal text and table extraction. The LLM returns structured JSON containing every page's text, every detected table, and the document language.

- **Stage 2 -- Financial Mapping:** Runs four sequential LLM passes over the extracted OCR data to produce structured financial intelligence: metadata (company, currency, fiscal periods), statement segmentation (which pages hold which financial statement), line-item structuring (hierarchy, values, source tracing), and notes extraction.

Stages 3-5 of the original pipeline (Integrity Check, Risk Signals, GoRules) are deterministic business-logic or external-service calls. They remain in the Django backend because they do not use AI and have no reason to be in this microservice.

### Responsibilities

| Responsibility | Details |
|---|---|
| PDF page extraction | Extract specific pages from a PDF using PyMuPDF, entirely in-memory |
| OCR via LLM | Send PDF bytes to Gemini for multimodal text/table extraction |
| Schema validation | Validate every LLM output against a JSON schema before returning it |
| Multi-pass financial mapping | Run four focused LLM passes to build structured financial data |
| Category assignment | Match extracted line-item names to canonical financial categories using a keyword CSV |
| Pipeline orchestration | Execute capture and mapping as sequential steps with shared context |

### What This Service Does NOT Do

- It does not manage pipeline state. There is no database. The service is stateless.
- It does not store results. The Django backend calls this service, receives the response, and persists it.
- It does not handle retries at the pipeline level. Per-stage retries are managed by the Django orchestrator; this service only retries individual LLM calls within a single request.
- It does not perform deterministic financial validation (that is Stage 3 in Django).
- It does not compute risk ratios or credit decisions (Stages 4-5 in Django).

---

## 2. Architecture Explanation

### System Context

```
                      Django Backend (Celery worker)
                               |
                    HTTP POST (PDF bytes / JSON)
                               |
                               v
                  +----------------------------+
                  |  Financial AI Microservice  |
                  |        (FastAPI)            |
                  +----------------------------+
                               |
                    Vertex AI SDK (gRPC)
                               |
                               v
                  +----------------------------+
                  |   Google Vertex AI          |
                  |   Gemini 1.5 Pro            |
                  +----------------------------+
```

The Django backend dispatches a Celery task. That task makes an HTTP request to this microservice, waits for the response, and saves the result into the Django ORM. The microservice never talks to the database.

### Layer Architecture

The codebase is split into five layers, each with a single responsibility.

```
ai-service/app/
    core/           <-- Configuration, logging, exception hierarchy
    api/            <-- HTTP endpoints, dependency injection, Pydantic schemas
    services/       <-- Business logic (LLM, PDF, capture, mapping)
    pipeline/       <-- Step abstraction, registry, orchestrator
    validation/     <-- JSON-schema validation of LLM outputs
```

**Core layer** (`app/core/`). Contains three modules:

- `config.py` -- All configuration is loaded from environment variables via `pydantic-settings`. A single `Settings` class with typed fields and defaults. A cached `get_settings()` function provides the singleton.
- `logging.py` -- Configures `structlog` for structured JSON logging in staging/production and coloured console output in development.
- `exceptions.py` -- A typed exception hierarchy rooted at `AIServiceError`. Every exception carries an `error_code`, an HTTP `status_code`, and optional `details`. Two FastAPI exception handlers translate these into consistent JSON error responses.

**API layer** (`app/api/`). Contains:

- `deps.py` -- FastAPI dependency-injection functions. Each function reads from `app.state` (populated during startup) and returns the appropriate service or client.
- `v1/endpoints/` -- Four endpoint modules: `health.py`, `capture.py`, `mapping.py`, `pipeline.py`. Each defines a single router with one or two routes.
- `v1/router.py` -- Aggregates all endpoint routers into one `v1_router`, which `main.py` mounts at `/api/v1`.

**Services layer** (`app/services/`). Contains four sub-packages:

- `llm/` -- Vendor-agnostic LLM abstraction. `BaseLLMClient` defines the interface; `VertexLLMClient` implements it for Gemini; `factory.py` selects the implementation based on `LLM_PROVIDER`.
- `pdf/` -- `LayoutService` wraps PyMuPDF for in-memory PDF page extraction, page counting, and page-map building.
- `capture/` -- `CaptureService` orchestrates OCR: extracts pages, calls the LLM, validates the output, maps pages to originals, and returns a self-contained dict.
- `mapping/` -- `BaseMapperService` defines the 4-pass framework; `FinancialMapperService` implements each pass; `CategoryMapper` performs keyword-to-category assignment; `prompts/` holds the four LLM prompt templates.

**Pipeline layer** (`app/pipeline/`). Contains:

- `base_step.py` -- `BasePipelineStep` ABC, plus `PipelineContext` (a mutable dict carried through all steps) and `StepResult` (outcome of a step).
- `registry.py` -- `StepRegistry` stores steps in insertion order.
- `orchestrator.py` -- `PipelineOrchestrator` iterates over registered steps, validates inputs, executes, and stops on first failure.
- `steps/` -- `CaptureStep` and `MappingStep` wrap the respective services as pipeline steps.

**Validation layer** (`app/validation/`). Contains:

- `schema_validator.py` -- Loads JSON schemas from disk (cached via `lru_cache`) and validates dicts against them using `jsonschema`.
- `schemas/` -- Five JSON schema files copied from the Django backend: `capture_output.json`, `metadata_schema.json`, `period_schema.json`, `statement_schema.json`, `notes_schema.json`.

### Why This Architecture

The layered structure was chosen because:

1. **Testability.** Each layer can be tested in isolation. The LLM is behind an abstract interface, so tests swap in a fake client with zero external calls.
2. **Replaceability.** Swapping Gemini for GPT-4 requires implementing one class and changing one environment variable. No service or endpoint code changes.
3. **Separation of concerns.** Endpoints do HTTP handling; services do business logic; the pipeline layer does orchestration. No layer reaches into another's internals.
4. **Extensibility.** Adding a new AI stage means writing one `BasePipelineStep` subclass and registering it -- no changes to the orchestrator or existing steps.

---

## 3. Pipeline Breakdown

The AI pipeline consists of two sequential steps, each containing sub-operations.

### Step 1: Capture (OCR)

**What it does.** Converts a raw PDF into structured text and table data.

**Why it exists.** Financial documents are unstructured PDFs (often scanned). Downstream stages need machine-readable text with page-level segmentation and table structure. This step is the bridge between the physical document and the semantic processing that follows.

**How it works internally:**

1. Count total pages in the PDF using PyMuPDF.
2. If specific `page_numbers` were requested, extract only those pages into a new in-memory PDF. Otherwise, use the full document.
3. Send the PDF bytes to Vertex AI Gemini with a prompt that includes the JSON output schema. The model returns structured JSON with `raw_text`, `pages`, `tables`, and `detected_language`.
4. Validate the LLM output against `capture_output.json` schema. If validation fails, raise `SchemaValidationError` so the caller can retry.
5. Map each extracted page and table back to its original page number (because the LLM sees a re-paginated PDF starting at page 1).
6. Build a `page_map` (extracted index to original page number) for downstream use.
7. Return the final dict with metadata (model version, processing time, token estimate).

**How it connects to the next step.** The capture output is placed into the `PipelineContext` under the key `capture_output`. The mapping step reads from that key.

### Step 2: Mapping (Financial Structuring)

**What it does.** Transforms raw OCR text/tables into structured financial intelligence through four focused LLM passes.

**Why it exists.** A single massive LLM call to extract all financial data from a document at once would suffer from high hallucination risk, context-window overflow, and expensive retries. Splitting into four passes gives controlled scope, lower hallucination, modular debugging, and targeted retries.

**The four passes:**

**Pass 1 -- Metadata Extraction.** Extracts document-level metadata: company name (EN/AR), fiscal periods, currency, value scale, and audit information. Sends the full OCR text and tables. Output is validated against `metadata_schema.json`. Null booleans (e.g., `is_audited`) are normalised to defaults.

**Pass 2 -- Period Detection and Segmentation.** Identifies which financial statements are present, their page ranges, table associations, and column structure (which column is which fiscal year). Also identifies the notes section. Sends the OCR data plus Pass 1 metadata for context. Output is validated against `period_schema.json`.

**Pass 3 -- Statement Structuring (parallelised).** For each non-notes statement identified in Pass 2, extracts all line items with hierarchy (parent/child), values per period, source tracing (table ID, row index, page), and confidence scores. Each statement is processed as a separate LLM call. All statement calls run concurrently via `asyncio.gather()`. Each result is validated against `statement_schema.json`. After all statements complete, the category mapper assigns canonical financial categories to each line item based on keyword matching.

**Pass 4 -- Notes Extraction.** Extracts note numbers, titles (EN/AR), descriptions, embedded tables, related line items, accounting policies, contingencies, and related-party disclosures. Only processes pages within the notes section identified by Pass 2. Output is validated against `notes_schema.json`.

**How it connects to the previous step.** The mapping step reads `capture_output` from `PipelineContext`, which was written by the capture step. The OCR data (raw text, pages, tables, language) is the direct input to all four passes.

### Data Flow Between Steps

```
PDF bytes (input)
    |
    v
[CaptureStep]
    |  Writes: context["capture_output"] = { raw_text, pages, tables, ... }
    v
[MappingStep]
    |  Reads:  context["capture_output"]
    |  Writes: context["mapping_output"] = { pass_1..4 outputs, metadata }
    v
Combined result (output)
```

---

## 4. Code Walkthrough

### Project Structure

```
ai-service/
  app/
    main.py                         # App factory, lifespan, CORS, error handlers
    core/
      config.py                     # Settings via pydantic-settings
      logging.py                    # structlog setup
      exceptions.py                 # Exception hierarchy + FastAPI handlers
    api/
      deps.py                       # DI: get services from app.state
      v1/
        router.py                   # Aggregates endpoint routers
        endpoints/
          health.py                 # GET /health, GET /ready
          capture.py                # POST /capture
          mapping.py                # POST /mapping
          pipeline.py               # POST /pipeline/execute
    schemas/
      common.py                     # ErrorResponse, HealthResponse, etc.
      capture.py                    # CaptureResponse
      mapping.py                    # MappingRequest, MappingResponse
      pipeline.py                   # PipelineConfig, PipelineResponse
    services/
      llm/
        base.py                     # BaseLLMClient, GenerationConfig, LLMResponse
        vertex.py                   # VertexLLMClient (Gemini)
        factory.py                  # create_llm_client()
      pdf/
        layout_service.py           # PyMuPDF page extraction
      capture/
        capture_service.py          # OCR orchestration
      mapping/
        base_mapper.py              # Abstract 4-pass framework
        financial_mapper.py         # Concrete financial mapper
        category_mapper.py          # Keyword-to-category matching
        prompts/
          metadata.py               # Pass 1 prompt
          period.py                 # Pass 2 prompt
          statement.py              # Pass 3 prompt + get_statement_prompt()
          notes.py                  # Pass 4 prompt
    pipeline/
      base_step.py                  # BasePipelineStep, PipelineContext, StepResult
      registry.py                   # StepRegistry
      orchestrator.py               # PipelineOrchestrator
      steps/
        capture_step.py             # Wraps CaptureService
        mapping_step.py             # Wraps FinancialMapperService
    validation/
      schema_validator.py           # JSON schema loader + validator
      schemas/                      # JSON schema files (5 files)
  tests/
    conftest.py                     # FakeLLMClient, fixtures, async_client
    test_capture.py                 # CaptureService + LayoutService tests
    test_mapping.py                 # FinancialMapperService + CategoryMapper tests
    test_pipeline.py                # Orchestrator + registry tests
    test_api.py                     # HTTP endpoint integration tests
  Dockerfile                        # Multi-stage build
  docker-compose.yml                # Single-service compose
  requirements.txt                  # Python dependencies
  .env.example                      # All environment variables documented
  README.md                         # Quick-start guide
```

### Request Flow: POST /api/v1/capture

This is the simplest flow. A client uploads a PDF and gets back structured OCR data.

```
1. Client sends POST /api/v1/capture with multipart form:
   - file: PDF binary
   - page_numbers: "[5,6,7]" (optional JSON string)

2. FastAPI routes to capture.py:run_capture()

3. run_capture() reads the file bytes, checks size against MAX_UPLOAD_SIZE_MB,
   parses page_numbers from JSON string to list[int].

4. Calls CaptureService.process(pdf_bytes, page_numbers):
   a. LayoutService.get_page_count() counts pages via PyMuPDF.
   b. If subset requested, LayoutService.extract_pages_to_bytes() creates a
      new PDF with only those pages.
   c. self._llm.generate_from_pdf() sends the PDF to Gemini.
      - Internally, VertexLLMClient runs model.generate_content() in a
        thread executor (async wrapper around sync SDK).
      - On rate-limit/timeout, retries with exponential backoff + jitter.
      - Parses JSON from the response text.
   d. SchemaValidator.validate("capture_output", ocr_output) checks the
      output against capture_output.json.
   e. _map_pages() and _map_tables() add original_page_number to each item.
   f. Returns a dict with raw_text, pages, tables, metadata, etc.

5. run_capture() wraps the dict in CaptureResponse (Pydantic model) and
   returns it as JSON.
```

### Request Flow: POST /api/v1/mapping

A client sends OCR output (from a previous capture call) and gets back financial structure.

```
1. Client sends POST /api/v1/mapping with JSON body:
   {
     "ocr_data": { "raw_text": "...", "pages": [...], "tables": [...] },
     "options": { "apply_category_mapping": true }
   }

2. FastAPI routes to mapping.py:run_mapping()

3. run_mapping() extracts the OCR dict from the Pydantic model and calls
   FinancialMapperService.process(ocr_dict, apply_categories=True):

   a. _run_pass_1(ocr_data):
      - Prepares content (text + tables as JSON string).
      - Calls self._llm.generate() with METADATA_EXTRACTION_PROMPT.
      - Normalises null booleans.
      - Validates against metadata_schema.json.
      - Returns metadata dict.

   b. _run_pass_2(ocr_data, pass_1):
      - Combines OCR data with Pass 1 metadata.
      - Calls self._llm.generate() with PERIOD_DETECTION_PROMPT.
      - Validates against period_schema.json.
      - Returns segmentation dict with statements list and notes_section.

   c. _run_pass_3(ocr_data, pass_2):
      - Filters out NOTES statements.
      - For each remaining statement, creates an async task:
        - Extracts only the tables and text for that statement's page range.
        - Calls self._llm.generate() with a statement-type-specific prompt.
        - Validates against statement_schema.json.
      - Runs all tasks concurrently via asyncio.gather().
      - Returns { "statements": [...] }.

   d. _apply_categories(pass_3_output):
      - For each statement's line items, calls
        CategoryMapper.categorize_items() which matches name_en/name_ar
        against keyword synonyms using longest-match-first.

   e. _run_pass_4(ocr_data, pass_2):
      - If notes_section exists, prepares content for the notes page range.
      - Calls self._llm.generate() with NOTES_EXTRACTION_PROMPT.
      - Validates against notes_schema.json.
      - Returns notes dict.

   f. Assembles final dict with pass_1_output through pass_4_output plus
      metadata (model, tokens, elapsed time).

4. run_mapping() wraps the result in MappingResponse and returns JSON.
```

### Request Flow: POST /api/v1/pipeline/execute

This is the full pipeline. It runs capture and mapping end-to-end.

```
1. Client sends POST /api/v1/pipeline/execute with multipart form:
   - file: PDF binary
   - config: '{"page_numbers": [5,6,7], "apply_category_mapping": true}'

2. FastAPI routes to pipeline.py:execute_pipeline()

3. execute_pipeline() builds initial_data dict:
   { "pdf_bytes": <bytes>, "page_numbers": [5,6,7], "apply_category_mapping": true }

4. Calls PipelineOrchestrator.run(initial_data):
   a. Creates PipelineContext with initial_data.
   b. Iterates over registered steps in order: [CaptureStep, MappingStep].

   c. CaptureStep:
      - validate_input: checks context has "pdf_bytes" as bytes.
      - execute: calls CaptureService.process(), writes result to
        context["capture_output"].

   d. MappingStep:
      - validate_input: checks context has "capture_output" with content.
      - execute: calls FinancialMapperService.process() using the capture
        output, writes result to context["mapping_output"].

   e. Returns context.data merged with _pipeline_metadata (per-step
      success/timing).

5. execute_pipeline() extracts capture_output, mapping_output, and
   pipeline_metadata from the result, wraps in PipelineResponse.
```

### Application Startup (Lifespan)

When the FastAPI app starts (via `uvicorn`), the `lifespan` async context manager in `main.py` runs:

```
1. Load Settings from environment / .env file.
2. Configure structlog (JSON in production, console in development).
3. Create LLM client via factory (VertexLLMClient for "vertex" provider).
4. Create CategoryMapper, call .load() to pre-load keywords from CSV.
5. Create CaptureService, injecting the LLM client.
6. Create FinancialMapperService, injecting the LLM client and CategoryMapper.
7. Create StepRegistry, register CaptureStep and MappingStep in order.
8. Create PipelineOrchestrator with the registry.
9. Store all objects on app.state for dependency injection.
```

All objects are created once and reused for the lifetime of the process.

---

## 5. Design Decisions

### Decision 1: Vendor-Agnostic LLM Interface

**What.** `BaseLLMClient` is an abstract class with `generate()`, `generate_from_pdf()`, and `health_check()`. `VertexLLMClient` implements it.

**Why.** The Django codebase had Vertex AI SDK calls scattered across `VertexAIService` and `VertexMappingClient`, each with duplicated retry logic. Swapping to OpenAI or Anthropic would have required rewriting both classes plus every call site.

**Alternative considered.** A direct Vertex AI client without abstraction (simpler, fewer files). Rejected because the architecture document explicitly calls for vendor independence, and the abstraction cost is minimal (one ABC, one implementation, one factory).

**How it is better.** Adding a new provider means implementing `BaseLLMClient` in a new file, adding an `elif` in `factory.py`, and setting `LLM_PROVIDER` in `.env`. Zero changes to services, endpoints, or tests.

### Decision 2: Async with Thread-Pool Executor for Vertex AI SDK

**What.** `VertexLLMClient._call_with_retry()` wraps `model.generate_content()` in `asyncio.get_running_loop().run_in_executor()`.

**Why.** The Vertex AI Python SDK is synchronous. The Django codebase used `time.sleep()` for retry delays, which blocks the Celery worker thread. In a FastAPI async context, blocking the event loop would prevent handling concurrent requests.

**Alternative considered.** Using the Vertex AI async SDK (`aio` module). This was not used because `vertexai.generative_models` does not expose stable async methods. The thread-pool approach is reliable and avoids depending on unstable internal APIs.

**How it is better.** The event loop stays free during LLM calls. Multiple requests can be processed concurrently (limited by the thread pool size). Retry delays use `asyncio.sleep()` instead of `time.sleep()`.

### Decision 3: Parallelised Pass 3 via asyncio.gather

**What.** Pass 3 (statement structuring) launches one async task per financial statement and runs them concurrently.

**Why.** The architecture document specifies that Pass 3 should be parallelisable. The Django implementation processes statements sequentially. For a document with four financial statements, parallelisation can reduce Pass 3 wall-clock time by up to 75%.

**Alternative considered.** Sequential processing (simpler error handling). Rejected because the performance gain is significant and `asyncio.gather(return_exceptions=True)` provides clean error collection.

### Decision 4: Context-Optimised Pass 3

**What.** Each Pass 3 invocation receives only the tables and text for that statement's page range, not the entire document.

**Why.** Financial documents can be 50+ pages. Sending all tables to every Pass 3 call wastes tokens and increases hallucination risk. By filtering to only relevant pages, the LLM has less noise and produces more accurate extractions.

### Decision 5: Stateless Service with No Database

**What.** The microservice has no database, no Redis, no persistent state.

**Why.** Pipeline lifecycle (FSM, retries, stage tracking) is already managed by Django's `PipelineRun` and `StageExecution` models. Duplicating state management in the microservice would create a split-brain problem. Instead, this service does one thing: receive input, run AI, return output.

**Alternative considered.** Adding a task queue (Celery or Redis-backed) inside the microservice for long-running jobs. Rejected because the Django Celery worker already provides that layer. The HTTP call from Celery to this service is inherently async from Django's perspective.

### Decision 6: Category Assignment in the Microservice

**What.** After Pass 3, the microservice applies keyword-based category mapping to each line item using `CategoryMapper`.

**Why.** The architecture document specifies that the LLM should NOT assign categories -- instead, a keyword-to-category mapping sheet is used. This is deterministic logic, but it is tightly coupled to the mapping stage output. Placing it here avoids an extra round-trip back to Django between Pass 3 and Pass 4.

**Alternative considered.** Leaving category assignment entirely in Django. This would work but adds latency (Django would need to process the mapping result, apply categories, then potentially call back for Pass 4). Since the category mapper is a simple CSV lookup, it is lightweight enough to include in the microservice.

### Decision 7: JSON Schema Validation of Every LLM Output

**What.** Every LLM response is validated against a JSON schema before being used.

**Why.** LLMs are non-deterministic. A response might be valid JSON but have missing required fields, wrong types, or unexpected structure. Schema validation catches these issues immediately rather than letting corrupt data propagate to downstream passes or back to Django.

### Decision 8: Structured Logging with structlog

**What.** All logging uses `structlog` with key-value pairs.

**Why.** The Django codebase uses basic Python `logging.getLogger()` with unstructured messages. In production, structured JSON logs are essential for log aggregation (CloudWatch, Stackdriver, ELK). The switch to structlog costs nothing at development time (console renderer in dev mode) but provides production observability.

---

## 6. Assumptions and Gaps

### Assumptions Made

1. **The Vertex AI SDK will remain synchronous.** The thread-pool executor approach assumes that `model.generate_content()` is a blocking call. If Google releases a stable async API, `VertexLLMClient` should be updated to use it directly.

2. **The Django backend will call this service synchronously from Celery tasks.** The service is designed for request-response HTTP calls where the caller (a Celery worker) can afford to wait 30-120 seconds for LLM processing to complete.

3. **The category mapping CSV format matches the Django version.** The `CategoryMapper` expects columns named `Canonical Field Name`, `Main Level`, `Synonyms (English)`, `Synonyms (Arabic)`, etc. If the Django team changes the sheet format, this mapper must be updated.

4. **PDF files fit in memory.** The `MAX_UPLOAD_SIZE_MB` default is 50 MB. Financial documents are typically 1-10 MB. The service processes PDFs entirely in-memory (no disk I/O).

5. **One Gemini model serves both OCR and mapping.** The same `VERTEX_MODEL` is used for both multimodal OCR (Pass 0/capture) and text-only mapping (Passes 1-4). If different models are needed (e.g., a cheaper model for OCR, a more capable one for mapping), the config would need per-stage model settings.

### Gaps in the Original Pipeline

1. **No authentication.** The pipeline architecture document does not specify how the AI microservice authenticates requests from Django. The current implementation has no auth. In production, an API key header or mutual TLS should be added.

2. **No rate limiting.** There is no request-level rate limiting. If multiple Celery workers hit this service simultaneously, all requests will compete for Vertex AI quota.

3. **No webhook/callback mode.** The service only supports synchronous request-response. For very large documents that take minutes to process, a callback-based design (Django submits a job, the service calls back when done) would be more robust against HTTP timeouts.

4. **Category mapper data source.** The original Django code fetches the keyword sheet from Google Sheets at runtime. The microservice defaults to a local CSV file loaded at startup. The remote URL option is supported but the Google Sheets CSV export URL is not configured by default. The team must either provide a CSV file at `CATEGORY_MAPPER_CSV_PATH` or set `CATEGORY_MAPPER_REMOTE_URL`.

5. **No metrics endpoint.** The architecture does not specify Prometheus metrics. The service tracks LLM call counts and token usage internally (`VertexLLMClient.get_stats()`) but does not expose them via an HTTP endpoint.

---

## 7. Extensibility

### Adding a New Pipeline Step

To add a new AI stage (for example, a "Summary Generation" step that runs after mapping):

1. Create a new service in `app/services/summary/summary_service.py` that encapsulates the AI logic.

2. Create a new step in `app/pipeline/steps/summary_step.py`:

```python
from app.pipeline.base_step import BasePipelineStep, PipelineContext, StepResult

class SummaryStep(BasePipelineStep):
    name = "summary"

    def __init__(self, summary_service):
        self._service = summary_service

    async def validate_input(self, context: PipelineContext) -> bool:
        return context.get("mapping_output") is not None

    async def execute(self, context: PipelineContext) -> StepResult:
        mapping = context.get("mapping_output")
        result = await self._service.process(mapping)
        context.set("summary_output", result)
        return StepResult(success=True, output=result)
```

3. Register the step in `app/main.py` lifespan:

```python
from app.pipeline.steps.summary_step import SummaryStep

registry.register(CaptureStep(capture_service))
registry.register(MappingStep(mapper_service))
registry.register(SummaryStep(summary_service))  # new step
```

4. Add an endpoint in `app/api/v1/endpoints/summary.py` if the step should be callable independently.

5. Update the Pydantic `PipelineResponse` schema to include `summary_output`.

No changes to the orchestrator, existing steps, or existing endpoints are needed.

### Adding a New LLM Provider

To add OpenAI as an alternative provider:

1. Create `app/services/llm/openai.py` implementing `BaseLLMClient`.

2. Add an `elif` branch in `app/services/llm/factory.py`:

```python
if provider == "vertex":
    return VertexLLMClient(settings)
elif provider == "openai":
    return OpenAILLMClient(settings)
```

3. Add OpenAI-specific settings to `app/core/config.py` (API key, model name).

4. Set `LLM_PROVIDER=openai` in `.env`.

No service or endpoint code changes are needed.

### Adding a New Pipeline Type

To support a different document type (e.g., bank statements with different passes):

1. Create `app/services/mapping/bank_mapper.py` extending `BaseMapperService` with different pass implementations.

2. Create new prompts in `app/services/mapping/prompts/bank/`.

3. Create a new `BankMappingStep` that wraps the bank mapper.

4. Either register it in the same pipeline (if it replaces the financial mapper conditionally) or create a separate `StepRegistry` for bank-statement pipelines and expose a new endpoint.

### Scaling

- **Horizontal scaling:** The service is stateless. Deploy multiple instances behind a load balancer.
- **Vertex AI quota:** Increase Vertex AI quota in GCP for concurrent requests.
- **Workers:** Set `WORKERS > 1` in production to run multiple uvicorn workers per container (note: each worker initialises its own Vertex AI client).

---

## 8. Deployment

### Docker Image

The Dockerfile uses a two-stage build:

- **Builder stage:** Installs Python dependencies into a `/install` prefix.
- **Runtime stage:** Copies the installed packages from the builder, copies the application code, runs as a non-root user (`appuser`), and exposes port 8090.

The image includes a Docker-level `HEALTHCHECK` that pings `GET /api/v1/health` every 30 seconds.

### Docker Compose

The `docker-compose.yml` defines a single service:

- Builds from the local Dockerfile.
- Maps port `8090:8090`.
- Reads environment variables from `.env`.
- Mounts `~/.config/gcloud` read-only for GCP Application Default Credentials.
- Connects to the `mala_network` external network (the same network used by the Django backend's `docker-compose.dev.yml`).

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APP_NAME` | Financial AI Service | Display name in logs and OpenAPI docs |
| `APP_VERSION` | 1.0.0 | Semantic version |
| `DEBUG` | false | Enable debug mode |
| `LOG_LEVEL` | INFO | Python log level (DEBUG, INFO, WARNING, ERROR) |
| `ENVIRONMENT` | development | One of: development, staging, production. Controls log format (console vs JSON) |
| `HOST` | 0.0.0.0 | Bind address |
| `PORT` | 8090 | Bind port |
| `WORKERS` | 1 | Number of uvicorn workers |
| `CORS_ORIGINS` | ["*"] | Allowed CORS origins (JSON array) |
| `LLM_PROVIDER` | vertex | LLM backend. Currently only "vertex" is implemented |
| `GOOGLE_CLOUD_PROJECT_ID` | (required) | GCP project ID for Vertex AI |
| `VERTEX_LOCATION` | us-central1 | GCP region for Vertex AI |
| `VERTEX_MODEL` | gemini-1.5-pro-002 | Gemini model identifier |
| `VERTEX_MAX_OUTPUT_TOKENS` | 8192 | Max output tokens per LLM call |
| `VERTEX_TEMPERATURE` | 0.1 | LLM temperature (low = more deterministic) |
| `LLM_MAX_RETRIES` | 5 | Max retry attempts per LLM call |
| `LLM_BASE_DELAY` | 1.0 | Base delay in seconds for exponential backoff |
| `LLM_MAX_DELAY` | 60.0 | Maximum delay cap in seconds |
| `LLM_JITTER_FACTOR` | 0.5 | Jitter factor (0-1) added to retry delays |
| `CATEGORY_MAPPER_CSV_PATH` | (empty) | Absolute path to the keyword-to-category CSV file |
| `CATEGORY_MAPPER_REMOTE_URL` | (empty) | URL to fetch the CSV from (e.g., Google Sheets export) |
| `CATEGORY_MAPPER_USE_REMOTE` | false | If true, try to fetch from remote URL first |
| `CATEGORY_MAPPER_CACHE_TTL` | 3600 | Seconds to cache the keyword data before reloading |
| `API_V1_PREFIX` | /api/v1 | URL prefix for all v1 endpoints |
| `MAX_UPLOAD_SIZE_MB` | 50 | Maximum PDF upload size in megabytes |

### Integration with Django Backend

After this service is deployed, the Django Celery tasks need to be updated to call it via HTTP instead of invoking local service classes. The integration pattern:

```python
# In Django: ocr/tasks/capture_tasks.py
import httpx

def process_ocr_task(pipeline_run_id, stage_execution_id):
    pipeline_run = PipelineRun.objects.get(id=pipeline_run_id)
    pdf_bytes = pipeline_run.document.file_bytes
    page_numbers = pipeline_run.execution_config.get("page_numbers")

    response = httpx.post(
        "http://mala_ai_service:8090/api/v1/capture",
        files={"file": ("document.pdf", pdf_bytes, "application/pdf")},
        data={"page_numbers": json.dumps(page_numbers)} if page_numbers else {},
        timeout=300,
    )
    response.raise_for_status()
    result = response.json()

    CaptureResult.objects.create(
        pipeline_run=pipeline_run,
        raw_text=result["raw_text"],
        pages=result["pages"],
        tables=result["tables"],
        # ... map remaining fields ...
    )
```

The `mala_ai_service` hostname resolves inside the Docker network because the AI service container is on the same `mala_network`.

---

## 9. Running the Service

### Option A: Running Locally (Without Docker)

**Prerequisites:**
- Python 3.11+
- GCP credentials configured (for Vertex AI access)

**Step 1: Set up a virtual environment**

```bash
cd ai-service

# Create virtual environment
python -m venv venv

# Activate it
# Linux / macOS:
source venv/bin/activate
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
```

**Step 2: Install dependencies**

```bash
pip install -r requirements.txt
```

**Step 3: Configure environment variables**

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```
GOOGLE_CLOUD_PROJECT_ID=your-actual-gcp-project-id
ENVIRONMENT=development
LOG_LEVEL=DEBUG
```

**Step 4: Authenticate with GCP**

```bash
gcloud auth application-default login
```

This stores credentials at `~/.config/gcloud/application_default_credentials.json`, which the Vertex AI SDK picks up automatically.

**Step 5: Start the server**

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8090
```

The `--reload` flag enables hot-reload on code changes (development only).

**Step 6: Verify the service is running**

```bash
curl http://localhost:8090/api/v1/health
```

Expected response:

```json
{
  "status": "ok",
  "version": "1.0.0",
  "environment": "development"
}
```

**Base URL:** `http://localhost:8090`

**Interactive docs:** `http://localhost:8090/docs` (Swagger UI)

### Option B: Running with Docker

**Prerequisites:**
- Docker and Docker Compose installed
- GCP credentials at `~/.config/gcloud/`

**Step 1: Create the external Docker network (if it does not exist)**

```bash
docker network create mala_network
```

**Step 2: Configure environment variables**

```bash
cd ai-service
cp .env.example .env
# Edit .env with your GOOGLE_CLOUD_PROJECT_ID
```

**Step 3: Build and start the service**

```bash
docker compose up --build
```

This builds the Docker image, starts the container, and streams logs to the terminal. Add `-d` to run in the background:

```bash
docker compose up --build -d
```

**Step 4: Verify the service**

```bash
curl http://localhost:8090/api/v1/health
```

**Step 5: Check readiness (verifies Vertex AI connectivity)**

```bash
curl http://localhost:8090/api/v1/ready
```

Expected response (if GCP credentials are valid):

```json
{
  "status": "healthy",
  "llm_status": "healthy",
  "model": "gemini-1.5-pro-002",
  "details": {
    "status": "healthy",
    "model": "gemini-1.5-pro-002",
    "location": "us-central1",
    "response": "OK"
  }
}
```

**Step 6: View logs**

```bash
docker compose logs -f ai-service
```

**Step 7: Stop the service**

```bash
docker compose down
```

### Option C: Build and Run Docker Image Manually

```bash
cd ai-service

# Build
docker build -t ai-service:latest .

# Run
docker run -p 8090:8090 \
  --env-file .env \
  -v ~/.config/gcloud:/home/appuser/.config/gcloud:ro \
  --name ai-service \
  ai-service:latest
```

### Health Check Endpoint

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/health` | GET | Service liveness check. Returns immediately. Does not test external dependencies. |
| `/api/v1/ready` | GET | Readiness check. Sends a test prompt to Vertex AI to verify LLM connectivity. Takes 1-3 seconds. |

---

## 10. Testing the Service

### A. Testing via API

#### Health Check

```bash
curl -s http://localhost:8090/api/v1/health | python -m json.tool
```

#### OCR Capture

Upload a PDF and get structured OCR data:

```bash
curl -X POST http://localhost:8090/api/v1/capture \
  -F "file=@/path/to/financial_statement.pdf" \
  -F 'page_numbers=[5,6,7,8,9,10]'
```

Without page filtering (process all pages):

```bash
curl -X POST http://localhost:8090/api/v1/capture \
  -F "file=@/path/to/financial_statement.pdf"
```

**Expected response** (truncated):

```json
{
  "raw_text": "Statement of Financial Position as at 31 December 2024...",
  "pages": [
    {
      "page_number": 1,
      "text": "Statement of Financial Position...",
      "original_page_number": 5
    }
  ],
  "tables": [
    {
      "page": 1,
      "table_id": "t1",
      "headers": ["", "Note", "2024", "2023"],
      "rows": [["Cash and cash equivalents", "5", "1,500,000", "1,200,000"]],
      "original_page_number": 5
    }
  ],
  "detected_language": "ar-en",
  "page_map": {"0": 5, "1": 6, "2": 7, "3": 8, "4": 9, "5": 10},
  "processed_pages": [5, 6, 7, 8, 9, 10],
  "page_count": 6,
  "is_schema_valid": true,
  "schema_version": "v1",
  "metadata": {
    "model": "gemini-1.5-pro-002",
    "prompt_version": "v1.0",
    "processing_time_ms": 12500,
    "attempt": 1,
    "estimated_tokens": 4500
  }
}
```

#### Financial Mapping

Send previously captured OCR data for financial structuring:

```bash
curl -X POST http://localhost:8090/api/v1/mapping \
  -H "Content-Type: application/json" \
  -d '{
    "ocr_data": {
      "raw_text": "Statement of Financial Position...",
      "pages": [
        {"page_number": 1, "text": "Balance sheet content...", "original_page_number": 5}
      ],
      "tables": [
        {
          "page": 1,
          "table_id": "t1",
          "headers": ["Item", "Note", "2024", "2023"],
          "rows": [
            ["Cash and cash equivalents", "5", "1500000", "1200000"],
            ["Trade receivables", "6", "2300000", "2100000"],
            ["Total current assets", "", "5000000", "4500000"]
          ],
          "original_page_number": 5
        }
      ],
      "detected_language": "ar-en"
    },
    "options": {
      "apply_category_mapping": true,
      "parallel_pass3": true
    }
  }'
```

**Expected response** (truncated):

```json
{
  "pass_1_output": {
    "company": {"name_en": "Example Corp", "name_ar": "شركة المثال"},
    "fiscal_periods": [
      {"fiscal_year": 2024, "period_type": "ANNUAL", "is_comparative": false},
      {"fiscal_year": 2023, "period_type": "ANNUAL", "is_comparative": true}
    ],
    "currency": {"code": "SAR"}
  },
  "pass_2_output": {
    "statements": [
      {"statement_type": "BALANCE_SHEET", "start_page": 5, "end_page": 6}
    ],
    "notes_section": {"start_page": 11, "end_page": 45}
  },
  "pass_3_outputs": {
    "statements": [
      {
        "statement_type": "BALANCE_SHEET",
        "line_items": [
          {"name_en": "Cash and cash equivalents", "values": [{"fiscal_year": 2024, "amount": 1500000}], "order": 0}
        ]
      }
    ]
  },
  "pass_4_output": {
    "notes": [{"note_number": "1", "title_en": "General Information"}]
  },
  "metadata": {
    "model": "gemini-1.5-pro-002",
    "processing_time_ms": 45000,
    "total_llm_calls": 6,
    "total_tokens": 15000
  }
}
```

#### Full Pipeline

Upload a PDF and run both capture and mapping in one request:

```bash
curl -X POST http://localhost:8090/api/v1/pipeline/execute \
  -F "file=@/path/to/financial_statement.pdf" \
  -F 'config={"page_numbers": [5,6,7,8,9,10], "apply_category_mapping": true}'
```

Without config (process all pages, apply categories):

```bash
curl -X POST http://localhost:8090/api/v1/pipeline/execute \
  -F "file=@/path/to/financial_statement.pdf"
```

**Expected response:**

```json
{
  "capture_output": {
    "raw_text": "...",
    "pages": [...],
    "tables": [...]
  },
  "mapping_output": {
    "pass_1_output": {...},
    "pass_2_output": {...},
    "pass_3_outputs": {...},
    "pass_4_output": {...},
    "metadata": {...}
  },
  "pipeline_metadata": {
    "steps": [
      {"step": "capture", "success": true, "elapsed_ms": 12500},
      {"step": "mapping", "success": true, "elapsed_ms": 45000}
    ],
    "total_elapsed_ms": 57500
  }
}
```

### B. Testing with Sample Files

#### File Format Requirements

- **Format:** PDF (`.pdf`)
- **Max size:** 50 MB (configurable via `MAX_UPLOAD_SIZE_MB`)
- **Content:** Financial statements (balance sheets, income statements, cash flow statements)
- **Languages:** English, Arabic, or bilingual

#### How Files Flow Through the Pipeline

```
1. PDF uploaded as multipart/form-data (field name: "file")
2. FastAPI reads raw bytes into memory
3. PyMuPDF validates the PDF and counts pages
4. If page_numbers specified, PyMuPDF extracts a subset PDF
5. PDF bytes are sent to Gemini as a multimodal Part
6. Gemini returns JSON with extracted text and tables
7. The JSON is validated, pages are remapped, result is returned
```

#### Testing with Postman

1. Create a new POST request to `http://localhost:8090/api/v1/capture`.
2. Set body type to **form-data**.
3. Add a key `file` with type **File**, select a PDF.
4. Optionally add a key `page_numbers` with type **Text**, value `[1,2,3]`.
5. Send the request.

For the mapping endpoint, use **raw** body type with **JSON** content type.

For the pipeline endpoint, use **form-data** with `file` (File) and optionally `config` (Text).

### C. End-to-End Flow

A complete example of processing a financial statement:

**Step 1: Upload the PDF to the full pipeline**

```bash
curl -X POST http://localhost:8090/api/v1/pipeline/execute \
  -F "file=@annual_report_2024.pdf" \
  -F 'config={"page_numbers": [5,6,7,8,9,10,11,12]}' \
  -o result.json
```

**Step 2: What happens inside**

```
API receives the PDF (8 pages extracted from the original document)
  |
  v
CaptureStep starts
  |-- PyMuPDF extracts pages 5-12 into a new 8-page PDF
  |-- Gemini extracts text and tables from 8 pages
  |-- Schema validation passes
  |-- Pages remapped: page 1 -> original 5, page 2 -> original 6, etc.
  |-- capture_output written to context
  |
  v
MappingStep starts
  |-- Pass 1: Extracts metadata (company="Example Corp", currency="SAR", fiscal_year=2024)
  |-- Pass 2: Identifies 4 statements (balance sheet pages 5-6, income stmt page 7, etc.)
  |-- Pass 3: Processes 4 statements in parallel
  |     |-- BALANCE_SHEET: 25 line items extracted
  |     |-- INCOME_STATEMENT: 18 line items extracted
  |     |-- CASH_FLOW: 22 line items extracted
  |     |-- CHANGES_IN_EQUITY: 12 line items extracted
  |-- Category mapping: assigns canonical categories to all 77 line items
  |-- Pass 4: Extracts 15 notes from pages 11-12
  |-- mapping_output written to context
  |
  v
Response returned with capture_output + mapping_output + pipeline_metadata
```

**Step 3: Inspect the result**

```bash
# View pipeline timing
cat result.json | python -m json.tool | grep -A 5 "pipeline_metadata"

# Count extracted line items
cat result.json | python -c "
import json, sys
data = json.load(sys.stdin)
stmts = data['mapping_output']['pass_3_outputs']['statements']
for s in stmts:
    print(f\"{s['statement_type']}: {len(s.get('line_items', []))} line items\")
"
```

### D. Running Unit Tests

The test suite uses a `FakeLLMClient` that returns deterministic responses without calling Vertex AI.

```bash
cd ai-service

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=app --cov-report=term-missing

# Run a specific test file
pytest tests/test_pipeline.py -v

# Run a specific test
pytest tests/test_api.py::test_health_endpoint -v
```

**What the tests cover:**

| Test file | What it tests |
|---|---|
| `test_capture.py` | CaptureService OCR logic, LayoutService page operations, PDF validation |
| `test_mapping.py` | FinancialMapperService 4-pass execution, CategoryMapper text normalisation and matching |
| `test_pipeline.py` | PipelineOrchestrator step execution, failure handling, validation errors, registry ordering |
| `test_api.py` | HTTP endpoints (health, readiness, capture, mapping) via httpx async client |

All tests run in under 5 seconds because no real LLM calls are made.
