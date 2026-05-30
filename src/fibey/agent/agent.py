"""
Single agent definition with Foundry Toolbox MCP connection.

The agent calls the Toolbox as one MCP endpoint; the Toolbox dispatches
to individual tools (FoundryIQ, Work Orders OpenAPI, Inventory MCP) behind
the scenes.  When the Toolbox is configured, FoundryIQ provides knowledge
base retrieval; otherwise a local Azure AI Search function tool is used
as a fallback.

When TOOLBOX_MCP_URL is empty the agent falls back to **local-direct mode**:
it connects to the inventory MCP server and work-orders API running on
localhost, bypassing the Toolbox entirely.  Set INVENTORY_MCP_URL and
WORK_ORDERS_API_URL to override the default localhost URLs.
"""

import asyncio
import base64
import os
import json
import logging
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx
from azure.identity import AzureCliCredential, DefaultAzureCredential
from agent_framework import (
    Agent,
    AgentResponseUpdate,
    AgentSession,
    Content,
    FileSkillsSource,
    FunctionTool,
    MCPStreamableHTTPTool,
    Message,
    ResponseStream,
    SkillsProvider,
)
from agent_framework.foundry import FoundryChatClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_prompt.md"
SKILLS_PATH = Path(__file__).parent / "skills"
_TOKEN_SCOPE = "https://ai.azure.com/.default"

# Azure AI Search configuration for direct KB queries
_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "")
_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX", "foundry-iq-docs-index")
# Accept either key; admin key also works for read operations
_SEARCH_API_KEY = os.getenv("AZURE_SEARCH_API_KEY", "") or os.getenv("AZURE_SEARCH_ADMIN_KEY", "")

# Content Understanding (optional)
_CU_ENDPOINT = os.getenv("AZURE_CONTENTUNDERSTANDING_ENDPOINT", "")

# Foundry IQ CU demo — two separate KB MCP endpoints (minimal vs standard ingestion)
_FOUNDRY_IQ_MINIMAL_MCP_URL = os.getenv("FOUNDRY_IQ_MINIMAL_MCP_URL", "")
_FOUNDRY_IQ_STANDARD_MCP_URL = os.getenv("FOUNDRY_IQ_STANDARD_MCP_URL", "")

_SEARCH_TOKEN_SCOPE = "https://search.azure.com/.default"


def _load_system_prompt() -> str:
    """Load the system prompt from markdown file."""
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return "You are Fibey, a helpful AI assistant."


def _get_credential():
    """Get Azure credential, preferring CLI for local dev."""
    try:
        cred = AzureCliCredential()
        cred.get_token(_TOKEN_SCOPE)
        return cred
    except Exception:
        return DefaultAzureCredential()


def _get_token_sync(credential) -> str:
    return credential.get_token(_TOKEN_SCOPE).token


class _ToolboxAuth(httpx.Auth):
    """httpx Auth that injects a fresh bearer token for Toolbox MCP."""
    
    def __init__(self, credential):
        self._credential = credential
    
    def auth_flow(self, request):
        """Add Authorization header with a fresh token on every request."""
        request.headers["Authorization"] = f"Bearer {self._credential.get_token(_TOKEN_SCOPE).token}"
        yield request


class _ToolboxApiKeyAuth(httpx.Auth):
    """httpx Auth that injects the Cognitive Services account key for Toolbox MCP."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    def auth_flow(self, request):
        request.headers["api-key"] = self._api_key
        yield request


def _create_toolbox_mcp(credential) -> MCPStreamableHTTPTool | None:
    """Create the Toolbox MCP tool if endpoint is configured."""
    toolbox_url = os.getenv("TOOLBOX_MCP_URL", "")
    if not toolbox_url:
        logger.warning("TOOLBOX_MCP_URL not set — running without Toolbox")
        return None

    if "api-version" not in toolbox_url:
        separator = "&" if "?" in toolbox_url else "?"
        toolbox_url = f"{toolbox_url}{separator}api-version=v1"
    
    logger.info("Toolbox MCP URL: %s", toolbox_url)

    api_key = os.getenv("TOOLBOX_API_KEY", "")
    if api_key:
        logger.info("Toolbox auth: api-key (TOOLBOX_API_KEY)")
        auth = _ToolboxApiKeyAuth(api_key)
    else:
        logger.info("Toolbox auth: Entra bearer token")
        auth = _ToolboxAuth(credential)

    auth_http_client = httpx.AsyncClient(
        auth=auth,
        headers={"Foundry-Features": "Toolboxes=V1Preview"},
        timeout=120.0,
    )

    return MCPStreamableHTTPTool(
        name="toolbox",
        url=toolbox_url,
        http_client=auth_http_client,
        load_prompts=False,
    )


def _create_foundry_iq_mcp(credential, foundry_iq_mode: str) -> MCPStreamableHTTPTool | None:
    """Create a dedicated KB MCP tool for the Foundry IQ CU demo.

    Returns the appropriate MCP tool based on the ingestion mode:
      "minimal"  → standard text extraction KB (no CU, free tier)
      "standard" → Azure Content Understanding KB (advanced OCR + table parsing)
    """
    url = _FOUNDRY_IQ_MINIMAL_MCP_URL if foundry_iq_mode == "minimal" else _FOUNDRY_IQ_STANDARD_MCP_URL
    if not url:
        logger.warning("FOUNDRY_IQ_%s_MCP_URL not configured — Foundry IQ CU demo unavailable", foundry_iq_mode.upper())
        return None

    # Azure AI Search KB MCP requires api-version for tools/call to work correctly
    if "api-version" not in url:
        url = url + ("&" if "?" in url else "?") + "api-version=2024-07-01"

    logger.info("Foundry IQ KB MCP (%s): %s", foundry_iq_mode, url)

    # header_provider only injects on call_tool(), not on connect()/initialize.
    # Bake auth into the AsyncClient's default_headers so every request is authenticated,
    # including the initial MCP handshake.
    if _SEARCH_API_KEY:
        default_headers = {"api-key": _SEARCH_API_KEY}
    else:
        token = credential.get_token(_SEARCH_TOKEN_SCOPE).token
        default_headers = {"Authorization": f"Bearer {token}"}

    auth_http_client = httpx.AsyncClient(
        headers=default_headers,
        timeout=120.0,
    )

    return MCPStreamableHTTPTool(
        name=f"foundry_iq_{foundry_iq_mode}",
        url=url,
        http_client=auth_http_client,
        load_prompts=False,
    )


async def knowledge_base_search(query: str, top: int = 5) -> str:
    """Search the fiber optics field operations knowledge base.

    Searches across procedures, safety protocols, troubleshooting guides,
    equipment specs, cable types, installation standards, OTDR testing,
    and network architecture documentation.

    Args:
        query: The search query describing what you need to find.
        top: Maximum number of results to return (default 5).

    Returns:
        JSON string with search results including document name and content.
    """
    if not _SEARCH_ENDPOINT:
        return json.dumps({"error": "AZURE_SEARCH_ENDPOINT not configured"})

    search_url = f"{_SEARCH_ENDPOINT}/indexes/{_SEARCH_INDEX}/docs/search?api-version=2024-07-01"
    payload = {
        "search": query,
        "queryType": "semantic",
        "semanticConfiguration": "default",
        "top": top,
        "select": "content,metadata_storage_name",
    }

    if _SEARCH_API_KEY:
        headers = {"api-key": _SEARCH_API_KEY, "Content-Type": "application/json"}
    else:
        token = _get_credential().get_token(_SEARCH_TOKEN_SCOPE).token
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(search_url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for doc in data.get("value", []):
        results.append({
            "source": doc.get("metadata_storage_name", "unknown"),
            "content": doc.get("content", ""),
        })

    return json.dumps({"results": results, "count": len(results)})


def _create_kb_search_tool() -> FunctionTool | None:
    """Create the knowledge base search tool if search is configured.

    Works with either AZURE_SEARCH_API_KEY (key auth) or az login (DefaultAzureCredential).
    """
    if not _SEARCH_ENDPOINT:
        logger.warning("AZURE_SEARCH_ENDPOINT not set — running without KB search")
        return None

    return FunctionTool(
        name="knowledge_base",
        description=(
            "Search the fiber optics field operations knowledge base. "
            "Covers: splicing procedures, safety protocols, OTDR testing, "
            "cable types, equipment specs, installation standards, "
            "network architecture, and troubleshooting guides."
        ),
        func=knowledge_base_search,
    )


# ---------------------------------------------------------------------------
# Local-direct mode: connect to localhost services without Toolbox
# ---------------------------------------------------------------------------

_INVENTORY_MCP_URL = os.getenv("INVENTORY_MCP_URL", "http://localhost:8001")
_WORK_ORDERS_API_URL = os.getenv("WORK_ORDERS_API_URL", "http://localhost:8002")


def _create_local_inventory_mcp() -> MCPStreamableHTTPTool:
    """Connect directly to the local inventory MCP server."""
    url = f"{_INVENTORY_MCP_URL}/mcp"
    logger.info("Local-direct: inventory MCP at %s", url)
    return MCPStreamableHTTPTool(
        name="inventory",
        url=url,
        load_prompts=False,
    )


def _create_work_order_tools() -> list[FunctionTool]:
    """Create FunctionTools that call the local work-orders REST API."""
    base = _WORK_ORDERS_API_URL

    async def list_work_orders(
        status: str | None = None,
        priority: str | None = None,
        assigned_technician: str | None = None,
    ) -> str:
        """List work orders with optional filters.

        Args:
            status: Filter by status (open, in_progress, completed, cancelled).
            priority: Filter by priority (low, medium, high, critical).
            assigned_technician: Filter by technician name.

        Returns:
            JSON string with matching work orders.
        """
        params = {}
        if status:
            params["status"] = status
        if priority:
            params["priority"] = priority
        if assigned_technician:
            params["assigned_technician"] = assigned_technician
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{base}/work-orders", params=params)
            resp.raise_for_status()
            return resp.text

    async def get_work_order(work_order_id: str) -> str:
        """Get details of a specific work order.

        Args:
            work_order_id: The work order ID (e.g. WO-001).

        Returns:
            JSON string with work order details.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{base}/work-orders/{work_order_id}")
            resp.raise_for_status()
            return resp.text

    async def create_work_order(
        title: str,
        description: str,
        priority: str,
        assigned_technician: str,
        location: str,
        due_date: str,
        status: str = "open",
    ) -> str:
        """Create a new work order.

        Args:
            title: Work order title.
            description: Detailed description.
            priority: Priority level (low, medium, high, critical).
            assigned_technician: Technician name.
            location: Job site location.
            due_date: Due date in ISO 8601 format.
            status: Initial status (default: open).

        Returns:
            JSON string with the created work order.
        """
        payload = {
            "title": title,
            "description": description,
            "priority": priority,
            "assigned_technician": assigned_technician,
            "location": location,
            "due_date": due_date,
            "status": status,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{base}/work-orders", json=payload)
            resp.raise_for_status()
            return resp.text

    async def update_work_order(work_order_id: str, **updates: Any) -> str:
        """Update an existing work order.

        Args:
            work_order_id: The work order ID (e.g. WO-001).
            **updates: Fields to update (status, priority, assigned_technician, etc.).

        Returns:
            JSON string with the updated work order.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(
                f"{base}/work-orders/{work_order_id}", json=updates
            )
            resp.raise_for_status()
            return resp.text

    return [
        FunctionTool(
            name="list_work_orders",
            description=(
                "List work orders with optional filters. "
                "Filter by status (open/in_progress/completed/cancelled), "
                "priority (low/medium/high/critical), or assigned_technician."
            ),
            func=list_work_orders,
        ),
        FunctionTool(
            name="get_work_order",
            description="Get full details of a specific work order by its ID (e.g. WO-001).",
            func=get_work_order,
        ),
        FunctionTool(
            name="create_work_order",
            description=(
                "Create a new work order. Requires title, description, priority, "
                "assigned_technician, location, and due_date."
            ),
            func=create_work_order,
        ),
        FunctionTool(
            name="update_work_order",
            description=(
                "Update an existing work order. Pass work_order_id and any fields "
                "to change (status, priority, assigned_technician, location, etc.)."
            ),
            func=update_work_order,
        ),
    ]


_CU_ANALYZER_IDS = {
    "basic": "prebuilt-layout",
    "work_order": "cu_demo_classify_and_analyze",
}


def create_agent(cu_mode: str = "none", foundry_iq_mode: str | None = None) -> tuple[Agent, list]:
    """Create the agent with Foundry client and Toolbox MCP connection.

    When TOOLBOX_MCP_URL is set, all tools are accessed via the single
    Toolbox MCP endpoint.  When it is empty, the agent connects directly
    to local services (inventory MCP on :8001, work-orders API on :8002).

    cu_mode controls Content Understanding:
      "none"       — no CU provider
      "basic"      — prebuilt-layout (general document understanding)
      "work_order" — cu_demo_work_order custom analyzer

    foundry_iq_mode selects the Foundry IQ knowledge base ingestion demo:
      None        — use default Toolbox KB (or local search fallback)
      "minimal"   — standard text extraction KB (contentExtractionMode: minimal)
      "standard"  — Azure Content Understanding KB (contentExtractionMode: standard)
    """
    credential = _get_credential()

    client = FoundryChatClient(
        credential=credential,
    )

    tools = []
    toolbox_mcp = _create_toolbox_mcp(credential)
    if toolbox_mcp:
        tools.append(toolbox_mcp)
    else:
        # Local-direct mode: connect to individual services
        logger.info("Local-direct mode: connecting to local services")
        tools.append(_create_local_inventory_mcp())
        tools.extend(_create_work_order_tools())

        # Add KB search as fallback if configured
        kb_tool = _create_kb_search_tool()
        if kb_tool:
            tools.append(kb_tool)

    # Foundry IQ CU demo: add the mode-specific KB MCP alongside existing tools.
    # The KB contains indexed field documents (OTDR reports, etc.) — the agent
    # uses live inventory/work-order APIs for operational data AND the KB for
    # document-based queries, which is the realistic production pattern.
    if foundry_iq_mode in ("minimal", "standard"):
        iq_mcp = _create_foundry_iq_mcp(credential, foundry_iq_mode)
        if iq_mcp:
            tools.append(iq_mcp)
            logger.info("Foundry IQ CU demo KB added: mode=%s", foundry_iq_mode)

    # Context providers
    context_providers = []

    skills_provider = None
    if SKILLS_PATH.is_dir():
        skills_source = FileSkillsSource(SKILLS_PATH)
        skills_provider = SkillsProvider(skills_source)
        context_providers.append(skills_provider)

    # Content Understanding provider (optional — driven by cu_mode)
    analyzer_id = _CU_ANALYZER_IDS.get(cu_mode)
    if analyzer_id and _CU_ENDPOINT:
        from agent_framework.foundry import ContentUnderstandingContextProvider
        cu_provider = ContentUnderstandingContextProvider(
            endpoint=_CU_ENDPOINT,
            credential=credential,
            analyzer_id=analyzer_id,
            output_sections=["markdown", "fields"],
            max_wait=None,  # Wait until analysis completes (no background deferral)
        )
        context_providers.append(cu_provider)
        logger.info("Content Understanding enabled: mode=%s analyzer=%s", cu_mode, analyzer_id)

    agent = Agent(
        client=client,
        name="fibey",
        instructions=_load_system_prompt(),
        tools=tools,
        context_providers=context_providers if context_providers else None,
    )

    return agent, tools


async def run_agent(
    message: str,
    session: dict,
    attachments: list[dict] | None = None,
    cu_mode: str = "none",
    foundry_iq_mode: str | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Run the agent and yield streaming events.

    Events yielded:
    - {"type": "delta", "content": "..."}
    - {"type": "activity", "tool": "...", "status": "...", "detail": "..."}
    - {"type": "citation", "source": "...", "url": "..."}
    """
    # OpenAI natively supports only images and PDF (via vision).
    # In None mode: detect unsupported types and surface a visible warning,
    # then let the agent run anyway — the confusing response demonstrates OpenAI's limitation.
    _OPENAI_SUPPORTED_TYPES = {
        "image/jpeg", "image/png", "image/gif", "image/webp",
        "application/pdf",
    }
    if cu_mode == "none" and attachments:
        unsupported = [
            att.get("name", "file")
            for att in attachments
            if att.get("type", "") not in _OPENAI_SUPPORTED_TYPES
        ]
        if unsupported:
            names = ", ".join(f"`{n}`" for n in unsupported)
            ext = unsupported[0].rsplit(".", 1)[-1].upper() if "." in unsupported[0] else "this file type"
            yield {
                "type": "warning",
                "content": (
                    f"⚠️ **Azure OpenAI cannot read {names}.** "
                    f"Azure OpenAI only supports images and PDF natively — "
                    f"**.{ext} files are silently ignored.** "
                    f"See the response below, then switch to **Parse: prebuilt-layout** or **Classify & Analyze** to unlock document understanding."
                ),
            }

    agent, tools = create_agent(cu_mode=cu_mode, foundry_iq_mode=foundry_iq_mode)

    agent_session = session.get("agent_session")
    if not agent_session:
        agent_session = AgentSession()
        session["agent_session"] = agent_session

    # Build input: text + optional file attachments as Content objects
    input_content: list[Any] = [message]
    if attachments:
        for att in attachments:
            data_url = att.get("data_url", "")
            filename = att.get("name", "file")
            media_type = att.get("type", "application/octet-stream")
            if not data_url:
                continue
            # Extract raw bytes from data URL
            if "," in data_url:
                raw_b64 = data_url.split(",", 1)[1]
                file_bytes = base64.b64decode(raw_b64)
            else:
                file_bytes = base64.b64decode(data_url)

            if cu_mode != "none" and _CU_ENDPOINT:
                # CU mode: namespace filename so the same file can be re-analyzed
                # under a different mode without hitting the session duplicate check.
                namespaced_filename = f"{filename}:{cu_mode}"
                input_content.append(
                    Content.from_data(
                        file_bytes,
                        media_type,
                        additional_properties={"filename": namespaced_filename},
                    )
                )
                logger.info("Attached file (CU): %s as %s (%s, %d bytes)", filename, namespaced_filename, media_type, len(file_bytes))
            else:
                # None mode: pass raw file bytes directly to OpenAI (no CU processing).
                # OpenAI will reject unsupported types (e.g. docx) — this is intentional
                # to demonstrate the contrast with CU modes.
                input_content.append(
                    Content.from_data(
                        file_bytes,
                        media_type,
                        additional_properties={"filename": filename},
                    )
                )
                logger.info("Attached file (OpenAI only): %s (%s, %d bytes)", filename, media_type, len(file_bytes))

    async with AsyncExitStack() as stack:
        # Initialize MCP tools
        for tool in tools:
            if isinstance(tool, MCPStreamableHTTPTool):
                await stack.enter_async_context(tool)

        # Use enriched input when files are attached, plain text otherwise
        agent_input = input_content if len(input_content) > 1 else message

        stream = agent.run(
            agent_input,
            stream=True,
            session=agent_session,
        )

        # Track tool calls to deduplicate streaming repeats and map results back
        seen_calls: set[str] = set()
        seen_results: set[str] = set()
        seen_skill_loads: set[str] = set()  # dedupe repeated load_skill for same skill
        seen_tool_args: set[str] = set()    # dedupe repeated tool calls with same args
        call_id_to_name: dict[str, str] = {}
        pending_args: dict[str, str] = {}
        suppressed_call_ids: set[str] = set()  # call_ids whose events should be hidden

        try:
            async for update in stream:
                update: AgentResponseUpdate

                if update.contents:
                    for content in update.contents:
                        ctype = content.type

                        if ctype == "text":
                            yield {"type": "delta", "content": content.text or ""}

                        elif ctype in ("mcp_server_tool_call", "function_call"):
                            tool_name = getattr(content, "tool_name", None) or getattr(content, "name", None) or "tool"
                            call_id = getattr(content, "call_id", None) or tool_name
                            call_id_to_name[call_id] = tool_name
                            # Accumulate arguments across streaming chunks
                            raw_args = getattr(content, "arguments", None) or ""
                            if isinstance(raw_args, dict):
                                raw_args = json.dumps(raw_args)
                            if call_id not in pending_args:
                                pending_args[call_id] = raw_args
                                # Try to detect duplicates early (works when args arrive in one chunk)
                                skip = False
                                if tool_name == "load_skill":
                                    try:
                                        parsed = json.loads(raw_args) if raw_args else {}
                                        skill_key = parsed.get("skill_name", "")
                                    except Exception:
                                        skill_key = ""
                                    if skill_key and skill_key in seen_skill_loads:
                                        skip = True
                                    elif skill_key:
                                        seen_skill_loads.add(skill_key)
                                elif raw_args:
                                    try:
                                        json.loads(raw_args)  # only dedup if args are complete JSON
                                        tool_args_key = f"{tool_name}::{raw_args}"
                                        if tool_args_key in seen_tool_args:
                                            skip = True
                                            suppressed_call_ids.add(call_id)
                                    except (ValueError, TypeError):
                                        pass  # incomplete args, can't dedup yet
                                if not skip:
                                    # Emit an early "running" activity so the UI shows a spinner
                                    yield {
                                        "type": "activity",
                                        "tool": tool_name,
                                        "call_id": call_id,
                                        "status": "running",
                                        "detail": f"Calling {tool_name}...",
                                    }
                            else:
                                pending_args[call_id] += raw_args

                        elif ctype in ("mcp_server_tool_result", "function_result"):
                            call_id = getattr(content, "call_id", None) or ""
                            tool_name = call_id_to_name.get(call_id) or getattr(content, "tool_name", None) or getattr(content, "name", None) or "tool"

                            # Emit the "running" activity with full accumulated args
                            if call_id not in seen_calls:
                                seen_calls.add(call_id)
                                args_str = pending_args.get(call_id, "")

                                # Suppress duplicate load_skill for same skill name
                                if tool_name == "load_skill":
                                    try:
                                        parsed = json.loads(args_str) if args_str else {}
                                        skill_name = parsed.get("skill_name", "")
                                    except Exception:
                                        skill_name = ""
                                    if skill_name and skill_name in seen_skill_loads:
                                        seen_results.add(call_id)
                                        suppressed_call_ids.add(call_id)
                                        continue
                                    if skill_name:
                                        seen_skill_loads.add(skill_name)
                                        detail = f"Loading skill: {skill_name}"
                                    else:
                                        detail = f"Calling {tool_name}..."
                                else:
                                    # Suppress duplicate tool calls with identical name+args
                                    tool_args_key = f"{tool_name}::{args_str}"
                                    if tool_args_key in seen_tool_args:
                                        seen_results.add(call_id)
                                        suppressed_call_ids.add(call_id)
                                        continue
                                    seen_tool_args.add(tool_args_key)

                                    detail = f"Calling {tool_name}..."
                                    try:
                                        parsed = json.loads(args_str) if args_str else {}
                                        if isinstance(parsed, dict):
                                            for key in ("work_order_id", "part_id", "query"):
                                                val = parsed.get(key)
                                                if val:
                                                    detail = f"Calling {tool_name} ({key}={val})"
                                                    break
                                    except Exception:
                                        pass
                                yield {
                                    "type": "activity",
                                    "tool": tool_name,
                                    "call_id": call_id,
                                    "status": "running",
                                    "detail": detail,
                                    "args": args_str,
                                }

                            # Emit the "complete" activity
                            if call_id not in seen_results:
                                seen_results.add(call_id)
                                yield {
                                    "type": "activity",
                                    "tool": tool_name,
                                    "call_id": call_id,
                                    "status": "complete",
                                    "detail": f"Completed {tool_name}",
                                }

                        else:
                            # Log unknown content types for debugging
                            import logging
                            logging.getLogger(__name__).debug(
                                "Unknown content type: %s attrs=%s",
                                ctype,
                                {k: str(v)[:100] for k, v in vars(content).items()} if hasattr(content, '__dict__') else str(content)[:200]
                            )
        except Exception as e:
            # Catch OpenAI / agent framework errors and yield a clean readable message.
            # This is especially important for None mode + unsupported file types:
            # OpenAI returns 400 "missing required parameter" when Content.from_data
            # receives a media type it cannot process (e.g. docx).
            err_str = str(e)
            # Extract just the human-readable OpenAI message if present
            import re as _re
            match = _re.search(r"'message':\s*['\"](.+?)['\"]", err_str)
            if match:
                clean = match.group(1)
                yield {"type": "delta", "content": f"❌ {clean}"}
            else:
                yield {"type": "delta", "content": f"❌ Agent error: {err_str}"}

