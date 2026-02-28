"""Tests for advisory Ollama audit of ABS rename plans."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from shelfr.abs.rename import _compute_plan_item_id
from shelfr.abs.rename_ollama_audit import (
    OllamaAuditConfig,
    OllamaEndpointState,
    _generate_batch,
    _prepare_candidates,
    audit_rename_plan_with_ollama,
)


def _make_plan_item(
    idx: int,
    *,
    source_path: str | None = None,
    status: str = "needs_rename",
    risk_flags: list[str] | None = None,
    include_plan_item_id: bool = True,
) -> dict[str, Any]:
    source = source_path or f"/library/source_{idx}"
    target = f"/library/target_{idx}"
    fingerprint = f"fp-{idx}"
    item: dict[str, Any] = {
        "source_path": source,
        "target_path": target,
        "status": status,
        "risk_flags": risk_flags or [],
        "reasons": ["canonicalization_required"],
        "fingerprint": fingerprint,
        "components": {},
        "conformance": {},
    }
    if include_plan_item_id:
        item["plan_item_id"] = _compute_plan_item_id(source, target, fingerprint)
    return item


def _write_plan(tmp_path: Path, items: list[dict[str, Any]]) -> Path:
    payload = {
        "version": "RenamePlanV1",
        "schema_version": 2,
        "generated_at": "2026-02-15T00:00:00+00:00",
        "source_dir": "/library",
        "policy": {},
        "summary": {},
        "conflicts": {},
        "items": items,
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")
    return plan_path


def test_plan_item_id_is_deterministic_when_missing() -> None:
    plan_payload = {
        "items": [
            _make_plan_item(
                1,
                include_plan_item_id=False,
                source_path="/library/a",
            ),
        ]
    }

    first = _prepare_candidates(plan_payload, max_items=10)
    second = _prepare_candidates(plan_payload, max_items=10)

    assert len(first) == 1
    assert first[0]["plan_item_id"] == second[0]["plan_item_id"]
    assert first[0]["plan_item_id"] == _compute_plan_item_id(
        "/library/a",
        "/library/target_1",
        "fp-1",
    )


def test_risk_score_sort_order_is_deterministic() -> None:
    plan_payload = {
        "items": [
            _make_plan_item(1, source_path="/library/c", risk_flags=["low_similarity"]),
            _make_plan_item(
                2,
                source_path="/library/a",
                risk_flags=["hierarchy_move", "tag_removed"],
            ),
            _make_plan_item(3, source_path="/library/b", risk_flags=["hierarchy_move"]),
            _make_plan_item(4, source_path="/library/d", risk_flags=[]),
        ]
    }

    rows = _prepare_candidates(plan_payload, max_items=10)
    assert [row["source_path"] for row in rows] == [
        "/library/c",  # 100
        "/library/a",  # 70
        "/library/b",  # 40
        "/library/d",  # 0
    ]


class _DummyResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://ollama/api/generate")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("http error", request=request, response=response)

    def json(self) -> dict[str, Any]:
        return self._payload


class _DummyClient:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self.payload = payload

    def __enter__(self) -> _DummyClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, _path: str, **kwargs: Any) -> _DummyResponse:
        payload = kwargs["json"]
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0
        assert payload["options"]["top_p"] == 1
        assert isinstance(payload["format"], dict)
        return _DummyResponse(self.status_code, self.payload)


def test_generate_batch_schema_success(monkeypatch: pytest.MonkeyPatch) -> None:
    batch = [
        _make_plan_item(1),
        _make_plan_item(2),
    ]
    payload = {
        "response": json.dumps(
            {
                "items": [
                    {
                        "plan_item_id": batch[0]["plan_item_id"],
                        "risk_level": "low",
                        "policy_concerns": [],
                        "human_review_reason": "looks fine",
                        "suggested_checks": ["spot-check"],
                        "confidence": 0.7,
                    },
                    {
                        "plan_item_id": batch[1]["plan_item_id"],
                        "risk_level": "medium",
                        "policy_concerns": ["tag policy"],
                        "human_review_reason": "possible trailing tag issue",
                        "suggested_checks": ["verify bracket tag"],
                        "confidence": 0.6,
                    },
                ]
            }
        )
    }

    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit.httpx.Client",
        lambda *args, **kwargs: _DummyClient(200, payload),
    )

    ok, status, _raw, parsed, _duration, _error = _generate_batch(
        endpoint="http://ollama",
        batch=batch,
        cfg=OllamaAuditConfig(),
        batch_index=1,
    )
    assert ok is True
    assert status == "ok"
    assert parsed is not None
    assert set(parsed["findings"]) == {batch[0]["plan_item_id"], batch[1]["plan_item_id"]}


def test_generate_batch_rejects_duplicate_or_unknown_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = [_make_plan_item(1), _make_plan_item(2)]

    duplicate_payload = {
        "response": json.dumps(
            {
                "items": [
                    {
                        "plan_item_id": batch[0]["plan_item_id"],
                        "risk_level": "high",
                        "policy_concerns": [],
                        "human_review_reason": "x",
                        "suggested_checks": [],
                        "confidence": 0.5,
                    },
                    {
                        "plan_item_id": batch[0]["plan_item_id"],
                        "risk_level": "low",
                        "policy_concerns": [],
                        "human_review_reason": "y",
                        "suggested_checks": [],
                        "confidence": 0.5,
                    },
                ]
            }
        )
    }
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit.httpx.Client",
        lambda *args, **kwargs: _DummyClient(200, duplicate_payload),
    )
    ok, status, _raw, _parsed, _duration, _error = _generate_batch(
        endpoint="http://ollama",
        batch=batch,
        cfg=OllamaAuditConfig(),
        batch_index=1,
    )
    assert ok is False
    assert status == "schema_error"

    unknown_payload = {
        "response": json.dumps(
            {
                "items": [
                    {
                        "plan_item_id": "unknown-id",
                        "risk_level": "high",
                        "policy_concerns": [],
                        "human_review_reason": "x",
                        "suggested_checks": [],
                        "confidence": 0.5,
                    }
                ]
            }
        )
    }
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit.httpx.Client",
        lambda *args, **kwargs: _DummyClient(200, unknown_payload),
    )
    ok, status, _raw, _parsed, _duration, _error = _generate_batch(
        endpoint="http://ollama",
        batch=batch,
        cfg=OllamaAuditConfig(),
        batch_index=1,
    )
    assert ok is False
    assert status == "schema_error"


def test_generate_batch_handles_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    batch = [_make_plan_item(1)]
    payload = {"response": "not-json"}
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit.httpx.Client",
        lambda *args, **kwargs: _DummyClient(200, payload),
    )
    ok, status, _raw, _parsed, _duration, _error = _generate_batch(
        endpoint="http://ollama",
        batch=batch,
        cfg=OllamaAuditConfig(),
        batch_index=1,
    )
    assert ok is False
    assert status == "invalid_json"


def test_report_metadata_fields_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    items = [_make_plan_item(1), _make_plan_item(2)]
    plan_path = _write_plan(tmp_path, items)

    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._probe_endpoint",
        lambda endpoint, model, timeout: OllamaEndpointState(
            endpoint=endpoint,
            reachable=True,
            ollama_version="0.5.7",
            model_available=True,
            disabled_reason=None,
        ),
    )
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._warm_endpoint",
        lambda endpoint, cfg: (True, "ok", 6, None),
    )

    def _ok_generate(endpoint, batch, cfg, batch_index):
        findings = {
            row["plan_item_id"]: {
                "risk_level": "low",
                "policy_concerns": [],
                "human_review_reason": "ok",
                "suggested_checks": [],
                "confidence": 0.9,
            }
            for row in batch
        }
        return True, "ok", {"prompt": "p"}, {"findings": findings, "missing_ids": []}, 11, None

    monkeypatch.setattr("shelfr.abs.rename_ollama_audit._generate_batch", _ok_generate)

    report = audit_rename_plan_with_ollama(
        plan_path=plan_path,
        cfg=OllamaAuditConfig(endpoints=["http://e1"], batch_size=1),
    )

    assert report.plan_sha256
    assert report.plan_schema_version == 2
    assert report.audit_prompt_version == "v1"
    assert report.tool_version
    assert report.warmup_by_endpoint["http://e1"]["status"] == "ok"


def test_sticky_primary_endpoint_routing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan_path = _write_plan(tmp_path, [_make_plan_item(1), _make_plan_item(2), _make_plan_item(3)])
    calls: list[str] = []

    def _probe(endpoint, model, timeout):
        return OllamaEndpointState(
            endpoint=endpoint,
            reachable=True,
            ollama_version="0.5.7",
            model_available=True,
            disabled_reason=None,
        )

    def _ok_generate(endpoint, batch, cfg, batch_index):
        calls.append(endpoint)
        findings = {
            row["plan_item_id"]: {
                "risk_level": "low",
                "policy_concerns": [],
                "human_review_reason": "ok",
                "suggested_checks": [],
                "confidence": 0.9,
            }
            for row in batch
        }
        return True, "ok", {"prompt": "p"}, {"findings": findings, "missing_ids": []}, 7, None

    monkeypatch.setattr("shelfr.abs.rename_ollama_audit._probe_endpoint", _probe)
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._warm_endpoint",
        lambda endpoint, cfg: (True, "ok", 5, None),
    )
    monkeypatch.setattr("shelfr.abs.rename_ollama_audit._generate_batch", _ok_generate)

    report = audit_rename_plan_with_ollama(
        plan_path=plan_path,
        cfg=OllamaAuditConfig(endpoints=["http://primary", "http://secondary"], batch_size=1),
    )
    assert calls == ["http://primary", "http://primary", "http://primary"]
    assert report.failover_count == 0


def test_midrun_failover_sticks_to_secondary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = _write_plan(tmp_path, [_make_plan_item(1), _make_plan_item(2), _make_plan_item(3)])
    calls: list[tuple[str, int]] = []

    def _probe(endpoint, model, timeout):
        return OllamaEndpointState(
            endpoint=endpoint,
            reachable=True,
            ollama_version="0.5.7",
            model_available=True,
            disabled_reason=None,
        )

    def _generate(endpoint, batch, cfg, batch_index):
        calls.append((endpoint, batch_index))
        if endpoint == "http://primary" and batch_index >= 2:
            return False, "http_503_overloaded", {"prompt": "p"}, None, 9, "overloaded"
        findings = {
            row["plan_item_id"]: {
                "risk_level": "low",
                "policy_concerns": [],
                "human_review_reason": "ok",
                "suggested_checks": [],
                "confidence": 0.9,
            }
            for row in batch
        }
        return True, "ok", {"prompt": "p"}, {"findings": findings, "missing_ids": []}, 8, None

    monkeypatch.setattr("shelfr.abs.rename_ollama_audit._probe_endpoint", _probe)
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._warm_endpoint",
        lambda endpoint, cfg: (True, "ok", 5, None),
    )
    monkeypatch.setattr("shelfr.abs.rename_ollama_audit._generate_batch", _generate)

    report = audit_rename_plan_with_ollama(
        plan_path=plan_path,
        cfg=OllamaAuditConfig(
            endpoints=["http://primary", "http://secondary"],
            batch_size=1,
            retry_count=0,
        ),
    )
    assert calls == [
        ("http://primary", 1),
        ("http://primary", 2),
        ("http://secondary", 2),
        ("http://secondary", 3),
    ]
    assert report.failover_count == 1
    assert report.endpoint_failures_by_reason.get("http_503_overloaded") == 1
    assert report.per_endpoint_successes["http://primary"] == 1
    assert report.per_endpoint_successes["http://secondary"] == 2
    assert report.per_endpoint_attempts["http://primary"] == 2
    assert report.per_endpoint_attempts["http://secondary"] == 2


def test_model_missing_endpoint_is_skipped_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = _write_plan(tmp_path, [_make_plan_item(1)])

    def _probe(endpoint, model, timeout):
        if endpoint == "http://missing":
            return OllamaEndpointState(
                endpoint=endpoint,
                reachable=True,
                ollama_version="0.5.7",
                model_available=False,
                disabled_reason="model_missing",
            )
        return OllamaEndpointState(
            endpoint=endpoint,
            reachable=True,
            ollama_version="0.5.7",
            model_available=True,
            disabled_reason=None,
        )

    def _ok_generate(endpoint, batch, cfg, batch_index):
        findings = {
            row["plan_item_id"]: {
                "risk_level": "low",
                "policy_concerns": [],
                "human_review_reason": "ok",
                "suggested_checks": [],
                "confidence": 0.9,
            }
            for row in batch
        }
        return True, "ok", {"prompt": "p"}, {"findings": findings, "missing_ids": []}, 5, None

    monkeypatch.setattr("shelfr.abs.rename_ollama_audit._probe_endpoint", _probe)
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._warm_endpoint",
        lambda endpoint, cfg: (True, "ok", 3, None),
    )
    monkeypatch.setattr("shelfr.abs.rename_ollama_audit._generate_batch", _ok_generate)

    report = audit_rename_plan_with_ollama(
        plan_path=plan_path,
        cfg=OllamaAuditConfig(endpoints=["http://missing", "http://healthy"]),
    )
    assert report.endpoints_disabled_due_to_model_missing == ["http://missing"]
    assert report.per_endpoint_successes == {"http://healthy": 1}
    assert report.per_endpoint_attempts == {"http://healthy": 1}


def test_all_model_missing_is_unavailable_non_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = _write_plan(tmp_path, [_make_plan_item(1), _make_plan_item(2)])

    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._probe_endpoint",
        lambda endpoint, model, timeout: OllamaEndpointState(
            endpoint=endpoint,
            reachable=True,
            ollama_version="0.5.7",
            model_available=False,
            disabled_reason="model_missing",
        ),
    )

    report = audit_rename_plan_with_ollama(
        plan_path=plan_path,
        cfg=OllamaAuditConfig(endpoints=["http://e1", "http://e2"]),
    )
    assert report.batches_failed == 1
    assert all(item.audit_status == "unavailable" for item in report.items)
    assert report.endpoints_disabled_due_to_model_missing == ["http://e1", "http://e2"]


def test_missing_ids_create_synthetic_schema_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = _write_plan(tmp_path, [_make_plan_item(1), _make_plan_item(2)])

    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._probe_endpoint",
        lambda endpoint, model, timeout: OllamaEndpointState(
            endpoint=endpoint,
            reachable=True,
            ollama_version="0.5.7",
            model_available=True,
            disabled_reason=None,
        ),
    )
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._warm_endpoint",
        lambda endpoint, cfg: (True, "ok", 4, None),
    )

    def _partial_generate(endpoint, batch, cfg, batch_index):
        first = batch[0]
        findings = {
            first["plan_item_id"]: {
                "risk_level": "medium",
                "policy_concerns": ["manual_check"],
                "human_review_reason": "only first item returned",
                "suggested_checks": ["inspect batch"],
                "confidence": 0.5,
            }
        }
        return True, "ok", {"prompt": "p"}, {"findings": findings, "missing_ids": []}, 10, None

    monkeypatch.setattr("shelfr.abs.rename_ollama_audit._generate_batch", _partial_generate)

    report = audit_rename_plan_with_ollama(
        plan_path=plan_path,
        cfg=OllamaAuditConfig(endpoints=["http://e1"]),
    )
    statuses = sorted(item.audit_status for item in report.items)
    assert statuses == ["ok", "schema_error"]


# ---- New tests for audit report improvements ----


def test_confidence_normalisation_100_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model returning confidence 0-100 should be normalised to 0-1."""
    batch = [_make_plan_item(1)]
    payload = {
        "response": json.dumps(
            {
                "items": [
                    {
                        "plan_item_id": batch[0]["plan_item_id"],
                        "risk_level": "low",
                        "policy_concerns": [],
                        "human_review_reason": "looks fine",
                        "suggested_checks": [],
                        "confidence": 95,  # 0-100 scale
                    },
                ]
            }
        )
    }
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit.httpx.Client",
        lambda *args, **kwargs: _DummyClient(200, payload),
    )
    ok, status, _raw, parsed, _duration, _error = _generate_batch(
        endpoint="http://ollama",
        batch=batch,
        cfg=OllamaAuditConfig(),
        batch_index=1,
    )
    assert ok is True
    assert status == "ok"
    assert parsed is not None
    finding = parsed["findings"][batch[0]["plan_item_id"]]
    assert finding["confidence"] == pytest.approx(0.95)


def test_confidence_normalisation_already_decimal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confidence already in 0-1 range should be unchanged."""
    batch = [_make_plan_item(1)]
    payload = {
        "response": json.dumps(
            {
                "items": [
                    {
                        "plan_item_id": batch[0]["plan_item_id"],
                        "risk_level": "low",
                        "policy_concerns": [],
                        "human_review_reason": "ok",
                        "suggested_checks": [],
                        "confidence": 0.85,
                    },
                ]
            }
        )
    }
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit.httpx.Client",
        lambda *args, **kwargs: _DummyClient(200, payload),
    )
    ok, _status, _raw, parsed, _duration, _error = _generate_batch(
        endpoint="http://ollama",
        batch=batch,
        cfg=OllamaAuditConfig(),
        batch_index=1,
    )
    assert ok is True
    finding = parsed["findings"][batch[0]["plan_item_id"]]
    assert finding["confidence"] == pytest.approx(0.85)


def test_failed_batch_items_have_duration_and_error_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed items should carry actual duration_ms and batch error_ref."""
    plan_path = _write_plan(tmp_path, [_make_plan_item(1), _make_plan_item(2)])

    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._probe_endpoint",
        lambda endpoint, model, timeout: OllamaEndpointState(
            endpoint=endpoint,
            reachable=True,
            ollama_version="0.5.7",
            model_available=True,
            disabled_reason=None,
        ),
    )
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._warm_endpoint",
        lambda endpoint, cfg: (True, "ok", 5, None),
    )

    def _fail_generate(endpoint, batch, cfg, batch_index):
        return False, "schema_error", {"prompt": "p"}, None, 42, "validation error in _Batch..."

    monkeypatch.setattr("shelfr.abs.rename_ollama_audit._generate_batch", _fail_generate)

    report = audit_rename_plan_with_ollama(
        plan_path=plan_path,
        cfg=OllamaAuditConfig(endpoints=["http://e1"], retry_count=0),
    )
    # Both items should have the real duration, not 0
    for item in report.items:
        assert item.duration_ms == 42
        assert item.error_ref == "batch:1"
        assert item.error is not None
        # Error should be a summary, not the full verbose string
        assert len(item.error or "") < 200


def test_items_selected_and_items_audited_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report should have items_selected, items_audited_ok, items_with_errors."""
    items = [_make_plan_item(1), _make_plan_item(2)]
    plan_path = _write_plan(tmp_path, items)

    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._probe_endpoint",
        lambda endpoint, model, timeout: OllamaEndpointState(
            endpoint=endpoint,
            reachable=True,
            ollama_version="0.5.7",
            model_available=True,
            disabled_reason=None,
        ),
    )
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._warm_endpoint",
        lambda endpoint, cfg: (True, "ok", 6, None),
    )

    def _ok_generate(endpoint, batch, cfg, batch_index):
        findings = {
            row["plan_item_id"]: {
                "risk_level": "low",
                "policy_concerns": [],
                "human_review_reason": "ok",
                "suggested_checks": [],
                "confidence": 0.9,
            }
            for row in batch
        }
        return True, "ok", {"prompt": "p"}, {"findings": findings, "missing_ids": []}, 11, None

    monkeypatch.setattr("shelfr.abs.rename_ollama_audit._generate_batch", _ok_generate)

    report = audit_rename_plan_with_ollama(
        plan_path=plan_path,
        cfg=OllamaAuditConfig(endpoints=["http://e1"]),
    )
    assert report.items_selected == 2
    assert report.items_audited_ok == 2
    assert report.items_with_errors == 0

    # Verify as_dict output
    d = report.as_dict()
    assert d["summary"]["items_selected"] == 2
    assert d["summary"]["items_audited_ok"] == 2
    assert d["summary"]["items_with_errors"] == 0


def test_endpoint_failures_by_reason_counts_batches_not_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With retry_count=1, one batch failure should count as 1, not 2."""
    plan_path = _write_plan(tmp_path, [_make_plan_item(1)])

    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._probe_endpoint",
        lambda endpoint, model, timeout: OllamaEndpointState(
            endpoint=endpoint,
            reachable=True,
            ollama_version="0.5.7",
            model_available=True,
            disabled_reason=None,
        ),
    )
    monkeypatch.setattr(
        "shelfr.abs.rename_ollama_audit._warm_endpoint",
        lambda endpoint, cfg: (True, "ok", 3, None),
    )

    def _always_fail(endpoint, batch, cfg, batch_index):
        return False, "schema_error", {"prompt": "p"}, None, 10, "bad schema"

    monkeypatch.setattr("shelfr.abs.rename_ollama_audit._generate_batch", _always_fail)

    report = audit_rename_plan_with_ollama(
        plan_path=plan_path,
        cfg=OllamaAuditConfig(endpoints=["http://e1"], retry_count=1),
    )
    # 1 batch failed, not 2 (initial + retry)
    assert report.endpoint_failures_by_reason.get("schema_error") == 1
    # But per_endpoint_attempts should count both attempts
    assert report.per_endpoint_attempts["http://e1"] == 2
