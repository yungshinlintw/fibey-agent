# Fibey Field Ops

Fibey Field Ops is a demo for **fiber optics field operations** built with **Azure AI Foundry Hosted Agents** and the **Foundry Toolbox**. The agent helps field technicians quickly check parts inventory, manage work orders, find procedures and safety guidance, and verify network/service status.

This sample also includes an **optional** Content Understanding (CU) extension to show how CU can improve agent quality when enabled. At runtime, CU adds file upload support in the chat flow so documents (for example PDF/image/Word) can be parsed and injected as structured context for Agent Framework orchestration. At indexing time, the Foundry IQ demo supports both `minimal` and `standard` ingestion paths; the `standard` path uses CU-enhanced extraction (especially for OCR and table/field structure), which can improve indexed content fidelity and downstream retrieval quality.

## Architecture

The Fibey agent can run in three deployment modes:

### 1. Local Development Mode
```text
┌───────────────┐   POST /api/chat   ┌────────────────┐   Direct Call   ┌────────────────────────┐
│ React UI      │ ─────────────────► │ FastAPI Gateway│ ──────────────► │ Agent (in-process)     │
│ + Activity    │ ◄──── SSE stream ─ │ (:8080)        │                 │ agent-framework        │
└───────────────┘                    └────────────────┘                 └──────────┬─────────────┘
                                                                                    │
                                                                         Foundry Toolbox MCP
                                                                                    │
                          ┌──────────────────┬───────────────────┬────────────────────┬───────────────────┐
                          │ inventory-mcp    │ work-orders-api   │ FoundryIQ KB       │ status dashboard  │
                          │ parts + stock    │ work order CRUD   │ procedures + safety│ browser automation│
                          └──────────────────┴───────────────────┴────────────────────┴───────────────────┘
```

### 2. Container Apps Mode (Recommended for Production)
```text
┌───────────────┐   POST /api/chat   ┌────────────────┐   Proxy + SSE   ┌────────────────────────┐
│ React UI      │ ─────────────────► │ FastAPI Gateway│ ──────────────► │ Agent Service          │
│ (nginx)       │ ◄──── SSE stream ─ │ (Container App)│                 │ (Container App)        │
└───────────────┘                    └────────────────┘                 │ + agent-framework      │
                                                                         │ + Managed Identity     │
                                                                         └──────────┬─────────────┘
                                                                                    │
                                                                         Foundry Toolbox MCP
                                                                         (api-version=v1)
                                                                                    │
                          ┌──────────────────┬───────────────────┬────────────────────┐
                          │ Work Orders API  │ Inventory MCP     │ Knowledge Base     │
                          │ (Container App)  │ (Container App)   │ (AI Search + Blob) │
                          └──────────────────┴───────────────────┴────────────────────┘
```

### 3. Foundry Hosted Mode
```text
┌───────────────┐   POST /api/chat   ┌────────────────┐   Proxy + SSE   ┌────────────────────────┐
│ React UI      │ ─────────────────► │ FastAPI Gateway│ ──────────────► │ Foundry Hosted Agent   │
│ + Activity    │ ◄──── SSE stream ─ │ (:8080)        │                 │ (Managed by Foundry)   │
└───────────────┘                    └────────────────┘                 └────────────────────────┘
```

## What the agent can do

- Look up fiber parts, SKUs, stock levels, and inventory locations
- View, create, and update work orders
- Retrieve splicing procedures, safety protocols, and troubleshooting guidance
- Check current network or service status from the dashboard

## Prerequisites

- Python 3.12+
- Node.js 20+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Azure CLI + azd CLI
- An Azure AI Foundry project with deployed models

## Quick start

```bash
# 1) Install root and UI dependencies
./scripts/setup.sh

# 2) Start the main app
./scripts/start-dev.sh

# 3) In separate terminals, start local toolbox services as needed
cd services/inventory-mcp && uv sync && uv run python server.py
cd services/work-orders-api && uv sync && uv run python server.py
cd services/status-dashboard/public && python -m http.server 8003
```

Local endpoints:
- UI: `http://localhost:5173`
- Gateway: `http://localhost:8080`
- Inventory MCP: `http://localhost:8001`
- Work Orders API: `http://localhost:8002`
- Status Dashboard: `http://localhost:8003`

FoundryIQ source documents live under `services/foundry-iq-docs/docs/` and are uploaded to blob storage, indexed by AI Search, and exposed via a knowledge base MCP endpoint.

## Environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `AGENT_MODE` | `local` (default, uses Foundry Toolbox), `hosted`, or `containerapp` |
| `FOUNDRY_PROJECT_ENDPOINT` | Foundry project endpoint |
| `FOUNDRY_MODEL` | Model deployment name (e.g., `gpt-4`) |
| `HOSTED_AGENT_NAME` | Hosted agent name (hosted mode only) |
| `CONTAINERAPP_AGENT_URL` | Agent service URL (containerapp mode only) |
| `TOOLBOX_MCP_URL` | Foundry Toolbox MCP endpoint (without api-version - automatically appended) |

For optional Content Understanding settings, see the CU table below; if you are improving this sample locally, see the local-direct table that follows.

### Content Understanding (CU) And CU Demo

| Variable | Description |
|----------|-------------|
| `AZURE_CONTENTUNDERSTANDING_ENDPOINT` | *(Optional, additive)* Azure AI Foundry endpoint for Content Understanding. When set, enables the "+" file attachment button in the UI for uploading PDFs, images, and Word documents. Files are analyzed via CU and work orders can be auto-extracted. Example: `https://your-foundry.services.ai.azure.com/` |
| `FOUNDRY_IQ_MINIMAL_MCP_URL` | *(Optional, additive)* MCP URL for the Foundry IQ KB ingested with minimal text extraction. Used by the CU ingestion comparison demo. Requires the standard URL below to also be set. |
| `FOUNDRY_IQ_STANDARD_MCP_URL` | *(Optional, additive)* MCP URL for the Foundry IQ KB ingested with Azure Content Understanding (standard mode). |
| `AZURE_CONTENTUNDERSTANDING_KEY` | *(Optional)* API key used by standard mode indexing when needed. |
| `CU_VERBOSE_LOGGING` | *(Optional)* Set to `1` to enable verbose `[CU]` info-level traces. Default is debug-only. |

### Local-Direct Mode (Dev-Only): Local Service Endpoints

`AGENT_MODE` also supports `local-direct` for development-only usage. This mode bypasses Foundry Toolbox and connects directly to local services. 

| Variable | Description |
|----------|-------------|
| `INVENTORY_MCP_URL` | *(Optional)* Override for local-direct mode inventory MCP. Default: `http://localhost:8001` |
| `WORK_ORDERS_API_URL` | *(Optional)* Override for local-direct mode work orders API. Default: `http://localhost:8002` |

**Important:** The `TOOLBOX_MCP_URL` should NOT include the `api-version` query parameter. The agent code automatically appends `?api-version=v1` to the URL. This is a critical requirement discovered during integration - the Toolbox MCP endpoint requires `api-version=v1` (not date-based versions like `2024-08-01-preview`).

## Project structure

```text
src/fibey/gateway/          # FastAPI chat gateway
src/fibey/agent/            # Field ops agent prompt and orchestration
services/inventory-mcp/     # Inventory MCP server
services/work-orders-api/   # Work orders FastAPI service
services/status-dashboard/  # Static status dashboard
services/foundry-iq-docs/   # FoundryIQ source documents
ui/                         # React frontend
infra/                      # Azure Bicep infrastructure (fibey-apps RG)
infra-agent/                # Hosted agent resource group docs
scripts/                    # Setup and deployment helper scripts
docs/                       # Architecture, deployment, and dev docs
```

## Content Understanding Demo

Fibey supports Azure Content Understanding (CU) for extracting structured work
order data from uploaded documents (PDF, images, Word). When
`AZURE_CONTENTUNDERSTANDING_ENDPOINT` is configured, a "+" attachment button
appears in the chat UI and a **CU mode selector** is shown in the Activity
sidebar.

**Three modes are available:**

| Mode | What it does |
|---|---|
| **None** | Plain OpenAI — no document understanding |
| **Basic CU** | Converts the document to markdown via `prebuilt-layout` and passes it to the LLM |
| **Classify & Analyze Work Order** | Classifies the document type, then runs a custom field extractor if it's a work order |

**Quick demo sequence** (full walkthrough in [`content-understanding/README.md`](content-understanding/README.md)):

1. **None + `.docx`** → OpenAI rejects the file with an error banner — it cannot read Word documents.
2. **Basic CU + `.docx`** → CU extracts the document and the agent can discuss it. However, the assigned technician comes back *wrong* (Marcus Tran instead of J. Martinez) because the document is deliberately ambiguous — the LLM reads the prominent "Field Technical Contact" label rather than the less obvious "Dispatch Information" row where the real technician is recorded.
3. **Classify & Analyze + `.docx` or `.pdf`** → The custom analyzer uses explicit field-location instructions, so the technician is now correct (J. Martinez) and all structured fields are extracted cleanly.

**Bonus scenarios:**
- Upload `safety_cert_splicing.pdf` in Classify & Analyze mode — it's classified as `other` (not a work order), demonstrating that the classifier prevents false positives.
- Upload `work_order_scanned.png` — a photo of a handwritten paper work order. CU's OCR pipeline reads the handwriting correctly despite real-world photo imperfections.

**Setup:**
```bash
# 1. Add to .env
AZURE_CONTENTUNDERSTANDING_ENDPOINT=https://<your-foundry-resource>.services.ai.azure.com/

# 2. Create CU analyzers (one-time setup)
uv run python content-understanding/tools/create_work_order_analyzer.py
uv run python content-understanding/tools/create_classify_and_analyze.py
```

Demo files are in `content-understanding/demo_files/`.

---

## Deployment to Azure

To deploy the full stack to Azure Container Apps:

```bash
# Login to Azure
az login
azd auth login

# Provision infrastructure and deploy services
azd up
```

This will:
1. Create Azure Container Apps environment
2. Deploy UI (nginx)
3. Deploy Gateway (FastAPI) in `containerapp` mode
4. Deploy Agent Service (agent-framework with Toolbox MCP)
5. Deploy backend services (work orders API, inventory MCP)
6. Configure managed identities and RBAC roles

For detailed deployment instructions, see [docs/deployment.md](docs/deployment.md).

**Production endpoints** (after deployment):
- UI: `https://fibey-apps-ui.<env-subdomain>.azurecontainerapps.io/`
- Gateway: `https://fibey-apps-gateway.<env-subdomain>.azurecontainerapps.io/`
- Agent Service: `https://fibey-apps-agent-service.<env-subdomain>.azurecontainerapps.io/`

## Documentation

See the `docs/` folder for more detail:
- `docs/architecture.md`
- `docs/local-development.md`
- `docs/integration.md` — CU + Foundry IQ extension flags and additive guarantees
- `docs/deployment.md`