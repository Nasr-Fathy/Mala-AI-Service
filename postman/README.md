# Postman Collection -- Financial AI Service

This folder contains a ready-to-import Postman collection and environment for testing the Financial AI Microservice.

## Files

| File | Purpose |
|---|---|
| `Financial_AI_Service.postman_collection.json` | All API requests organised into folders |
| `Financial_AI_Service.postman_environment.json` | Environment variables (`base_url`) |

## How to Import

### 1. Import the Collection

1. Open Postman.
2. Click **Import** (top-left, or `Ctrl+O`).
3. Drag and drop `Financial_AI_Service.postman_collection.json`, or click **Upload Files** and select it.
4. Click **Import**.

### 2. Import the Environment

1. Click **Import** again.
2. Select `Financial_AI_Service.postman_environment.json`.
3. Click **Import**.

### 3. Activate the Environment

1. In the top-right corner of Postman, click the environment dropdown (it may say "No Environment").
2. Select **Financial AI Service - Local**.

The `{{base_url}}` variable is now set to `http://localhost:8090`.

## How to Run Requests

### Health Check (start here)

1. Expand the **Health** folder.
2. Click **Health Check**.
3. Click **Send**.
4. Verify you get `{"status": "ok", ...}`.

If the service is not running, start it first:

```bash
cd ai-service
docker compose up --build
```

### Readiness Check

1. Click **Readiness Check** in the Health folder.
2. Click **Send**.
3. This tests Vertex AI connectivity. If you see `"status": "unhealthy"`, check your GCP credentials.

### OCR Capture (File Upload)

1. Expand the **Capture (OCR)** folder.
2. Click **Capture - All Pages** or **Capture - Specific Pages**.
3. In the **Body** tab, click **Select File** next to the `file` key.
4. Choose a PDF from your filesystem.
5. (Optional) For the "Specific Pages" request, edit the `page_numbers` value to match your document.
6. Click **Send**.
7. Wait 10-30 seconds for the LLM to respond.

### Financial Mapping (JSON Body)

1. Expand the **Mapping** folder.
2. Click **Financial Mapping - Full**.
3. The request body is pre-filled with a realistic balance sheet example. Edit it if needed or paste OCR output from a prior capture call.
4. Click **Send**.
5. Wait 30-60 seconds for the 4-pass LLM pipeline to complete.

### Full Pipeline (File Upload + Config)

1. Expand the **Pipeline** folder.
2. Click **Execute Pipeline - With Config**.
3. Select a PDF file for the `file` key.
4. Edit the `config` text value to set page numbers and options.
5. Click **Send**.
6. Wait 60-120 seconds for both capture and mapping to complete.

## Changing the Base URL

If the service runs on a different host or port:

1. Click the **eye icon** next to the environment dropdown (top-right).
2. Edit the `base_url` value (e.g., `http://192.168.1.50:8090` or `https://ai.example.com`).
3. Click **Save**.

All requests automatically use the updated URL.

## Timeouts

LLM-powered endpoints can take 30-120 seconds. If Postman times out:

1. Go to **Settings** (gear icon, top-right) > **General**.
2. Set **Request timeout in ms** to `300000` (5 minutes).
3. Click **Save**.

## Folder Overview

| Folder | Endpoints | Method | Auth |
|---|---|---|---|
| Health | `/api/v1/health`, `/api/v1/ready` | GET | None |
| Capture (OCR) | `/api/v1/capture` | POST (form-data) | None |
| Mapping | `/api/v1/mapping` | POST (JSON) | None |
| Pipeline | `/api/v1/pipeline/execute` | POST (form-data) | None |
| OpenAPI Docs | `/docs`, `/redoc`, `/openapi.json` | GET | None |
