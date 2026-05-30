# Foundry IQ CU Demo Setup

This guide sets up the **Foundry IQ Ingestion Mode demo** for Fibey Field Ops. The demo shows how two different `contentExtractionMode` settings in Azure AI Search produce different results when asked about tables in PDF documents — specifically tables with adjacent numeric columns and sparse (empty) cells.

## What the demo shows

| Mode | Setting | Parser | Table accuracy |
|------|---------|--------|----------------|
| **Minimal** | `contentExtractionMode: minimal` | Standard text extraction (free) | Empty cells collapse → column values shift left → wrong answers |
| **Standard** | `contentExtractionMode: standard` | Azure Content Understanding | Preserves cell boundaries → correct answers |

### Demo questions to try

After switching the **Foundry IQ Ingestion** mode in the sidebar:

**Primary demo question (OTDR report):**
> *"Check the KB — what is the ORL reading at 1310nm for fiber F-03?"*

| Mode | Expected answer | Why |
|------|----------------|-----|
| **Minimal** | ~46.1 dB *(wrong — this is the ORL @1550nm value)* | Blank ORL@1310 cell is collapsed; 46.1 shifts left into the 1310nm column |
| **Standard** | ORL@1310 was not recorded (blank) | HTML `<td></td>` preserves the empty cell; LLM correctly reads it as absent |

**Secondary demo question (parts inventory):**
> *"How many FIB-009 units are available to pick?"*

| Mode | Expected answer | Why |
|------|----------------|-----|
| **Minimal** | Wrong count | Blank Reserved cell collapses; Available value shifts left |
| **Standard** | 5 units *(Current 8 − Reserved 3 = 5)* | HTML table preserves all cell boundaries |

## Prerequisites

- Azure subscription with:
  - Azure AI Search service (Basic tier or above)
  - Azure Storage Account
  - Azure AI Foundry account + project
- Azure CLI installed and authenticated (`az login`)
- `azd` CLI installed (optional — used to read output values)
- `uv` installed (for generating demo PDFs)

## Step 1 — Generate the demo PDF documents

```bash
uv run python scripts/gen_cu_demo_docs.py
```

This creates two PDFs in `services/foundry-iq-docs/docs/content_understanding_docs/`:

- **`otdr-acceptance-results.pdf`** — OTDR acceptance test table with 6 adjacent numeric columns (loss @1310, loss @1550, ORL @1310, ORL @1550) and sparse ORL cells
- **`parts-inventory-report.pdf`** — Parts stock table with 5 adjacent numeric columns (Min Stock, Current Stock, Reserved, Available, Unit Price) and blank Reserved cells

## Step 2 — Run the setup script

```bash
export AZURE_RESOURCE_GROUP="<your-resource-group>"
export FOUNDRY_RESOURCE_GROUP="<your-foundry-resource-group>"
export FOUNDRY_ACCOUNT_NAME="<your-foundry-account>"

# Optional: only needed for standard mode with a dedicated AI Services endpoint
# export AZURE_CONTENTUNDERSTANDING_ENDPOINT="https://<your-ai-services>.cognitiveservices.azure.com/"
# export AZURE_CONTENTUNDERSTANDING_KEY="<your-key>"

./scripts/setup-foundry-iq-cu-demo.sh
```

Or pass the Foundry arguments directly:

```bash
./scripts/setup-foundry-iq-cu-demo.sh <foundry-rg> <foundry-account> <foundry-project>
```

The script will:

1. Create a blob container `foundry-iq-cu-demo` and upload the PDFs
2. Create knowledge source `fibey-iq-minimal-ks` with `contentExtractionMode: minimal`
3. Create knowledge source `fibey-iq-standard-ks` with `contentExtractionMode: standard`
4. Create knowledge bases `fibey-iq-minimal-kb` and `fibey-iq-standard-kb`
5. Create Foundry connections `kb-fibey-iq-minimal` and `kb-fibey-iq-standard`
6. Assign Search Index Data Reader RBAC to the Foundry managed identity

> **Note:** `contentExtractionMode` cannot be changed after a knowledge source is created. If you need to change it, delete the knowledge source and recreate it.

## Step 3 — Configure your environment

The script prints the MCP endpoints at the end. Add them to your `.env`:

```bash
FOUNDRY_IQ_MINIMAL_MCP_URL="https://<search>.search.windows.net/knowledgebases/fibey-iq-minimal-kb/mcp"
FOUNDRY_IQ_STANDARD_MCP_URL="https://<search>.search.windows.net/knowledgebases/fibey-iq-standard-kb/mcp"
AZURE_SEARCH_ADMIN_KEY="<your-search-admin-key>"
```

Or with azd:

```bash
azd env set FOUNDRY_IQ_MINIMAL_MCP_URL  "https://..."
azd env set FOUNDRY_IQ_STANDARD_MCP_URL "https://..."
azd env set AZURE_SEARCH_ADMIN_KEY       "<your-search-admin-key>"
```

The admin key is used by the gateway to authenticate the KB MCP calls in local mode. Get it from the Azure portal under your Search service → **Keys**, or:

```bash
az search admin-key show --service-name <search-service> --resource-group <rg> --query primaryKey -o tsv
```

When both MCP URL variables are set, the **Foundry IQ Ingestion** selector appears in the Activity sidebar.

## Step 4 — Wait for indexing

The `standard` mode knowledge source uses Azure Content Understanding and takes longer to index (typically 2–5 minutes per document). Check indexer status using the **indexer name** (formed as `<ks-name>-indexer`):

```bash
SEARCH_ENDPOINT="https://<search>.search.windows.net"
curl -s "${SEARCH_ENDPOINT}/indexers/fibey-iq-standard-ks-indexer/status?api-version=2024-07-01" \
  -H "api-key: $AZURE_SEARCH_ADMIN_KEY" | python3 -m json.tool
```

Look for `"lastResult": { "status": "success", "itemsProcessed": 2 }` before running the demo.

## Architecture

```
UI sidebar (Foundry IQ Ingestion selector)
  └─ minimal / standard toggle
       ↓
App.tsx → useChat → sendMessage (foundry_iq_mode param)
       ↓
FastAPI Gateway /api/chat (foundry_iq_mode field)
       ↓
agent.py create_agent(foundry_iq_mode=...)
       ↓
MCPStreamableHTTPTool (FOUNDRY_IQ_MINIMAL_MCP_URL or FOUNDRY_IQ_STANDARD_MCP_URL)
       ↓
Azure AI Search Knowledge Base MCP
  ├─ fibey-iq-minimal-kb  ← contentExtractionMode: minimal
  └─ fibey-iq-standard-kb ← contentExtractionMode: standard
       ↓
Azure Blob Storage (foundry-iq-cu-demo container)
  ├─ otdr-acceptance-results.pdf
  └─ parts-inventory-report.pdf
```

## Troubleshooting

**The sidebar selector does not appear**
: Both `FOUNDRY_IQ_MINIMAL_MCP_URL` and `FOUNDRY_IQ_STANDARD_MCP_URL` must be set. Check `GET /api/features` — `foundry_iq_cu_demo` should be `true`.

**Both modes return the same answer**
: The standard knowledge source may still be indexing. Wait a few minutes and check indexer status (see Step 4). Also verify both URLs point to different KB names (`fibey-iq-minimal-kb` vs `fibey-iq-standard-kb`).

**Authentication errors from the KB MCP (`api-key` header)**
: Set `AZURE_SEARCH_ADMIN_KEY` in your `.env`. In local mode the gateway uses this key to authenticate directly to the Search MCP endpoint. The hosted mode uses the Foundry project managed identity instead (set up by the Foundry connection).

**Standard mode `contentExtractionMode` rejected (HTTP 400)**
: The search service managed identity needs `Cognitive Services User` on your AI Services account. The setup script assigns this, but IAM propagation can take 5–15 minutes. Alternatively, pass `AZURE_CONTENTUNDERSTANDING_KEY` so the script uses API-key auth instead of managed identity.

**Standard mode returns "no results"**
: Verify that the indexer completed successfully (see Step 4). If `contentExtractionMode: standard` was set without a valid `aiServices.uri`, the indexer fails silently — delete and recreate the knowledge source:
```bash
SEARCH_ADMIN_KEY="..." SEARCH_ENDPOINT="https://<search>.search.windows.net"
curl -X DELETE "${SEARCH_ENDPOINT}/knowledgesources/fibey-iq-standard-ks?api-version=2026-04-01" \
  -H "api-key: ${SEARCH_ADMIN_KEY}"
# Then re-run the setup script with AZURE_CONTENTUNDERSTANDING_ENDPOINT and AZURE_CONTENTUNDERSTANDING_KEY set
```
