"""
Foundry IQ CU Demo — Integration Tests
=======================================
Verifies that the two Azure AI Search knowledge bases (minimal vs standard
contentExtractionMode) are correctly set up and produce different extracted
content for the demo documents, confirming the value proposition of Azure
Content Understanding for table-heavy PDFs.

Auth (in priority order — first available wins):
  AZURE_SEARCH_ADMIN_KEY  — Search service admin key (fastest, no extra calls)
  az search admin-key show — auto-fetched via Azure CLI if key not in env
  az account get-access-token — bearer token via DefaultAzureCredential / az login

Required .env variables (loaded from repo root):
  FOUNDRY_IQ_MINIMAL_MCP_URL    — KB MCP endpoint (minimal mode)
  FOUNDRY_IQ_STANDARD_MCP_URL   — KB MCP endpoint (standard / CU mode)

Run:
  cd services/foundry-iq-docs
  pytest tests/ -v
"""

import os
import re
import subprocess
import urllib.parse
from pathlib import Path

import pytest
import requests

# ─── Load .env from repository root ──────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[4]  # fibey-agent/
_ENV_FILE = _REPO_ROOT / ".env"


def _load_dotenv(path: Path) -> None:
    """Minimal .env parser — no external deps required."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(_ENV_FILE)


# ─── Auth resolution ─────────────────────────────────────────────────────────

_SEARCH_TOKEN_SCOPE = "https://search.azure.com/.default"


def _resolve_search_auth(search_endpoint: str) -> dict[str, str]:
    """Return HTTP headers for Azure AI Search auth.

    Priority:
      1. AZURE_SEARCH_ADMIN_KEY env var
      2. az search admin-key show (auto-fetch via CLI)
      3. az account get-access-token (bearer token / DefaultAzureCredential)
    """
    # 1. Explicit env var
    key = os.getenv("AZURE_SEARCH_ADMIN_KEY", "").strip()
    if key:
        return {"api-key": key}

    # 2. Auto-fetch admin key via az CLI
    try:
        svc = search_endpoint.rstrip("/").split("//")[-1].split(".")[0]
        rg = os.getenv("AZURE_RESOURCE_GROUP", "")
        if svc and rg:
            result = subprocess.run(
                ["az", "search", "admin-key", "show",
                 "--service-name", svc, "--resource-group", rg,
                 "--query", "primaryKey", "-o", "tsv"],
                capture_output=True, text=True, timeout=20
            )
            fetched = result.stdout.strip()
            if fetched:
                return {"api-key": fetched}
    except Exception:
        pass

    # 3. Bearer token via az account get-access-token
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token",
             "--scope", _SEARCH_TOKEN_SCOPE,
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, timeout=20
        )
        token = result.stdout.strip()
        if token:
            return {"Authorization": f"Bearer {token}"}
    except Exception:
        pass

    return {}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _search_endpoint_from_mcp_url(mcp_url: str) -> str:
    """Extract base search endpoint from an MCP URL.

    e.g. https://fibey-iq-search.search.windows.net/knowledgebases/foo/mcp
         → https://fibey-iq-search.search.windows.net
    """
    parsed = urllib.parse.urlparse(mcp_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _kb_name_from_mcp_url(mcp_url: str) -> str:
    """Extract knowledge base name from MCP URL."""
    # …/knowledgebases/<kb-name>/mcp
    parts = urllib.parse.urlparse(mcp_url).path.strip("/").split("/")
    try:
        idx = parts.index("knowledgebases")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return ""


def _index_name_from_kb_name(kb_name: str) -> str:
    """Knowledge source index follows the pattern <ks-name>-index.
    KB names: fibey-iq-minimal-kb  →  KS name: fibey-iq-minimal-ks  →  index: fibey-iq-minimal-ks-index
    """
    return kb_name.replace("-kb", "-ks") + "-index"


def _indexer_name_from_kb_name(kb_name: str) -> str:
    return kb_name.replace("-kb", "-ks") + "-indexer"


def _search_query(search_endpoint: str, auth_headers: dict, index_name: str, query: str, top: int = 1) -> list[dict]:
    """Run a full-text search query against an Azure AI Search index."""
    url = f"{search_endpoint}/indexes/{index_name}/docs"
    resp = requests.get(
        url,
        params={"api-version": "2024-07-01", "search": query, "$top": top},
        headers=auth_headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("value", [])


def _index_doc_count(search_endpoint: str, auth_headers: dict, index_name: str) -> int:
    """Return the number of documents currently in an index."""
    url = f"{search_endpoint}/indexes/{index_name}/docs/$count"
    resp = requests.get(
        url,
        params={"api-version": "2024-07-01"},
        headers=auth_headers,
        timeout=30,
    )
    resp.raise_for_status()
    return int(resp.text.strip())


def _indexer_status(search_endpoint: str, auth_headers: dict, indexer_name: str) -> dict:
    url = f"{search_endpoint}/indexers/{indexer_name}/status"
    resp = requests.get(
        url,
        params={"api-version": "2024-07-01"},
        headers=auth_headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def env():
    """Return required environment variables, skipping all tests if any are missing."""
    minimal_url = os.getenv("FOUNDRY_IQ_MINIMAL_MCP_URL", "")
    standard_url = os.getenv("FOUNDRY_IQ_STANDARD_MCP_URL", "")

    missing = [
        name for name, val in [
            ("FOUNDRY_IQ_MINIMAL_MCP_URL", minimal_url),
            ("FOUNDRY_IQ_STANDARD_MCP_URL", standard_url),
        ] if not val
    ]
    if missing:
        pytest.skip(f"Required env vars not set: {', '.join(missing)}. Check .env at repo root.")

    search_endpoint = _search_endpoint_from_mcp_url(minimal_url)
    auth_headers = _resolve_search_auth(search_endpoint)
    if not auth_headers:
        pytest.skip(
            "No Azure Search credentials available. Set AZURE_SEARCH_ADMIN_KEY, "
            "or ensure 'az login' is active."
        )

    return {
        "minimal_url": minimal_url,
        "standard_url": standard_url,
        "auth_headers": auth_headers,
        "search_endpoint": search_endpoint,
        "minimal_kb": _kb_name_from_mcp_url(minimal_url),
        "standard_kb": _kb_name_from_mcp_url(standard_url),
        "minimal_index": _index_name_from_kb_name(_kb_name_from_mcp_url(minimal_url)),
        "standard_index": _index_name_from_kb_name(_kb_name_from_mcp_url(standard_url)),
        "minimal_indexer": _indexer_name_from_kb_name(_kb_name_from_mcp_url(minimal_url)),
        "standard_indexer": _indexer_name_from_kb_name(_kb_name_from_mcp_url(standard_url)),
    }


# ─── Asset verification tests ─────────────────────────────────────────────────


class TestAssets:
    """Verify required Azure assets exist and are ready."""

    def test_env_file_exists(self):
        assert _ENV_FILE.exists(), f".env not found at {_ENV_FILE}"

    def test_minimal_mcp_url_set(self):
        assert os.getenv("FOUNDRY_IQ_MINIMAL_MCP_URL"), \
            "FOUNDRY_IQ_MINIMAL_MCP_URL not set in .env"

    def test_standard_mcp_url_set(self):
        assert os.getenv("FOUNDRY_IQ_STANDARD_MCP_URL"), \
            "FOUNDRY_IQ_STANDARD_MCP_URL not set in .env"

    def test_mcp_urls_point_to_different_kbs(self):
        minimal = os.getenv("FOUNDRY_IQ_MINIMAL_MCP_URL", "")
        standard = os.getenv("FOUNDRY_IQ_STANDARD_MCP_URL", "")
        assert minimal and standard and minimal != standard, \
            "FOUNDRY_IQ_MINIMAL_MCP_URL and FOUNDRY_IQ_STANDARD_MCP_URL must point to different KB endpoints"

    def test_minimal_indexer_succeeded(self, env):
        status = _indexer_status(env["search_endpoint"], env["auth_headers"], env["minimal_indexer"])
        last = status.get("lastResult", {})
        assert last.get("status") == "success", \
            f"Minimal indexer not successful: {last.get('status')} — {last.get('errors', [])}"
        assert last.get("itemsFailed", 0) == 0, \
            f"Indexer has failed items: {last.get('errors', [])}"
        count = _index_doc_count(env["search_endpoint"], env["auth_headers"], env["minimal_index"])
        assert count >= 1, f"Minimal index is empty — expected ≥1 documents, got {count}"

    def test_standard_indexer_succeeded(self, env):
        status = _indexer_status(env["search_endpoint"], env["auth_headers"], env["standard_indexer"])
        last = status.get("lastResult", {})
        assert last.get("status") == "success", \
            f"Standard indexer not successful: {last.get('status')} — {last.get('errors', [])}"
        assert last.get("itemsFailed", 0) == 0, \
            f"Indexer has failed items: {last.get('errors', [])}"
        count = _index_doc_count(env["search_endpoint"], env["auth_headers"], env["standard_index"])
        assert count >= 1, f"Standard index is empty — expected ≥1 documents, got {count}"

    def test_gateway_features_flag(self):
        """Gateway /api/features must report foundry_iq_cu_demo: true."""
        try:
            resp = requests.get("http://localhost:8080/api/features", timeout=5)
            resp.raise_for_status()
            features = resp.json()
            assert features.get("foundry_iq_cu_demo") is True, \
                f"foundry_iq_cu_demo not enabled in /api/features: {features}"
        except requests.ConnectionError:
            pytest.skip("Gateway not running on localhost:8080 — start with scripts/start-dev.sh")


# ─── Demo question 1: Parts inventory — FIB-009 available units ───────────────


class TestPartsInventoryFIB009:
    """
    Demo question: "How many FIB-009 (GPON ONU SFP Module) units are available to pick?"
    Correct answer: Available = 5 (Current Stock = 8, Reserved = 3 for WO-006)

    Minimal mode: plain text extraction — the row reads "8 3 5" as space-separated
    values but column context may be lost for rows where Reserved is blank.
    Standard mode: HTML table — empty cells preserved as <td></td>, column
    assignments are unambiguous.
    """

    def test_minimal_index_contains_fib009_row(self, env):
        docs = _search_query(env["search_endpoint"], env["auth_headers"], env["minimal_index"], "FIB-009")
        assert docs, "No results for FIB-009 in minimal index"
        snippet = docs[0].get("snippet", "")
        assert "FIB-009" in snippet, "FIB-009 not found in minimal index snippet"

    def test_standard_index_contains_fib009_table_row(self, env):
        docs = _search_query(env["search_endpoint"], env["auth_headers"], env["standard_index"], "FIB-009")
        assert docs, "No results for FIB-009 in standard index"
        snippet = docs[0].get("snippet", "")
        assert "FIB-009" in snippet, "FIB-009 not found in standard index snippet"

    def test_standard_index_preserves_fib009_reserved_as_html_cell(self, env):
        """Standard (CU) mode produces HTML tables with explicit empty cells.
        The FIB-009 row must have all 5 numeric columns as <td> elements,
        with Reserved=3 and Available=5 clearly separated.
        """
        docs = _search_query(env["search_endpoint"], env["auth_headers"], env["standard_index"], "FIB-009 GPON ONU")
        assert docs, "No results for FIB-009 in standard index"
        snippet = docs[0].get("snippet", "")

        # CU output is HTML table — verify table structure present
        assert "<table" in snippet or "<td>" in snippet, (
            "Standard index should return HTML table markup for parts inventory. "
            f"Got plain text instead:\n{snippet[:400]}"
        )

        # FIB-009 row: Reserved=3, Available=5 must appear as adjacent cells
        # Match pattern: ...FIB-009...</td>...<td>3</td>...<td>5</td>...
        assert re.search(r"FIB-009", snippet), "FIB-009 not in snippet"
        assert "<td>3</td>" in snippet, \
            "Reserved value '3' not found as explicit <td> cell in standard index"
        assert "<td>5</td>" in snippet, \
            "Available value '5' not found as explicit <td> cell in standard index"

    def test_minimal_index_fib009_row_is_plain_text(self, env):
        """Minimal mode extracts plain text — no HTML table tags."""
        docs = _search_query(env["search_endpoint"], env["auth_headers"], env["minimal_index"], "FIB-009 GPON ONU")
        assert docs, "No results for FIB-009 in minimal index"
        snippet = docs[0].get("snippet", "")

        # Minimal should NOT have full HTML table structure for each data row
        # (it may have column headers as partial text, but not <td> per cell)
        assert "<td>3</td>" not in snippet or "<td>5</td>" not in snippet, (
            "Minimal index unexpectedly contains structured HTML cells — "
            "check if contentExtractionMode is actually set to 'minimal'"
        )

    def test_standard_index_fib009_note_preserved(self, env):
        """The NOTE about WO-006 reservation must be findable in standard index."""
        docs = _search_query(
            env["search_endpoint"], env["auth_headers"], env["standard_index"],
            "FIB-009 reserved WO-006", top=3
        )
        assert docs, "No results for FIB-009 WO-006 note in standard index"
        combined = " ".join(d.get("snippet", "") for d in docs)
        assert "WO-006" in combined, \
            "Work order WO-006 reservation note not found in standard index"


# ─── Demo question 2: OTDR — F-03 ORL@1310 reading ──────────────────────────


class TestOTDRFiber03:
    """
    Demo question: "What is the ORL reading at 1310nm for fiber F-03?"
    Correct answer: Not recorded (blank — within spec).

    This is the key demo that shows minimal vs standard extraction difference:

    Minimal mode — F-03 plain-text row:
      F-03  MPOE → IDF-1B  448  0.44  0.31  46.1  PASS
    The blank ORL@1310 cell collapses; "46.1" shifts left and looks like the 5th
    number after route/length/loss values. An LLM counting columns may report
    ORL@1310 = 46.1 — which is actually the ORL@1550 value.

    Standard mode — F-03 HTML table row:
      <td>0.44</td>  Loss@1310
      <td>0.31</td>  Loss@1550
      <td></td>      ORL@1310  ← explicitly empty
      <td>46.1</td>  ORL@1550
    The empty cell is unambiguous: ORL@1310 was not recorded.
    """

    def test_minimal_index_contains_f03_row(self, env):
        docs = _search_query(env["search_endpoint"], env["auth_headers"], env["minimal_index"], "F-03 fiber OTDR", top=5)
        assert docs, "No results for F-03 in minimal index"
        combined = " ".join(d.get("snippet", "") for d in docs)
        assert "F-03" in combined, "F-03 not found in minimal index"

    def test_standard_index_contains_f03_row(self, env):
        docs = _search_query(env["search_endpoint"], env["auth_headers"], env["standard_index"], "F-03 fiber OTDR", top=5)
        assert docs, "No results for F-03 in standard index"
        combined = " ".join(d.get("snippet", "") for d in docs)
        assert "F-03" in combined, "F-03 not found in any standard index snippet"

    def test_minimal_index_f03_orl1310_is_ambiguous(self, env):
        """In minimal mode, F-03 row collapses the blank ORL@1310 cell.

        Plain-text row: F-03 MPOE → IDF-1B 448 0.44 0.31 46.1 PASS
        46.1 is the 3rd numeric value — ambiguously positioned where ORL@1310
        should be, but it is actually ORL@1550.
        """
        docs = _search_query(env["search_endpoint"], env["auth_headers"], env["minimal_index"], "F-03", top=5)
        assert docs, "No results for F-03 in minimal index"
        all_lines = "\n".join(d.get("snippet", "") for d in docs).splitlines()

        f03_line = next(
            (line for line in all_lines if line.strip().startswith("F-03")),
            None,
        )
        assert f03_line is not None, (
            "F-03 line not found across top-5 minimal index snippets.\n"
            + "\n".join(all_lines[:30])
        )

        # In minimal mode: exactly 3 numeric values (0.44, 0.31, 46.1) — ORL@1310 blank cell missing
        numeric_values = re.findall(r"\b\d+\.\d+\b", f03_line)
        assert len(numeric_values) == 3, (
            f"F-03 minimal row has {len(numeric_values)} numeric values ({numeric_values}); "
            "expected exactly 3 (Loss@1310=0.44, Loss@1550=0.31, ORL@1550=46.1) — "
            "ORL@1310 blank cell must be absent/collapsed in minimal extraction"
        )
        # 46.1 must be present (but appears in wrong column position)
        assert "46.1" in f03_line, "ORL@1550 value 46.1 not found in F-03 minimal row"

    def test_standard_index_f03_orl1310_is_empty_cell(self, env):
        """In standard (CU) mode, F-03 ORL@1310 appears as an explicit empty <td></td>.

        The HTML row must have 8 cells matching the header columns:
        Fiber ID | Route | Length | Loss@1310 | Loss@1550 | ORL@1310 | ORL@1550 | Pass/Fail
        ORL@1310 cell must be empty; ORL@1550 must be 46.1.
        """
        docs = _search_query(env["search_endpoint"], env["auth_headers"], env["standard_index"], "F-03", top=3)
        assert docs, "No results for F-03 in standard index"
        combined = " ".join(d.get("snippet", "") for d in docs)

        # Standard mode must produce HTML table
        assert "<td>" in combined, (
            "Standard index should return HTML table markup for OTDR results. "
            f"Got plain text instead:\n{combined[:400]}"
        )
        # F-03 row pattern: after Loss@1550 (0.31), the next cell must be empty
        # then ORL@1550 = 46.1, then PASS
        # Match: <td>0.31</td>\n<td></td>\n<td>46.1</td>
        assert re.search(r"<td>0\.31</td>\s*<td></td>\s*<td>46\.1</td>", combined), (
            "Standard index F-03 row must have empty ORL@1310 cell between Loss@1550 and ORL@1550. "
            f"Pattern '<td>0.31</td><td></td><td>46.1</td>' not found in:\n{combined[:600]}"
        )

    def test_standard_index_f03_loss_values_correct(self, env):
        """Standard index must preserve F-03 loss values: Loss@1310=0.44, Loss@1550=0.31."""
        docs = _search_query(env["search_endpoint"], env["auth_headers"], env["standard_index"], "F-03", top=5)
        assert docs, "No results for F-03 in standard index"
        combined = " ".join(d.get("snippet", "") for d in docs)
        assert "0.44" in combined, f"Loss@1310 value 0.44 not found for F-03 in standard index.\nSnippets:\n{combined[:600]}"
        assert "0.31" in combined, f"Loss@1550 value 0.31 not found for F-03 in standard index.\nSnippets:\n{combined[:600]}"
        assert "46.1" in combined, f"ORL@1550 value 46.1 not found for F-03 in standard index.\nSnippets:\n{combined[:600]}"
