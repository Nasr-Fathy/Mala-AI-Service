# Financial AI Microservice

A production-ready FastAPI microservice that provides AI-powered financial document processing: OCR data capture via Vertex AI (Gemini) and multi-pass LLM financial mapping.

## Architecture

```
Upload PDF
    |
    v
+-------------------+
|  FastAPI Service   |
|                    |
|  POST /capture     |  --> Vertex AI OCR
|  POST /mapping     |  --> 4-pass LLM mapping
|  POST /pipeline    |  --> capture + mapping
|    /execute        |
+-------------------+
```

The service is **stateless** -- it receives input, performs AI processing, and returns structured JSON. Pipeline state management (FSM, retries, DB persistence) remains in the Django backend which calls this service via HTTP.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Service health check |
| GET | `/api/v1/ready` | Readiness probe (checks Vertex AI) |
| POST | `/api/v1/capture` | OCR extraction from PDF |
| POST | `/api/v1/mapping` | Multi-pass financial mapping |
| POST | `/api/v1/pipeline/execute` | Full pipeline (capture + mapping) |

## Quick Start

### 1. Environment Setup

```bash
cp .env.example .env
# Edit .env with your GCP project ID and other settings
```

### 2. Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate    # Linux/Mac
# venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload --port 8090
```

### 3. Docker

```bash
# Build and run
docker compose up --build

# Or build manually
docker build -t ai-service .
docker run -p 8090:8090 --env-file .env ai-service
```

### 4. GCP Authentication

The service needs access to Vertex AI. Authenticate using one of:

```bash
# Option A: Application Default Credentials (development)
gcloud auth application-default login

# Option B: Service account key (production)
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

## API Usage Examples

### OCR Capture

```bash
curl -X POST http://localhost:8090/api/v1/capture \
  -F "file=@financial_statement.pdf" \
  -F "page_numbers=[5,6,7,8]"
```

### Financial Mapping

```bash
curl -X POST http://localhost:8090/api/v1/mapping \
  -H "Content-Type: application/json" \
  -d '{
    "ocr_data": {
      "raw_text": "...",
      "pages": [...],
      "tables": [...],
      "detected_language": "ar-en"
    },
    "options": {
      "apply_category_mapping": true,
      "parallel_pass3": true
    }
  }'
```

### Full Pipeline

```bash
curl -X POST http://localhost:8090/api/v1/pipeline/execute \
  -F "file=@financial_statement.pdf" \
  -F 'config={"page_numbers": [5,6,7,8], "apply_category_mapping": true}'
```

## Project Structure

```
ai-service/
├── app/
│   ├── main.py               # FastAPI app factory + lifespan
│   ├── core/                  # Config, logging, exceptions
│   ├── api/v1/endpoints/      # HTTP endpoints
│   ├── schemas/               # Pydantic request/response models
│   ├── services/
│   │   ├── llm/               # LLM abstraction (Vertex AI)
│   │   ├── pdf/               # PDF processing (PyMuPDF)
│   │   ├── capture/           # OCR orchestration
│   │   └── mapping/           # Financial mapping (4-pass)
│   ├── pipeline/              # Step orchestrator
│   └── validation/            # JSON schema validation
├── tests/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Configuration

All settings are managed via environment variables (see `.env.example`). The service uses `pydantic-settings` for type-safe configuration.

Key settings:
- `LLM_PROVIDER` -- LLM backend (`vertex`). Extensible for `openai`, etc.
- `GOOGLE_CLOUD_PROJECT_ID` -- GCP project for Vertex AI.
- `VERTEX_MODEL` -- Gemini model identifier.
- `CATEGORY_MAPPER_CSV_PATH` -- Path to keyword-to-category CSV file.

## Extending

**Add a new LLM provider:** implement `BaseLLMClient` in `app/services/llm/`, register in `factory.py`.

**Add a new pipeline step:** implement `BasePipelineStep`, register in `app/main.py` lifespan.

## Testing

```bash
pytest tests/ -v
```
