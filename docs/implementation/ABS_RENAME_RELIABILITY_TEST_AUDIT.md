# ABS Rename Reliability Test And Audit Guide

## Purpose

This document is the review and audit checklist for the reliability-first ABS rename changes:

- importer rollback + per-run ASIN uniqueness hardening
- canonical rename policy + hierarchy enforcement
- deterministic `plan -> approve -> apply` workflow
- optional post-plan distributed Ollama advisory audit
- canary execution and transactional rollback behavior

Audit baseline date: `2026-02-15`.

## Scope Under Audit

Code paths included in this audit:

- `src/shelfr/abs/importer.py`
- `src/shelfr/abs/rename.py`
- `src/shelfr/commands/abs/rename.py`
- `src/shelfr/cli_argparse.py`
- `src/shelfr/abs/rename_ollama_audit.py`
- `src/shelfr/config.py`
- `src/shelfr/schemas/config.py`
- `tests/test_abs_importer.py`
- `tests/test_abs_rename.py`
- `tests/test_abs_rename_ollama_audit.py`
- `tests/test_cli_abs.py`

## Locked Policy Decisions (Verification Targets)

These rules are mandatory and should be treated as pass/fail:

1. Two-step execution: `plan -> approve -> apply`.
2. Canary-first rollout: 50 items, stratified.
3. Per-book transactional rollback on apply failure.
4. Hierarchy:
   - series: `Author/Series/Book`
   - standalone: `Author/Book`
5. Arc policy: optional, omit when unreliable/empty.
6. ASIN policy: preserve exactly as trusted value.
7. Tag policy:
   - preserve `[H2OKing]` when already present
   - drop non-`H2OKing` trailing bracket tags
8. Reports written to `data/reports`.

## Automated Verification

Run these from repo root.

### 1) Importer blocker gates

```bash
pytest -q \
  tests/test_abs_importer.py::TestImportSingle::test_overwrite_rollback_on_move_failure \
  tests/test_abs_importer.py::TestImportBatch::test_batch_enforces_per_run_asin_uniqueness \
  tests/test_abs_importer.py::TestImportBatch::test_batch_enforces_per_run_asin_uniqueness_in_dry_run
```

Expected: all pass.

### 2) Rename policy + transaction + CLI/config coverage

```bash
pytest -q \
  tests/test_abs_importer.py \
  tests/test_abs_rename.py \
  tests/test_abs_rename_ollama_audit.py \
  tests/test_cli_abs.py \
  tests/test_config.py \
  tests/test_config_schema.py
```

Expected: all pass.

### 3) Lint touched audit paths

```bash
ruff check \
  src/shelfr/abs/rename.py \
  src/shelfr/abs/rename_ollama_audit.py \
  src/shelfr/commands/abs/rename.py \
  tests/test_abs_rename.py \
  tests/test_abs_rename_ollama_audit.py \
  tests/test_cli_abs.py
```

Expected: `All checks passed!`

## Key Tests Mapped To Risk

### Importer reliability

- `TestImportSingle::test_overwrite_rollback_on_move_failure`
- `TestImportBatch::test_batch_enforces_per_run_asin_uniqueness`
- `TestImportBatch::test_batch_enforces_per_run_asin_uniqueness_in_dry_run`

### Locked naming policy

- `TestPolicyLockedRules::test_arc_omitted_when_missing`
- `TestPolicyLockedRules::test_preserves_h2oking_tag`
- `TestPolicyLockedRules::test_drops_non_allowlisted_trailing_tag`
- `TestPolicyLockedRules::test_preserves_numeric_asin_verbatim`

### Hierarchy + candidate discovery

- `TestHierarchyAndDiscovery::test_series_target_uses_author_series_book`
- `TestHierarchyAndDiscovery::test_standalone_target_uses_author_book`
- `TestHierarchyAndDiscovery::test_discovery_collapses_deep_episode_subfolders`

### Apply transactions and preflight safety

- `TestPlanApplyTransactions::test_apply_refuses_stale_manifest_on_fingerprint_drift`
- `TestPlanApplyTransactions::test_conflict_preflight_leaves_filesystem_unchanged`
- `TestPlanApplyTransactions::test_move_failure_rolls_back_source`

### Conformance

- `TestConformance::test_sao_like_target_conforms`

### CLI contract

- `TestAbsRenameParser::test_abs_rename_plan_apply_canary_flags`
- `TestAbsRenameParser::test_abs_rename_defaults`
- `TestAbsRenameParser::test_abs_rename_ollama_flags_parse`
- `TestAbsRenameOllamaResolution::test_cli_overrides_config_for_ollama_settings`
- `TestAbsRenameOllamaResolution::test_config_used_when_cli_omits_ollama_settings`
- `TestAbsRenameOllamaResolution::test_defaults_used_when_cli_and_config_missing`

### Ollama advisory reliability

- `test_plan_item_id_is_deterministic_when_missing`
- `test_risk_score_sort_order_is_deterministic`
- `test_generate_batch_rejects_duplicate_or_unknown_ids`
- `test_sticky_primary_endpoint_routing`
- `test_midrun_failover_sticks_to_secondary`
- `test_model_missing_endpoint_is_skipped_and_counted`
- `test_all_model_missing_is_unavailable_non_blocking`

## Operator Audit Workflow

### Phase A: Generate plan artifact

```bash
Shelfr abs-rename \
  --source /mnt/user/data/audio/audiobooks \
  --policy-profile sao_gold \
  --plan-out data/reports/rename_plan_$(date +%Y%m%d_%H%M%S).json
```

Expected artifacts:

- `data/reports/rename_plan_<timestamp>.json`
- `data/reports/rename_plan_<timestamp>.html`

### Phase B: Optional Ollama advisory review (non-blocking)

Run this on plan generation by enabling advisory mode:

```bash
Shelfr abs-rename \
  --source /mnt/user/data/audio/audiobooks \
  --policy-profile sao_gold \
  --plan-out data/reports/rename_plan_$(date +%Y%m%d_%H%M%S).json \
  --ollama-audit \
  --ollama-model llama3.1:8b-instruct-q4_K_M \
  --ollama-endpoint http://<remote-3080ti>:11434 \
  --ollama-endpoint http://127.0.0.1:11434 \
  --ollama-endpoint http://<remote-3070ti>:11434
```

Expected advisory artifact:

- explicit `--ollama-report-out` path, if provided
- otherwise `data/reports/rename_plan_<timestamp>.llm_audit.json`

Semantics:

1. Advisory-only: report never mutates plan JSON or apply behavior.
2. Non-blocking: endpoint/model/schema failures warn and do not fail planning.
3. Deterministic input set: `status == "needs_rename"` with risk-score ordering.
4. Sticky routing with ordered failover.

### Phase C: Audit plan before approval

Use the generated JSON report and verify:

1. No runtime errors in command output.
2. `summary.total_candidates` is non-zero and plausible.
3. `items[].status` classification is sensible (`needs_rename`, `up_to_date`, conflicts).
4. `items[].conformance.violations` is empty for canonical targets that should pass.
5. No item preserves non-allowlisted tags.
6. ASIN token is preserved exactly in target naming.
7. Hierarchy target path is correct for series vs standalone.

Suggested quick checks:

```bash
jq '.summary' data/reports/rename_plan_<timestamp>.json
jq '[.items[] | select(.status=="needs_rename")] | length' data/reports/rename_plan_<timestamp>.json
jq '[.items[] | select((.components.ripper_tag // "") != "" and .components.ripper_tag != "H2OKing")] | length' data/reports/rename_plan_<timestamp>.json
jq '[.items[] | select((.conformance.violations // []) | length > 0)] | length' data/reports/rename_plan_<timestamp>.json
```

Optional Ollama advisory quick checks:

```bash
jq '.summary' data/reports/rename_plan_<timestamp>.llm_audit.json
jq '.summary.endpoint_failures_by_reason' data/reports/rename_plan_<timestamp>.llm_audit.json
jq '[.items[] | select(.audit_status != "ok")] | group_by(.audit_status) | map({status: .[0].audit_status, count: length})' data/reports/rename_plan_<timestamp>.llm_audit.json
jq '.summary.endpoints_disabled_due_to_model_missing' data/reports/rename_plan_<timestamp>.llm_audit.json
```

### Phase D: Canary apply (50, stratified)

```bash
Shelfr abs-rename \
  --apply-from data/reports/rename_plan_<approved>.json \
  --canary-size 50 \
  --canary-strategy stratified \
  --report data/reports/rename_apply_$(date +%Y%m%d_%H%M%S).json
```

Expected artifacts:

- `data/reports/rename_apply_<timestamp>.json`
- `data/reports/rename_apply_<timestamp>.html`

Canary acceptance checks:

1. `summary.failed == 0`
2. `warnings.preflight_failed != true`
3. No `rollback_ok == false`
4. 100% sampled canary names conform to locked policy

Suggested check:

```bash
jq '.summary, .warnings' data/reports/rename_apply_<timestamp>.json
jq '[.results[] | select(.status=="failed")] | length' data/reports/rename_apply_<timestamp>.json
jq '[.results[] | select((.rollback_ok // true) == false)] | length' data/reports/rename_apply_<timestamp>.json
```

### Phase E: Full apply

Run apply again without `--canary-size`.

```bash
Shelfr abs-rename \
  --apply-from data/reports/rename_plan_<approved>.json \
  --report data/reports/rename_apply_full_$(date +%Y%m%d_%H%M%S).json
```

Expected:

1. zero data-loss incidents
2. no unrecovered transaction failures
3. zero tag/ASIN policy violations in post-run review

## Gold-Standard Spot Check

Use this path as the schema benchmark sample:

- `/mnt/user/data/audio/audiobooks/Reki Kawahara/Sword Art Online`

Manual review checklist:

1. Folder hierarchy follows `Author/Series/Book`.
2. Arc token appears only when reliable.
3. ASIN placement is `{ASIN.<value>}` and value is preserved.
4. `[H2OKing]` is preserved only when pre-existing.
5. Non-`H2OKing` trailing tags are absent.

## Evidence Capture Template

Record the following for sign-off:

1. Plan command used.
2. Plan report path.
3. Plan review summary counts.
4. Canary command used.
5. Canary report path and failure count.
6. Full apply report path and failure count.
7. Manual spot-check sample paths reviewed.
8. Final decision: `APPROVED` or `HOLD`.

## Sign-Off Gate

Release is approved only when all are true:

1. Automated tests pass.
2. Importer blocker tests pass.
3. Plan report is clean enough for manual approval.
4. Canary apply has zero unrecovered failures.
5. Full apply has zero tag/ASIN policy violations.
