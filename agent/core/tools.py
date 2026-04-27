"""
Tool system for the agent
Provides ToolSpec and ToolRouter for managing both built-in and MCP tools
"""

import logging
import re
import warnings
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

from fastmcp import Client
from fastmcp.exceptions import ToolError as MCPToolError
from mcp.types import EmbeddedResource, ImageContent, TextContent

from agent.config import MCPServerConfig
from agent.core.tool_results import (
    ToolResult,
    normalize_tool_result,
    tool_result_from_mcp_content,
)
from agent.tools.dataset_tools import (
    HF_INSPECT_DATASET_TOOL_SPEC,
    hf_inspect_dataset_handler,
)
from agent.tools.docs_tools import (
    EXPLORE_HF_DOCS_TOOL_SPEC,
    HF_DOCS_FETCH_TOOL_SPEC,
    explore_hf_docs_handler,
    hf_docs_fetch_handler,
)
from agent.tools.github_find_examples import (
    GITHUB_FIND_EXAMPLES_TOOL_SPEC,
    github_find_examples_handler,
)
from agent.tools.github_list_repos import (
    GITHUB_LIST_REPOS_TOOL_SPEC,
    github_list_repos_handler,
)
from agent.tools.github_read_file import (
    GITHUB_READ_FILE_TOOL_SPEC,
    github_read_file_handler,
)
from agent.tools.hf_repo_files_tool import (
    HF_REPO_FILES_TOOL_SPEC,
    hf_repo_files_handler,
)
from agent.tools.hf_repo_git_tool import (
    HF_REPO_GIT_TOOL_SPEC,
    hf_repo_git_handler,
)
from agent.tools.jobs_tool import HF_JOBS_TOOL_SPEC, hf_jobs_handler
from agent.tools.papers_tool import HF_PAPERS_TOOL_SPEC, hf_papers_handler
from agent.tools.plan_tool import PLAN_TOOL_SPEC, plan_tool_handler
from agent.tools.research_tool import RESEARCH_TOOL_SPEC, research_handler
from agent.tools.sandbox_tool import get_sandbox_tools

# NOTE: Private HF repo tool disabled - replaced by hf_repo_files and hf_repo_git
# from agent.tools.private_hf_repo_tools import (
#     PRIVATE_HF_REPO_TOOL_SPEC,
#     private_hf_repo_handler,
# )

# Suppress aiohttp deprecation warning
warnings.filterwarnings(
    "ignore", category=DeprecationWarning, module="aiohttp.connector"
)

NOT_ALLOWED_TOOL_NAMES = ["hf_jobs", "hf_doc_search", "hf_doc_fetch", "hf_whoami"]


class _FallbackRiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class _FallbackSideEffectLevel(str, Enum):
    NONE = "none"
    AGENT_STATE = "agent_state"
    LOCAL_READ = "local_read"
    LOCAL_WRITE = "local_write"
    LOCAL_EXEC = "local_exec"
    NETWORK_READ = "network_read"
    REMOTE_READ = "remote_read"
    REMOTE_WRITE = "remote_write"
    REMOTE_EXEC = "remote_exec"
    REMOTE_COMPUTE = "remote_compute"
    EXTERNAL_SERVICE = "external_service"


class _FallbackRollbackSupport(str, Enum):
    NOT_NEEDED = "not_needed"
    REPLACEABLE = "replaceable"
    MANUAL = "manual"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class _FallbackBudgetImpact(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class _FallbackCredentialScope(str, Enum):
    NONE = "none"
    LOCAL_FILESYSTEM = "local_filesystem"
    LOCAL_SYSTEM = "local_system"
    HF_TOKEN = "hf_token"
    GITHUB_TOKEN = "github_token"
    MODEL_PROVIDER = "model_provider"
    MCP_SERVER = "mcp_server"


@dataclass(frozen=True)
class _FallbackToolMetadata:
    risk: Any
    side_effect: Any
    rollback: Any
    budget: Any
    credentials: tuple[Any, ...] = ()

    @property
    def credential(self) -> tuple[Any, ...]:
        return self.credentials


@dataclass(frozen=True)
class _FallbackPolicyDecision:
    allowed: bool = True
    requires_approval: bool = False
    reason: str | None = None
    code: str | None = None
    metadata: dict[str, Any] | None = None

    @property
    def denied(self) -> bool:
        return not self.allowed


try:
    from agent.core import policy as _policy
except ImportError:
    _policy = None

RiskLevel = getattr(_policy, "RiskLevel", _FallbackRiskLevel)
SideEffectLevel = getattr(_policy, "SideEffectLevel", _FallbackSideEffectLevel)
RollbackSupport = getattr(_policy, "RollbackSupport", _FallbackRollbackSupport)
BudgetImpact = getattr(_policy, "BudgetImpact", _FallbackBudgetImpact)
CredentialScope = getattr(_policy, "CredentialScope", _FallbackCredentialScope)
ToolMetadata = getattr(_policy, "ToolMetadata", _FallbackToolMetadata)
PolicyDecision = getattr(_policy, "PolicyDecision", _FallbackPolicyDecision)


def _coerce_policy_value(policy_type: Any, value: str) -> Any:
    """Use policy enum/core values when available; keep strings as fallback."""
    if value == "none" and hasattr(policy_type, "READ_ONLY"):
        value = "read_only"
    try:
        return policy_type(value)
    except Exception:
        try:
            return getattr(policy_type, value.upper())
        except Exception:
            return value


def tool_metadata(
    *,
    risk: str,
    side_effect: str,
    rollback: str,
    budget: str,
    credentials: tuple[str, ...] = (),
    source: str | None = None,
    read_only: bool | None = None,
    local: bool | None = None,
    reason: str | None = None,
    mcp_origin: str | None = None,
    mcp_server: str | None = None,
    mcp_tool: str | None = None,
    mcp_trusted: bool | None = None,
    mcp_forwarded_hf_token: bool | None = None,
) -> Any:
    values = {
        "risk": _coerce_policy_value(RiskLevel, risk),
        "side_effect": _coerce_policy_value(SideEffectLevel, side_effect),
        "rollback": _coerce_policy_value(RollbackSupport, rollback),
        "budget": _coerce_policy_value(BudgetImpact, budget),
        "credentials": tuple(
            _coerce_policy_value(CredentialScope, credential)
            for credential in credentials
        ),
    }
    policy_values = {
        "source": source,
        "read_only": read_only,
        "local": local,
        "risk": values["risk"],
        "side_effects": [] if side_effect == "none" else [side_effect],
        "rollback": rollback,
        "budget_impact": budget,
        "credential_usage": list(credentials),
        "reason": reason,
        "mcp_origin": mcp_origin,
        "mcp_server": mcp_server,
        "mcp_tool": mcp_tool,
        "mcp_trusted": mcp_trusted,
        "mcp_forwarded_hf_token": mcp_forwarded_hf_token,
    }

    for candidate in (
        {key: value for key, value in policy_values.items() if value is not None},
        values,
        {**values, "credential": values["credentials"]},
        {**values, "side_effects": values["side_effect"]},
    ):
        try:
            return ToolMetadata(**candidate)
        except Exception:
            continue
    return _FallbackToolMetadata(**values)


def policy_decision(
    *,
    allowed: bool = True,
    requires_approval: bool = False,
    reason: str | None = None,
    code: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    values = {
        "allowed": allowed,
        "requires_approval": requires_approval,
        "reason": reason,
        "code": code,
        "metadata": metadata or {},
    }
    for candidate in (
        values,
        {key: value for key, value in values.items() if key != "code"},
        {**values, "is_allowed": allowed},
    ):
        try:
            return PolicyDecision(**candidate)
        except Exception:
            continue
    return _FallbackPolicyDecision(**values)


def _plain_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain_value(item) for key, item in value.items()}
    return value


def _metadata_field(metadata: Any, field: str, default: Any = None) -> Any:
    if metadata is None:
        return default
    if isinstance(metadata, dict):
        return metadata.get(field, default)
    return getattr(metadata, field, default)


def _decision_field(decision: Any, field: str, default: Any = None) -> Any:
    if isinstance(decision, dict):
        return decision.get(field, default)
    return getattr(decision, field, default)


def _decision_denied(decision: Any) -> bool:
    denied = _decision_field(decision, "denied", None)
    if denied is not None:
        return bool(denied)
    allowed = _decision_field(decision, "allowed", True)
    return not bool(allowed)


def _decision_requires_approval(decision: Any) -> bool:
    return bool(
        _decision_field(
            decision,
            "requires_approval",
            _decision_field(decision, "needs_approval", False),
        )
    )


def _policy_error_metadata(decision: Any, tool_name: str) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "policy_decision": _plain_value(decision),
    }


BUILTIN_DEFAULT_METADATA = tool_metadata(
    risk="medium",
    side_effect="external_service",
    rollback="unknown",
    budget="unknown",
    credentials=(),
)
MCP_DEFAULT_METADATA = tool_metadata(
    risk="unknown",
    side_effect="external_service",
    rollback="unknown",
    budget="unknown",
    credentials=("mcp_server",),
    source="mcp",
)
RESEARCH_METADATA = tool_metadata(
    risk="read_only",
    side_effect="network_read",
    rollback="not_needed",
    budget="medium",
    credentials=("model_provider", "hf_token", "github_token"),
    read_only=True,
)
DOCS_METADATA = tool_metadata(
    risk="read_only",
    side_effect="network_read",
    rollback="not_needed",
    budget="low",
    credentials=(),
    read_only=True,
)
PLAN_METADATA = tool_metadata(
    risk="low",
    side_effect="agent_state",
    rollback="replaceable",
    budget="none",
    credentials=(),
)
HF_READ_METADATA = tool_metadata(
    risk="read_only",
    side_effect="network_read",
    rollback="not_needed",
    budget="low",
    credentials=("hf_token",),
    read_only=True,
)
HF_JOBS_METADATA = tool_metadata(
    risk="high",
    side_effect="remote_compute",
    rollback="manual",
    budget="high",
    credentials=("hf_token",),
)
HF_REPO_WRITE_METADATA = tool_metadata(
    risk="high",
    side_effect="remote_write",
    rollback="partial",
    budget="low",
    credentials=("hf_token",),
)
GITHUB_READ_METADATA = tool_metadata(
    risk="read_only",
    side_effect="network_read",
    rollback="not_needed",
    budget="low",
    credentials=("github_token",),
    read_only=True,
)


def convert_mcp_content_to_string(content: list) -> str:
    """
    Convert MCP content blocks to a string format compatible with LLM messages.

    Based on FastMCP documentation, content can be:
    - TextContent: has .text field
    - ImageContent: has .data and .mimeType fields
    - EmbeddedResource: has .resource field with .text or .blob

    Args:
        content: List of MCP content blocks

    Returns:
        String representation of the content suitable for LLM consumption
    """
    if not content:
        return ""

    parts = []
    for item in content:
        if isinstance(item, TextContent):
            # Extract text from TextContent blocks
            parts.append(item.text)
        elif isinstance(item, ImageContent):
            # TODO: Handle images
            # For images, include a description with MIME type
            parts.append(f"[Image: {item.mimeType}]")
        elif isinstance(item, EmbeddedResource):
            # TODO: Handle embedded resources
            # For embedded resources, try to extract text
            resource = item.resource
            if hasattr(resource, "text") and resource.text:
                parts.append(resource.text)
            elif hasattr(resource, "blob") and resource.blob:
                parts.append(
                    f"[Binary data: {resource.mimeType if hasattr(resource, 'mimeType') else 'unknown'}]"
                )
            else:
                parts.append(
                    f"[Resource: {resource.uri if hasattr(resource, 'uri') else 'unknown'}]"
                )
        else:
            # Fallback: try to convert to string
            parts.append(str(item))

    return "\n".join(parts)


@dataclass
class ToolSpec:
    """Tool specification for LLM"""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Optional[Callable[..., Awaitable[Any]]] = None
    metadata: Optional[Any] = None


@dataclass(frozen=True)
class MCPToolOrigin:
    """Origin map for an LLM-facing MCP tool name."""

    server_name: str
    raw_tool_name: str
    client_tool_name: str
    namespaced_tool_name: str
    trusted: bool
    forwarded_hf_token: bool


@dataclass(frozen=True)
class MCPServerCredentialPolicy:
    """Credential forwarding state for one configured MCP server."""

    server_name: str
    trusted: bool
    explicit_authorization: bool
    forwarded_hf_token: bool


_MCP_NAME_PART_PATTERN = re.compile(r"[^A-Za-z0-9_]+")
_MCP_NAME_UNDERSCORE_PATTERN = re.compile(r"_+")
_DEFAULT_MCP_SERVER_NAME = "default"


def _normalize_mcp_name_part(value: str) -> str:
    normalized = _MCP_NAME_PART_PATTERN.sub("_", str(value).strip().lower())
    normalized = _MCP_NAME_UNDERSCORE_PATTERN.sub("_", normalized).strip("_")
    return normalized or "unnamed"


def _namespaced_mcp_tool_name(server_name: str, raw_tool_name: str) -> str:
    return (
        f"mcp__{_normalize_mcp_name_part(server_name)}"
        f"__{_normalize_mcp_name_part(raw_tool_name)}"
    )


def _headers_have_authorization(headers: dict[str, Any]) -> bool:
    return any(str(key).lower() == "authorization" for key in headers)


def _tool_meta_value(tool: Any, *keys: str) -> Any:
    meta = getattr(tool, "meta", None)
    if meta is None:
        meta = getattr(tool, "_meta", None)
    if hasattr(meta, "model_dump"):
        meta = meta.model_dump()
    if not isinstance(meta, dict):
        meta = {}
    for key in keys:
        if key in meta:
            return meta[key]
    return None


class DefaultToolPolicyEngine:
    """Default router-boundary policy for registered tools.

    The default policy is intentionally conservative about denial: it exposes
    approval requirements but only denies calls when metadata or a delegated
    policy engine explicitly marks the call as blocked.
    """

    def __init__(self, delegate: Any | None = None) -> None:
        self.delegate = delegate if delegate is not None else self._make_delegate()

    def evaluate(
        self,
        *,
        tool: ToolSpec,
        arguments: dict[str, Any],
        session: Any = None,
        config: Any = None,
    ) -> Any:
        delegated = self._evaluate_delegate(
            tool=tool,
            arguments=arguments,
            session=session,
            config=config,
        )
        if delegated is not None:
            if isinstance(delegated, bool):
                return policy_decision(allowed=delegated)
            return delegated

        metadata = tool.metadata or BUILTIN_DEFAULT_METADATA
        risk = str(_plain_value(_metadata_field(metadata, "risk", "medium")))
        deny = bool(_metadata_field(metadata, "deny", False)) or risk in {
            "blocked",
            "denied",
            "forbidden",
        }
        reason = _metadata_field(metadata, "reason", None)
        if deny:
            return policy_decision(
                allowed=False,
                requires_approval=False,
                reason=reason or f"Tool call denied by policy: {tool.name}",
                code="tool_policy_denied",
                metadata={"tool_metadata": _plain_value(metadata)},
            )

        return policy_decision(
            allowed=True,
            requires_approval=self._requires_approval(tool, arguments, risk),
            reason=reason,
            metadata={"tool_metadata": _plain_value(metadata)},
        )

    def _make_delegate(self) -> Any | None:
        if _policy is None:
            return None
        for name in ("DefaultToolPolicyEngine", "DefaultPolicyEngine", "PolicyEngine"):
            engine_cls = getattr(_policy, name, None)
            if engine_cls is None:
                continue
            try:
                return engine_cls()
            except Exception:
                logger.debug("Failed to initialize policy engine %s", name, exc_info=True)
        return None

    def _evaluate_delegate(
        self,
        *,
        tool: ToolSpec,
        arguments: dict[str, Any],
        session: Any = None,
        config: Any = None,
    ) -> Any | None:
        if self.delegate is None:
            return None
        for method_name in ("evaluate_tool_call", "evaluate"):
            method = getattr(self.delegate, method_name, None)
            if method is None:
                continue
            for kwargs in (
                {"tool": tool, "arguments": arguments, "session": session},
                {"tool_spec": tool, "arguments": arguments, "session": session},
                {
                    "tool_name": tool.name,
                    "tool_args": arguments,
                    "config": config,
                    "metadata": tool.metadata,
                },
                {
                    "tool_name": tool.name,
                    "arguments": arguments,
                    "metadata": tool.metadata,
                    "session": session,
                    "config": config,
                },
            ):
                try:
                    return method(**kwargs)
                except TypeError:
                    continue
        return None

    def _requires_approval(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        risk: str,
    ) -> bool:
        if bool(_metadata_field(tool.metadata, "requires_approval", False)):
            return True
        if tool.name == "sandbox_create":
            return True
        if tool.name == "hf_jobs":
            return arguments.get("operation", "") in {
                "run",
                "uv",
                "scheduled run",
                "scheduled uv",
            }
        if tool.name == "hf_repo_files":
            return arguments.get("operation", "") in {"upload", "delete"}
        if tool.name == "hf_repo_git":
            return arguments.get("operation", "") in {
                "delete_branch",
                "delete_tag",
                "merge_pr",
                "create_repo",
                "update_repo",
            }
        return risk == "high"


class ToolRouter:
    """
    Routes tool calls to appropriate handlers.
    Based on codex-rs/core/src/tools/router.rs
    """

    def __init__(
        self,
        mcp_servers: dict[str, MCPServerConfig],
        hf_token: str | None = None,
        local_mode: bool = False,
        policy_engine: Any | None = None,
        trusted_hf_mcp_servers: list[str] | tuple[str, ...] | set[str] | None = None,
    ):
        self.tools: dict[str, ToolSpec] = {}
        self.mcp_servers: dict[str, dict[str, Any]] = {}
        self.mcp_server_credential_policies: dict[str, MCPServerCredentialPolicy] = {}
        self.mcp_tool_origins: dict[str, MCPToolOrigin] = {}
        self._mcp_server_names = list(mcp_servers.keys())
        self._trusted_hf_mcp_servers = set(trusted_hf_mcp_servers or ())
        self.policy_engine = policy_engine or DefaultToolPolicyEngine()

        for tool in create_builtin_tools(local_mode=local_mode):
            self.register_tool(tool)

        self.mcp_client: Client | None = None
        if mcp_servers:
            mcp_servers_payload = {}
            for name, server in mcp_servers.items():
                data = server.model_dump()
                data, credential_policy = self._apply_mcp_credential_policy(
                    name,
                    data,
                    hf_token=hf_token,
                )
                self.mcp_server_credential_policies[name] = credential_policy
                mcp_servers_payload[name] = data
            self.mcp_servers = mcp_servers_payload
            self.mcp_client = Client({"mcpServers": mcp_servers_payload})
        self._mcp_initialized = False

    def register_tool(self, tool: ToolSpec) -> None:
        self.tools[tool.name] = tool

    def _apply_mcp_credential_policy(
        self,
        server_name: str,
        server_data: dict[str, Any],
        *,
        hf_token: str | None,
    ) -> tuple[dict[str, Any], MCPServerCredentialPolicy]:
        data = dict(server_data)
        raw_headers = data.get("headers")
        headers = dict(raw_headers or {}) if isinstance(raw_headers, dict) else {}
        explicit_authorization = _headers_have_authorization(headers)
        trusted = server_name in self._trusted_hf_mcp_servers
        forwarded_hf_token = bool(hf_token and trusted and not explicit_authorization)

        if forwarded_hf_token:
            headers["Authorization"] = f"Bearer {hf_token}"
            data["headers"] = headers
        elif raw_headers is not None:
            data["headers"] = raw_headers

        return data, MCPServerCredentialPolicy(
            server_name=server_name,
            trusted=trusted,
            explicit_authorization=explicit_authorization,
            forwarded_hf_token=forwarded_hf_token,
        )

    async def register_mcp_tools(self) -> None:
        tools = await self.mcp_client.list_tools()
        registered_names = []
        skipped_count = 0
        for tool in tools:
            origin = self._mcp_tool_origin(tool)
            if origin is None:
                skipped_count += 1
                continue
            if origin.raw_tool_name in NOT_ALLOWED_TOOL_NAMES:
                skipped_count += 1
                continue
            if origin.namespaced_tool_name in self.tools:
                skipped_count += 1
                logger.warning(
                    "Skipping MCP tool %s from server %s: namespaced name %s collides with an existing tool",
                    origin.raw_tool_name,
                    origin.server_name,
                    origin.namespaced_tool_name,
                )
                continue
            registered_names.append(origin.namespaced_tool_name)
            self.mcp_tool_origins[origin.namespaced_tool_name] = origin
            self.register_tool(
                ToolSpec(
                    name=origin.namespaced_tool_name,
                    description=tool.description,
                    parameters=tool.inputSchema,
                    handler=None,
                    metadata=self._mcp_metadata_for_origin(origin),
                )
            )
        logger.info(
            f"Loaded {len(registered_names)} MCP tools: {', '.join(registered_names)} ({skipped_count} disabled)"
        )

    def _mcp_tool_origin(self, tool: Any) -> MCPToolOrigin | None:
        client_tool_name = str(tool.name)
        explicit_server = (
            getattr(tool, "server_name", None)
            or _tool_meta_value(tool, "server_name", "mcp_server", "server")
        )
        explicit_raw_tool = (
            getattr(tool, "raw_tool_name", None)
            or _tool_meta_value(tool, "raw_tool_name", "mcp_tool", "tool")
        )

        if explicit_server:
            server_name = str(explicit_server)
            raw_tool_name = str(explicit_raw_tool or client_tool_name)
        else:
            inferred = self._infer_mcp_origin(client_tool_name)
            if inferred is None:
                logger.warning(
                    "Skipping MCP tool %s: could not determine a unique server origin",
                    client_tool_name,
                )
                return None
            server_name, raw_tool_name = inferred

        namespaced_tool_name = _namespaced_mcp_tool_name(server_name, raw_tool_name)
        policy = self.mcp_server_credential_policies.get(
            server_name,
            MCPServerCredentialPolicy(
                server_name=server_name,
                trusted=server_name in self._trusted_hf_mcp_servers,
                explicit_authorization=False,
                forwarded_hf_token=False,
            ),
        )
        return MCPToolOrigin(
            server_name=server_name,
            raw_tool_name=raw_tool_name,
            client_tool_name=client_tool_name,
            namespaced_tool_name=namespaced_tool_name,
            trusted=policy.trusted,
            forwarded_hf_token=policy.forwarded_hf_token,
        )

    def _infer_mcp_origin(self, client_tool_name: str) -> tuple[str, str] | None:
        if len(self._mcp_server_names) == 1:
            return self._mcp_server_names[0], client_tool_name
        if not self._mcp_server_names:
            return _DEFAULT_MCP_SERVER_NAME, client_tool_name

        matches = [
            (server_name, client_tool_name[len(server_name) + 1 :])
            for server_name in self._mcp_server_names
            if client_tool_name.startswith(f"{server_name}_")
            and len(client_tool_name) > len(server_name) + 1
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def _mcp_metadata_for_origin(self, origin: MCPToolOrigin) -> Any:
        credentials = ["mcp_server"]
        if origin.forwarded_hf_token:
            credentials.append("hf_token")
        return tool_metadata(
            risk="unknown",
            side_effect="external_service",
            rollback="unknown",
            budget="unknown",
            credentials=tuple(credentials),
            source="mcp",
            reason=(
                f"MCP tool from server '{origin.server_name}'. "
                f"Trusted HF token forwarding: {origin.trusted}. "
                f"Forwarded user HF token: {origin.forwarded_hf_token}."
            ),
            mcp_origin=f"{origin.server_name}:{origin.raw_tool_name}",
            mcp_server=origin.server_name,
            mcp_tool=origin.raw_tool_name,
            mcp_trusted=origin.trusted,
            mcp_forwarded_hf_token=origin.forwarded_hf_token,
        )

    async def register_openapi_tool(self) -> None:
        """Register the OpenAPI search tool (requires async initialization)"""
        from agent.tools.docs_tools import (
            _get_api_search_tool_spec,
            search_openapi_handler,
        )

        try:
            openapi_spec = await _get_api_search_tool_spec()
            self.register_tool(
                ToolSpec(
                    name=openapi_spec["name"],
                    description=openapi_spec["description"],
                    parameters=openapi_spec["parameters"],
                    handler=search_openapi_handler,
                    metadata=DOCS_METADATA,
                )
            )
            logger.info(f"Loaded OpenAPI search tool: {openapi_spec['name']}")
        except Exception as e:
            logger.warning("Failed to load OpenAPI search tool: %s", e)

    def get_tool_specs_for_llm(self) -> list[dict[str, Any]]:
        """Get tool specifications in OpenAI format"""
        specs = []
        for tool in self.tools.values():
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return specs

    def evaluate_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session: Any = None,
        config: Any = None,
    ) -> Any:
        tool = self.tools.get(tool_name)
        if tool is None:
            return policy_decision(
                allowed=False,
                requires_approval=False,
                reason=f"Unknown tool: {tool_name}",
                code="unknown_tool",
            )
        try:
            return self.policy_engine.evaluate(
                tool=tool,
                arguments=arguments,
                session=session,
                config=config,
            )
        except TypeError:
            return self.policy_engine.evaluate(
                tool=tool,
                arguments=arguments,
                session=session,
            )

    def evaluate_policy(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        config: Any = None,
        session: Any = None,
    ) -> Any:
        return self.evaluate_tool_call(
            tool_name,
            tool_args,
            session=session,
            config=config,
        )

    def evaluate_unregistered_mcp_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session: Any = None,
        config: Any = None,
    ) -> Any:
        tool = ToolSpec(
            name=tool_name,
            description="Unregistered MCP tool",
            parameters={"type": "object", "properties": {}},
            handler=None,
            metadata=MCP_DEFAULT_METADATA,
        )
        try:
            return self.policy_engine.evaluate(
                tool=tool,
                arguments=arguments,
                session=session,
                config=config,
            )
        except TypeError:
            return self.policy_engine.evaluate(
                tool=tool,
                arguments=arguments,
                session=session,
            )

    async def __aenter__(self) -> "ToolRouter":
        if self.mcp_client is not None:
            try:
                await self.mcp_client.__aenter__()
                await self.mcp_client.initialize()
                await self.register_mcp_tools()
                self._mcp_initialized = True
            except Exception as e:
                logger.warning("MCP connection failed, continuing without MCP tools: %s", e)
                self.mcp_client = None

        await self.register_openapi_tool()

        total_tools = len(self.tools)
        logger.info(f"Agent ready with {total_tools} tools total")

        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.mcp_client is not None:
            await self.mcp_client.__aexit__(exc_type, exc, tb)
            self._mcp_initialized = False

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session: Any = None,
        tool_call_id: str | None = None,
        policy_approved: bool = False,
    ) -> tuple[str, bool]:
        """
        Call a tool and return (output_string, success_bool).

        For MCP tools, converts the CallToolResult content blocks to a string.
        For built-in tools, calls their handler directly.
        """
        result = await self.call_tool_result(
            tool_name,
            arguments,
            session=session,
            tool_call_id=tool_call_id,
            policy_approved=policy_approved,
        )
        return result.to_legacy_tuple()

    async def call_tool_result(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session: Any = None,
        tool_call_id: str | None = None,
        policy_approved: bool = False,
    ) -> ToolResult:
        """
        Call a tool and return a structured ToolResult.

        This is the opt-in structured path. call_tool() remains the public
        compatibility API for existing agent-loop consumers.
        """
        tool = self.tools.get(tool_name)
        if tool is not None:
            decision = self.evaluate_tool_call(
                tool_name,
                arguments,
                session=session,
                config=getattr(session, "config", None),
            )
        elif self._mcp_initialized:
            decision = policy_decision(
                allowed=False,
                requires_approval=False,
                reason=(
                    f"Unknown MCP tool: {tool_name}. "
                    "MCP tools must be registered and called by their namespaced name."
                ),
                code="unknown_mcp_tool",
            )
        else:
            decision = None

        if decision is not None and _decision_denied(decision):
            reason = _decision_field(
                decision,
                "reason",
                f"Tool call denied by policy: {tool_name}",
            )
            code = _decision_field(decision, "code", "tool_policy_denied")
            return ToolResult.from_error(
                str(reason),
                code=code,
                kind="policy",
                metadata=_policy_error_metadata(decision, tool_name),
            )
        if (
            decision is not None
            and _decision_requires_approval(decision)
            and not policy_approved
        ):
            reason = _decision_field(
                decision,
                "reason",
                f"Tool call requires approval before execution: {tool_name}",
            )
            return ToolResult.from_error(
                str(reason),
                code="tool_policy_approval_required",
                kind="policy",
                metadata=_policy_error_metadata(decision, tool_name),
            )

        if tool and tool.handler:
            result = await self._call_handler(
                tool.handler,
                arguments,
                session=session,
                tool_call_id=tool_call_id,
            )
            return normalize_tool_result(result)

        # Otherwise, use MCP client
        if self._mcp_initialized and tool is not None:
            try:
                origin = self.mcp_tool_origins.get(tool_name)
                if origin is None:
                    return ToolResult.from_error(
                        f"MCP tool origin missing for {tool_name}",
                        code="mcp_tool_origin_missing",
                        kind="policy",
                    )
                result = await self.mcp_client.call_tool(
                    origin.client_tool_name,
                    arguments,
                )
                return tool_result_from_mcp_content(
                    result.content,
                    is_error=result.is_error,
                    converter=convert_mcp_content_to_string,
                    raw=result,
                )
            except MCPToolError as e:
                # Catch MCP tool errors and return them to the agent
                error_msg = f"Tool error: {str(e)}"
                return ToolResult.from_error(
                    error_msg,
                    code="mcp_tool_error",
                    raw=e,
                )

        return ToolResult.from_error(
            "MCP client not initialized",
            code="mcp_client_not_initialized",
        )

    async def _call_handler(
        self,
        handler: Callable[..., Awaitable[Any]],
        arguments: dict[str, Any],
        session: Any = None,
        tool_call_id: str | None = None,
    ) -> Any:
        import inspect

        sig = inspect.signature(handler)
        if "session" in sig.parameters:
            if "tool_call_id" in sig.parameters:
                return await handler(
                    arguments,
                    session=session,
                    tool_call_id=tool_call_id,
                )
            return await handler(arguments, session=session)
        return await handler(arguments)


# ============================================================================
# BUILT-IN TOOL HANDLERS
# ============================================================================


def create_builtin_tools(local_mode: bool = False) -> list[ToolSpec]:
    """Create built-in tool specifications"""
    # in order of importance
    tools = [
        # Research sub-agent (delegates to read-only tools in independent context)
        ToolSpec(
            name=RESEARCH_TOOL_SPEC["name"],
            description=RESEARCH_TOOL_SPEC["description"],
            parameters=RESEARCH_TOOL_SPEC["parameters"],
            handler=research_handler,
            metadata=RESEARCH_METADATA,
        ),
        # Documentation search tools
        ToolSpec(
            name=EXPLORE_HF_DOCS_TOOL_SPEC["name"],
            description=EXPLORE_HF_DOCS_TOOL_SPEC["description"],
            parameters=EXPLORE_HF_DOCS_TOOL_SPEC["parameters"],
            handler=explore_hf_docs_handler,
            metadata=DOCS_METADATA,
        ),
        ToolSpec(
            name=HF_DOCS_FETCH_TOOL_SPEC["name"],
            description=HF_DOCS_FETCH_TOOL_SPEC["description"],
            parameters=HF_DOCS_FETCH_TOOL_SPEC["parameters"],
            handler=hf_docs_fetch_handler,
            metadata=DOCS_METADATA,
        ),
        # Paper discovery and reading
        ToolSpec(
            name=HF_PAPERS_TOOL_SPEC["name"],
            description=HF_PAPERS_TOOL_SPEC["description"],
            parameters=HF_PAPERS_TOOL_SPEC["parameters"],
            handler=hf_papers_handler,
            metadata=DOCS_METADATA,
        ),
        # Dataset inspection tool (unified)
        ToolSpec(
            name=HF_INSPECT_DATASET_TOOL_SPEC["name"],
            description=HF_INSPECT_DATASET_TOOL_SPEC["description"],
            parameters=HF_INSPECT_DATASET_TOOL_SPEC["parameters"],
            handler=hf_inspect_dataset_handler,
            metadata=HF_READ_METADATA,
        ),
        # Planning and job management tools
        ToolSpec(
            name=PLAN_TOOL_SPEC["name"],
            description=PLAN_TOOL_SPEC["description"],
            parameters=PLAN_TOOL_SPEC["parameters"],
            handler=plan_tool_handler,
            metadata=PLAN_METADATA,
        ),
        ToolSpec(
            name=HF_JOBS_TOOL_SPEC["name"],
            description=HF_JOBS_TOOL_SPEC["description"],
            parameters=HF_JOBS_TOOL_SPEC["parameters"],
            handler=hf_jobs_handler,
            metadata=HF_JOBS_METADATA,
        ),
        # HF Repo management tools
        ToolSpec(
            name=HF_REPO_FILES_TOOL_SPEC["name"],
            description=HF_REPO_FILES_TOOL_SPEC["description"],
            parameters=HF_REPO_FILES_TOOL_SPEC["parameters"],
            handler=hf_repo_files_handler,
            metadata=HF_REPO_WRITE_METADATA,
        ),
        ToolSpec(
            name=HF_REPO_GIT_TOOL_SPEC["name"],
            description=HF_REPO_GIT_TOOL_SPEC["description"],
            parameters=HF_REPO_GIT_TOOL_SPEC["parameters"],
            handler=hf_repo_git_handler,
            metadata=HF_REPO_WRITE_METADATA,
        ),
        ToolSpec(
            name=GITHUB_FIND_EXAMPLES_TOOL_SPEC["name"],
            description=GITHUB_FIND_EXAMPLES_TOOL_SPEC["description"],
            parameters=GITHUB_FIND_EXAMPLES_TOOL_SPEC["parameters"],
            handler=github_find_examples_handler,
            metadata=GITHUB_READ_METADATA,
        ),
        ToolSpec(
            name=GITHUB_LIST_REPOS_TOOL_SPEC["name"],
            description=GITHUB_LIST_REPOS_TOOL_SPEC["description"],
            parameters=GITHUB_LIST_REPOS_TOOL_SPEC["parameters"],
            handler=github_list_repos_handler,
            metadata=GITHUB_READ_METADATA,
        ),
        ToolSpec(
            name=GITHUB_READ_FILE_TOOL_SPEC["name"],
            description=GITHUB_READ_FILE_TOOL_SPEC["description"],
            parameters=GITHUB_READ_FILE_TOOL_SPEC["parameters"],
            handler=github_read_file_handler,
            metadata=GITHUB_READ_METADATA,
        ),
    ]

    # Sandbox or local tools (highest priority)
    if local_mode:
        from agent.tools.local_tools import get_local_tools
        tools = get_local_tools() + tools
    else:
        tools = get_sandbox_tools() + tools

    for tool in tools:
        if tool.metadata is None:
            tool.metadata = BUILTIN_DEFAULT_METADATA

    tool_names = ", ".join([t.name for t in tools])
    logger.info(f"Loaded {len(tools)} built-in tools: {tool_names}")

    return tools
