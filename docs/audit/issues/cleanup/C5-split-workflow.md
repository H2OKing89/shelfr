# C5: Split workflow.py

**Priority**: Low
**Effort**: Medium
**Risk**: Low

---

## Problem

`src/shelfr/workflow.py` is 1223 lines handling:

- Progress reporting classes
- Pipeline stages
- Stage execution logic
- Result aggregation

## Target Structure

```
src/shelfr/workflow/
├── __init__.py      # Re-exports
├── pipeline.py      # run_pipeline(), PipelineConfig
├── stages.py        # Individual stage functions
├── progress.py      # ProgressStage, ProgressInfo, callbacks
└── results.py       # ProcessingResult, PipelineResult
```

## Implementation

Similar approach to O2 (Split config.py).

## Acceptance Criteria

- [ ] Workflow split into logical modules
- [ ] All existing imports still work
- [ ] No module exceeds 400 lines
