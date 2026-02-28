"""Ollama advisory audit for rename plan manifests.

This module adds a post-plan, advisory-only LLM review layer that never mutates
rename targets or apply behavior.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from shelfr import __version__
from shelfr.abs.rename import _compute_plan_item_id

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_MODEL = "llama3.1:8b-instruct-q4_K_M"
DEFAULT_OLLAMA_ENDPOINTS = ("http://127.0.0.1:11434",)
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 60
DEFAULT_OLLAMA_MAX_ITEMS = 200
DEFAULT_OLLAMA_BATCH_SIZE = 15
DEFAULT_OLLAMA_WORKERS = 1
DEFAULT_OLLAMA_RETRY_COUNT = 1
DEFAULT_OLLAMA_KEEP_ALIVE = "10m"
AUDIT_PROMPT_VERSION = "v1"

AuditStatus = Literal[
    "ok",
    "timeout",
    "connection_error",
    "http_5xx",
    "http_503_overloaded",
    "invalid_json",
    "schema_error",
    "model_missing",
    "unavailable",
]


@dataclass
class OllamaAuditConfig:
    """Runtime configuration for advisory audit."""

    model: str = DEFAULT_OLLAMA_MODEL
    endpoints: list[str] = field(default_factory=lambda: list(DEFAULT_OLLAMA_ENDPOINTS))
    timeout_seconds: int = DEFAULT_OLLAMA_TIMEOUT_SECONDS
    max_items: int = DEFAULT_OLLAMA_MAX_ITEMS
    batch_size: int = DEFAULT_OLLAMA_BATCH_SIZE
    workers: int = DEFAULT_OLLAMA_WORKERS
    retry_count: int = DEFAULT_OLLAMA_RETRY_COUNT
    debug_dump_dir: Path | None = None
    keep_alive: str = DEFAULT_OLLAMA_KEEP_ALIVE


@dataclass
class OllamaEndpointState:
    """Endpoint readiness and model availability state."""

    endpoint: str
    reachable: bool
    ollama_version: str | None = None
    model_available: bool = False
    disabled_reason: AuditStatus | None = None
    model_details: dict[str, Any] | None = None


@dataclass
class OllamaAuditItem:
    """Single advisory finding for one rename plan item."""

    plan_item_id: str
    source_path: str
    target_path: str | None
    audit_status: AuditStatus
    risk_level: str | None = None
    policy_concerns: list[str] = field(default_factory=list)
    human_review_reason: str | None = None
    suggested_checks: list[str] = field(default_factory=list)
    confidence: float | None = None
    attempted_endpoints: list[str] = field(default_factory=list)
    used_endpoint: str | None = None
    retries_used: int = 0
    duration_ms: int = 0
    error: str | None = None
    error_ref: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "plan_item_id": self.plan_item_id,
            "source_path": self.source_path,
            "target_path": self.target_path,
            "audit_status": self.audit_status,
            "risk_level": self.risk_level,
            "policy_concerns": self.policy_concerns,
            "human_review_reason": self.human_review_reason,
            "suggested_checks": self.suggested_checks,
            "confidence": self.confidence,
            "attempted_endpoints": self.attempted_endpoints,
            "used_endpoint": self.used_endpoint,
            "retries_used": self.retries_used,
            "duration_ms": self.duration_ms,
        }
        # Only include error/error_ref when present to keep JSON compact.
        if self.error_ref:
            d["error_ref"] = self.error_ref
        if self.error:
            d["error"] = self.error
        return d


@dataclass
class OllamaAuditBatchResult:
    """Batch-level execution trace."""

    batch_index: int
    status: AuditStatus
    attempted_endpoints: list[str] = field(default_factory=list)
    used_endpoint: str | None = None
    retries_used: int = 0
    duration_ms: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_index": self.batch_index,
            "status": self.status,
            "attempted_endpoints": self.attempted_endpoints,
            "used_endpoint": self.used_endpoint,
            "retries_used": self.retries_used,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class OllamaAuditReportV1:
    """Top-level advisory report artifact."""

    advisory_only: bool
    generated_at: str
    plan_path: str
    plan_sha256: str
    plan_schema_version: int
    tool_version: str
    audit_prompt_version: str
    model: str
    endpoints: list[str]
    endpoint_versions: dict[str, str | None]
    batches_total: int
    batches_failed: int
    items_selected: int
    items_audited_ok: int
    items_with_errors: int
    failover_count: int
    per_endpoint_attempts: dict[str, int]
    per_endpoint_successes: dict[str, int]
    endpoint_failures_by_reason: dict[str, int]
    endpoints_disabled_due_to_model_missing: list[str]
    warmup_by_endpoint: dict[str, dict[str, Any]]
    warnings: list[str]
    batch_results: list[OllamaAuditBatchResult]
    items: list[OllamaAuditItem]

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": "OllamaAuditReportV1",
            "advisory_only": self.advisory_only,
            "generated_at": self.generated_at,
            "plan_path": self.plan_path,
            "plan_sha256": self.plan_sha256,
            "plan_schema_version": self.plan_schema_version,
            "tool_version": self.tool_version,
            "audit_prompt_version": self.audit_prompt_version,
            "model": self.model,
            "endpoints": self.endpoints,
            "endpoint_versions": self.endpoint_versions,
            "summary": {
                "batches_total": self.batches_total,
                "batches_failed": self.batches_failed,
                "items_selected": self.items_selected,
                "items_audited_ok": self.items_audited_ok,
                "items_with_errors": self.items_with_errors,
                "failover_count": self.failover_count,
                "per_endpoint_attempts": self.per_endpoint_attempts,
                "per_endpoint_successes": self.per_endpoint_successes,
                "endpoint_failures_by_reason": self.endpoint_failures_by_reason,
                "endpoints_disabled_due_to_model_missing": (
                    self.endpoints_disabled_due_to_model_missing
                ),
                "warmup_by_endpoint": self.warmup_by_endpoint,
            },
            "warnings": self.warnings,
            "batch_results": [row.as_dict() for row in self.batch_results],
            "items": [row.as_dict() for row in self.items],
        }


class _BatchFindingModel(BaseModel):
    plan_item_id: str
    risk_level: Literal["low", "medium", "high"]
    policy_concerns: list[str] = Field(default_factory=list)
    human_review_reason: str
    suggested_checks: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=100.0)

    # noinspection PyMethodParameters
    @classmethod
    def _normalize_confidence(cls, v: float) -> float:
        """Accept 0-100 scale and normalise to 0-1."""
        if v > 1.0:
            return round(v / 100.0, 4)
        return v

    def model_post_init(self, __context: Any) -> None:
        object.__setattr__(self, "confidence", self._normalize_confidence(self.confidence))


class _BatchResponseModel(BaseModel):
    items: list[_BatchFindingModel] = Field(default_factory=list)


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _build_format_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "plan_item_id",
                        "risk_level",
                        "policy_concerns",
                        "human_review_reason",
                        "suggested_checks",
                        "confidence",
                    ],
                    "properties": {
                        "plan_item_id": {"type": "string"},
                        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                        "policy_concerns": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "human_review_reason": {"type": "string"},
                        "suggested_checks": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 100},
                    },
                },
            }
        },
    }


def _normalize_endpoints(endpoints: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for endpoint in endpoints:
        cleaned = endpoint.strip().rstrip("/")
        if not cleaned or cleaned in seen:
            continue
        normalized.append(cleaned)
        seen.add(cleaned)
    return normalized


def _extract_model_names(tags_payload: dict[str, Any]) -> set[str]:
    models = tags_payload.get("models", [])
    if not isinstance(models, list):
        return set()
    names: set[str] = set()
    for row in models:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if isinstance(name, str) and name.strip():
            names.add(name.strip())
    return names


def _probe_endpoint(endpoint: str, model: str, timeout_seconds: int) -> OllamaEndpointState:
    state = OllamaEndpointState(endpoint=endpoint, reachable=False)
    timeout = httpx.Timeout(timeout_seconds)
    try:
        with httpx.Client(base_url=endpoint, timeout=timeout, http2=True) as client:
            version_response = client.get("/api/version")
            version_response.raise_for_status()
            version_payload = version_response.json()
            state.ollama_version = str(version_payload.get("version", "")) or None
            state.reachable = True

            tags_response = client.get("/api/tags")
            tags_response.raise_for_status()
            model_names = _extract_model_names(tags_response.json())
            if model not in model_names:
                state.disabled_reason = "model_missing"
                return state

            show_response = client.post("/api/show", json={"model": model})
            if show_response.status_code == 404:
                state.disabled_reason = "model_missing"
                return state
            show_response.raise_for_status()
            show_payload = show_response.json()
            state.model_details = show_payload if isinstance(show_payload, dict) else None
            state.model_available = True
            return state
    except httpx.TimeoutException:
        state.disabled_reason = "timeout"
        return state
    except httpx.ConnectError:
        state.disabled_reason = "connection_error"
        return state
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 503:
            state.disabled_reason = "http_503_overloaded"
        elif exc.response.status_code >= 500:
            state.disabled_reason = "http_5xx"
        else:
            state.disabled_reason = "schema_error"
        return state
    except (json.JSONDecodeError, TypeError, ValueError):
        state.disabled_reason = "invalid_json"
        return state


def _status_from_exception(exc: Exception) -> AuditStatus:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connection_error"
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 503:
            return "http_503_overloaded"
        if exc.response.status_code >= 500:
            return "http_5xx"
        return "schema_error"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    return "schema_error"


def _risk_score(risk_flags: list[str]) -> int:
    score = 0
    flags = set(risk_flags)
    if "low_similarity" in flags:
        score += 100
    if "hierarchy_move" in flags:
        score += 40
    if "tag_removed" in flags:
        score += 30
    if "edge_case_numeric_asin" in flags:
        score += 20
    return score


def _build_prompt(batch: list[dict[str, Any]]) -> str:
    items_payload: list[dict[str, Any]] = []
    for row in batch:
        components = row.get("components", {})
        if not isinstance(components, dict):
            components = {}
        items_payload.append(
            {
                "plan_item_id": row["plan_item_id"],
                "source_path": row.get("source_path"),
                "target_path": row.get("target_path"),
                "reasons": row.get("reasons", []),
                "risk_flags": row.get("risk_flags", []),
                "similarity_percent": row.get("similarity_percent"),
                "components": {
                    "author": components.get("author"),
                    "series": components.get("series"),
                    "volume": components.get("volume"),
                    "title": components.get("title"),
                    "year": components.get("year"),
                    "asin": components.get("asin"),
                    "arc": components.get("arc"),
                    "ripper_tag": components.get("ripper_tag"),
                },
                "conformance": row.get("conformance", {}),
            }
        )

    return (
        "You are reviewing audiobook rename plan candidates.\n"
        "Audit mode: advisory-only.\n"
        "Rules:\n"
        "- Never propose new target paths.\n"
        "- Never propose new author/title/series/asin values.\n"
        "- Only flag policy concerns and suggest human checks.\n"
        "- Return findings keyed by plan_item_id.\n"
        "- Response must match provided JSON schema.\n"
        "Locked policy focus:\n"
        "- hierarchy: Author/Series/Book for series; Author/Book for standalone\n"
        "- arc optional, omit if unreliable\n"
        "- ASIN preserved exactly\n"
        "- preserve [H2OKing] only when present; drop non-allowlisted trailing tags\n"
        "Input items JSON:\n"
        f"{json.dumps({'items': items_payload}, ensure_ascii=True)}"
    )


def _chunk_rows(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[idx : idx + size] for idx in range(0, len(rows), size)]


def _prepare_candidates(plan_payload: dict[str, Any], max_items: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in plan_payload.get("items", []):
        if row.get("status") != "needs_rename":
            continue
        source_path = str(row.get("source_path", ""))
        target_path = row.get("target_path")
        target_str = str(target_path) if target_path else None
        fingerprint = str(row.get("fingerprint")) if row.get("fingerprint") else None
        row_id = row.get("plan_item_id")
        if not isinstance(row_id, str) or not row_id.strip():
            row_id = _compute_plan_item_id(
                source_path=source_path,
                target_path=target_str,
                fingerprint=fingerprint,
            )
        normalized = {
            **row,
            "plan_item_id": row_id,
            "source_path": source_path,
            "target_path": target_str,
            "risk_flags": list(row.get("risk_flags", [])),
            "risk_score": _risk_score(list(row.get("risk_flags", []))),
        }
        candidates.append(normalized)

    candidates.sort(key=lambda row: (-int(row["risk_score"]), str(row["source_path"])))
    return candidates[:max_items]


def _write_debug_dump(
    debug_dir: Path | None,
    batch_index: int,
    prompt: str,
    raw_payload: dict[str, Any] | None,
    parsed_payload: dict[str, Any] | None,
) -> None:
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / f"batch_{batch_index}_prompt.json").write_text(
        json.dumps({"prompt": prompt}, indent=2),
        encoding="utf-8",
    )
    (debug_dir / f"batch_{batch_index}_raw_response.json").write_text(
        json.dumps(raw_payload if raw_payload is not None else {}, indent=2),
        encoding="utf-8",
    )
    (debug_dir / f"batch_{batch_index}_parsed.json").write_text(
        json.dumps(parsed_payload if parsed_payload is not None else {}, indent=2),
        encoding="utf-8",
    )


def _warm_endpoint(
    endpoint: str, cfg: OllamaAuditConfig
) -> tuple[bool, AuditStatus, int, str | None]:
    start = time.perf_counter()
    payload = {
        "model": cfg.model,
        "prompt": "warmup",
        "stream": False,
        "options": {"temperature": 0, "top_p": 1},
        "keep_alive": cfg.keep_alive,
    }
    try:
        with httpx.Client(
            base_url=endpoint,
            timeout=httpx.Timeout(cfg.timeout_seconds),
            http2=True,
        ) as client:
            response = client.post("/api/generate", json=payload)
            if response.status_code == 503:
                duration = int((time.perf_counter() - start) * 1000)
                return False, "http_503_overloaded", duration, "endpoint overloaded during warmup"
            response.raise_for_status()
        duration = int((time.perf_counter() - start) * 1000)
        return True, "ok", duration, None
    except Exception as exc:
        duration = int((time.perf_counter() - start) * 1000)
        return False, _status_from_exception(exc), duration, str(exc)


def _generate_batch(
    endpoint: str,
    batch: list[dict[str, Any]],
    cfg: OllamaAuditConfig,
    batch_index: int,
) -> tuple[bool, AuditStatus, dict[str, Any] | None, dict[str, Any] | None, int, str | None]:
    _ = batch_index
    prompt = _build_prompt(batch)
    payload = {
        "model": cfg.model,
        "prompt": prompt,
        "stream": False,
        "format": _build_format_schema(),
        "options": {"temperature": 0, "top_p": 1},
        "keep_alive": cfg.keep_alive,
    }
    start = time.perf_counter()
    try:
        with httpx.Client(
            base_url=endpoint,
            timeout=httpx.Timeout(cfg.timeout_seconds),
            http2=True,
        ) as client:
            response = client.post("/api/generate", json=payload)
            if response.status_code == 503:
                duration = int((time.perf_counter() - start) * 1000)
                return (
                    False,
                    "http_503_overloaded",
                    {"prompt": prompt},
                    None,
                    duration,
                    "503 overload",
                )
            response.raise_for_status()
            raw_payload = response.json()
    except Exception as exc:
        duration = int((time.perf_counter() - start) * 1000)
        return False, _status_from_exception(exc), {"prompt": prompt}, None, duration, str(exc)

    try:
        response_payload = raw_payload.get("response")
        if isinstance(response_payload, dict):
            parsed_payload = response_payload
        elif isinstance(response_payload, str):
            parsed_payload = json.loads(response_payload)
        else:
            raise json.JSONDecodeError("response was not JSON", doc=str(response_payload), pos=0)

        parsed = _BatchResponseModel.model_validate(parsed_payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        duration = int((time.perf_counter() - start) * 1000)
        return (
            False,
            "schema_error" if isinstance(exc, ValidationError) else "invalid_json",
            {"prompt": prompt, "raw": raw_payload},
            None,
            duration,
            str(exc),
        )

    batch_ids = [str(row["plan_item_id"]) for row in batch]
    returned_ids = [item.plan_item_id for item in parsed.items]
    duplicate_ids = {item_id for item_id in returned_ids if returned_ids.count(item_id) > 1}
    unknown_ids = [item_id for item_id in returned_ids if item_id not in batch_ids]
    missing_ids = [item_id for item_id in batch_ids if item_id not in returned_ids]

    if duplicate_ids or unknown_ids:
        duration = int((time.perf_counter() - start) * 1000)
        details = f"duplicate_ids={sorted(duplicate_ids)} unknown_ids={sorted(set(unknown_ids))}"
        return (
            False,
            "schema_error",
            {"prompt": prompt, "raw": raw_payload},
            None,
            duration,
            details,
        )

    findings = {
        item.plan_item_id: {
            "risk_level": item.risk_level,
            "policy_concerns": item.policy_concerns,
            "human_review_reason": item.human_review_reason,
            "suggested_checks": item.suggested_checks,
            "confidence": float(item.confidence),
        }
        for item in parsed.items
    }
    parsed_output = {
        "prompt": prompt,
        "raw": raw_payload,
        "findings": findings,
        "missing_ids": missing_ids,
    }
    duration = int((time.perf_counter() - start) * 1000)
    return True, "ok", {"prompt": prompt, "raw": raw_payload}, parsed_output, duration, None


def _summarise_error(error: str | None) -> str | None:
    """Create a short, human-readable summary from a verbose error string."""
    if not error:
        return None
    # Pydantic validation errors — extract the essence.
    if "validation error" in error.lower():
        # e.g. "8 validation errors for _BatchResponseModel\nitems.0.confidence ..."
        first_line = error.split("\n")[0]
        # Try to extract the field and reason
        if "confidence" in error:
            return f"{first_line}: confidence out of range (expected 0..1)"
        return first_line
    if len(error) > 120:
        return error[:117] + "..."
    return error


def _build_unavailable_items(
    batch: list[dict[str, Any]],
    *,
    status: AuditStatus,
    attempted_endpoints: list[str],
    retries_used: int,
    duration_ms: int,
    error: str | None,
    batch_index: int | None = None,
) -> list[OllamaAuditItem]:
    error_ref = f"batch:{batch_index}" if batch_index is not None else None
    short_error = _summarise_error(error)
    return [
        OllamaAuditItem(
            plan_item_id=str(row["plan_item_id"]),
            source_path=str(row.get("source_path", "")),
            target_path=(str(row["target_path"]) if row.get("target_path") else None),
            audit_status=status,
            attempted_endpoints=attempted_endpoints,
            used_endpoint=None,
            retries_used=retries_used,
            duration_ms=duration_ms,
            error=short_error,
            error_ref=error_ref,
        )
        for row in batch
    ]


def _build_ok_items(
    batch: list[dict[str, Any]],
    findings: dict[str, Any],
    *,
    attempted_endpoints: list[str],
    used_endpoint: str,
    retries_used: int,
    duration_ms: int,
) -> list[OllamaAuditItem]:
    rows_by_id = {str(row["plan_item_id"]): row for row in batch}
    result: list[OllamaAuditItem] = []
    for item_id, row in rows_by_id.items():
        finding = findings.get(item_id)
        if finding is None:
            result.append(
                OllamaAuditItem(
                    plan_item_id=item_id,
                    source_path=str(row.get("source_path", "")),
                    target_path=(str(row["target_path"]) if row.get("target_path") else None),
                    audit_status="schema_error",
                    attempted_endpoints=attempted_endpoints,
                    used_endpoint=used_endpoint,
                    retries_used=retries_used,
                    duration_ms=duration_ms,
                    error="missing_id_in_batch_response",
                )
            )
            continue
        result.append(
            OllamaAuditItem(
                plan_item_id=item_id,
                source_path=str(row.get("source_path", "")),
                target_path=(str(row["target_path"]) if row.get("target_path") else None),
                audit_status="ok",
                risk_level=str(finding.get("risk_level")),
                policy_concerns=list(finding.get("policy_concerns", [])),
                human_review_reason=str(finding.get("human_review_reason", "")),
                suggested_checks=list(finding.get("suggested_checks", [])),
                confidence=float(finding.get("confidence", 0.0)),
                attempted_endpoints=attempted_endpoints,
                used_endpoint=used_endpoint,
                retries_used=retries_used,
                duration_ms=duration_ms,
            )
        )
    return result


def audit_rename_plan_with_ollama(
    plan_path: Path,
    cfg: OllamaAuditConfig,
) -> OllamaAuditReportV1:
    """Run advisory-only Ollama audit for a rename plan manifest."""
    with open(plan_path, encoding="utf-8") as f:
        plan_payload = json.load(f)

    plan_schema_version = int(plan_payload.get("schema_version", 1))
    endpoint_list = _normalize_endpoints(cfg.endpoints or list(DEFAULT_OLLAMA_ENDPOINTS))
    warnings: list[str] = []
    if cfg.workers > 1:
        warnings.append("ollama_workers>1 is not yet parallelized in v1; running sequentially")

    selected = _prepare_candidates(plan_payload, cfg.max_items)
    batches = _chunk_rows(selected, cfg.batch_size)
    endpoint_states = [
        _probe_endpoint(endpoint, cfg.model, cfg.timeout_seconds) for endpoint in endpoint_list
    ]
    endpoint_versions = {row.endpoint: row.ollama_version for row in endpoint_states}
    disabled_model_missing = [
        row.endpoint for row in endpoint_states if row.disabled_reason == "model_missing"
    ]

    usable_endpoints = [
        row
        for row in endpoint_states
        if row.reachable and row.model_available and row.disabled_reason is None
    ]

    per_endpoint_attempts: dict[str, int] = {row.endpoint: 0 for row in usable_endpoints}
    per_endpoint_successes: dict[str, int] = {row.endpoint: 0 for row in usable_endpoints}
    endpoint_failures_by_reason: dict[str, int] = {}
    batch_results: list[OllamaAuditBatchResult] = []
    findings: list[OllamaAuditItem] = []
    failover_count = 0
    batches_failed = 0
    warmup_by_endpoint: dict[str, dict[str, Any]] = {}

    if not usable_endpoints:
        status: AuditStatus = "unavailable"
        if selected:
            findings.extend(
                _build_unavailable_items(
                    selected,
                    status=status,
                    attempted_endpoints=[row.endpoint for row in endpoint_states],
                    retries_used=0,
                    duration_ms=0,
                    error="no_usable_ollama_endpoints",
                )
            )
            batch_results.append(
                OllamaAuditBatchResult(
                    batch_index=1,
                    status=status,
                    attempted_endpoints=[row.endpoint for row in endpoint_states],
                    error="no_usable_ollama_endpoints",
                )
            )
            batches_failed = 1
        warnings.append("ollama audit unavailable: no reachable endpoint with pinned model")
    else:
        active_idx = 0
        warmed: set[str] = set()

        for batch_index, batch in enumerate(batches, start=1):
            attempted_endpoints: list[str] = []
            retries_used = 0
            last_status: AuditStatus = "unavailable"
            last_error: str | None = None
            batch_done = False

            while active_idx < len(usable_endpoints) and not batch_done:
                endpoint = usable_endpoints[active_idx].endpoint
                attempted_endpoints.append(endpoint)

                if endpoint not in warmed:
                    warm_ok, warm_status, warm_duration, warm_error = _warm_endpoint(endpoint, cfg)
                    warmup_by_endpoint[endpoint] = {
                        "status": warm_status,
                        "duration_ms": warm_duration,
                        "error": warm_error,
                    }
                    if not warm_ok:
                        endpoint_failures_by_reason[warm_status] = (
                            endpoint_failures_by_reason.get(warm_status, 0) + 1
                        )
                        last_status = warm_status
                        last_error = warm_error
                        active_idx += 1
                        if active_idx < len(usable_endpoints):
                            failover_count += 1
                        continue
                    warmed.add(endpoint)

                last_batch_duration_ms = 0
                for attempt in range(cfg.retry_count + 1):
                    per_endpoint_attempts[endpoint] = per_endpoint_attempts.get(endpoint, 0) + 1
                    ok, status, raw_payload, parsed_payload, duration_ms, error = _generate_batch(
                        endpoint=endpoint,
                        batch=batch,
                        cfg=cfg,
                        batch_index=batch_index,
                    )
                    last_batch_duration_ms = duration_ms
                    _write_debug_dump(
                        cfg.debug_dump_dir,
                        batch_index,
                        prompt=(raw_payload or {}).get("prompt", ""),
                        raw_payload=raw_payload,
                        parsed_payload=parsed_payload,
                    )
                    if ok and parsed_payload is not None:
                        per_endpoint_successes[endpoint] = (
                            per_endpoint_successes.get(endpoint, 0) + 1
                        )
                        ok_items = _build_ok_items(
                            batch=batch,
                            findings=dict(parsed_payload.get("findings", {})),
                            attempted_endpoints=attempted_endpoints,
                            used_endpoint=endpoint,
                            retries_used=retries_used,
                            duration_ms=duration_ms,
                        )
                        findings.extend(ok_items)
                        batch_results.append(
                            OllamaAuditBatchResult(
                                batch_index=batch_index,
                                status="ok",
                                attempted_endpoints=attempted_endpoints,
                                used_endpoint=endpoint,
                                retries_used=retries_used,
                                duration_ms=duration_ms,
                            )
                        )
                        batch_done = True
                        break

                    last_status = status
                    last_error = error
                    if attempt < cfg.retry_count:
                        retries_used += 1
                        continue
                    # All retries exhausted for this endpoint — record
                    # one batch-level failure (not per-attempt).
                    endpoint_failures_by_reason[status] = (
                        endpoint_failures_by_reason.get(status, 0) + 1
                    )
                    break

                if batch_done:
                    break

                active_idx += 1
                if active_idx < len(usable_endpoints):
                    failover_count += 1

            if not batch_done:
                batches_failed += 1
                fallback_status = last_status if last_status else "unavailable"
                findings.extend(
                    _build_unavailable_items(
                        batch,
                        status=fallback_status,
                        attempted_endpoints=attempted_endpoints,
                        retries_used=retries_used,
                        duration_ms=last_batch_duration_ms,
                        error=last_error or "failed_all_endpoints",
                        batch_index=batch_index,
                    )
                )
                batch_results.append(
                    OllamaAuditBatchResult(
                        batch_index=batch_index,
                        status=fallback_status,
                        attempted_endpoints=attempted_endpoints,
                        retries_used=retries_used,
                        duration_ms=last_batch_duration_ms,
                        error=last_error or "failed_all_endpoints",
                    )
                )

    items_audited_ok = sum(1 for row in findings if row.audit_status == "ok")
    items_with_errors = sum(1 for row in findings if row.audit_status != "ok")
    return OllamaAuditReportV1(
        advisory_only=True,
        generated_at=datetime.now(UTC).isoformat(),
        plan_path=str(plan_path),
        plan_sha256=_sha256_file(plan_path),
        plan_schema_version=plan_schema_version,
        tool_version=__version__,
        audit_prompt_version=AUDIT_PROMPT_VERSION,
        model=cfg.model,
        endpoints=endpoint_list,
        endpoint_versions=endpoint_versions,
        batches_total=len(batches),
        batches_failed=batches_failed,
        items_selected=len(selected),
        items_audited_ok=items_audited_ok,
        items_with_errors=items_with_errors,
        failover_count=failover_count,
        per_endpoint_attempts=per_endpoint_attempts,
        per_endpoint_successes=per_endpoint_successes,
        endpoint_failures_by_reason=endpoint_failures_by_reason,
        endpoints_disabled_due_to_model_missing=disabled_model_missing,
        warmup_by_endpoint=warmup_by_endpoint,
        warnings=warnings,
        batch_results=batch_results,
        items=findings,
    )
