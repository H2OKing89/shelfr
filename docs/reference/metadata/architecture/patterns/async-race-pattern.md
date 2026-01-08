# Async Race Pattern

> Code reference for parallel region racing with `asyncio.as_completed()`

---

## The Problem

Sequential region lookup is slow:

```
us → (1.5s) → uk → (1.5s) → au → (1.5s) → found! = ~4.5s
```

## The Solution: Staged Race

```python
# Stage 1: common regions (covers ~95% of ASINs)
STAGE_1_REGIONS = ["us", "uk", "de"]
STAGE_1_TIMEOUT = 1.5  # seconds

# Stage 2: ALL regions (not just remaining!)
ALL_REGIONS = ["us", "uk", "de", "au", "ca", "es", "fr", "in", "it", "jp"]
STAGE_2_TIMEOUT = 8.5  # seconds
```

**Why Stage 2 re-races all regions:** If Stage 1 timed out (not 404), the correct region might have been us/uk/de but slow. Only skip regions that *definitively* returned 404.

---

## Race Implementation

⚠️ **Critical:** `as_completed()` yields new coroutine wrappers, NOT the original tasks.

```python
async def _race_regions(
    asin: str,
    regions: list[str],
    timeout: float = 10.0,
) -> tuple[tuple[dict | None, str | None], set[str], int]:
    """First valid response wins; cancel losers.

    Returns:
        - (data, region) tuple or (None, None)
        - Set of regions that definitively returned 404
        - Request count
    """
    definitive_404s: set[str] = set()
    requests_completed = 0

    async def _probe(region: str) -> tuple[str, dict | None, Exception | None]:
        """Probe a single region, returning (region, data, error)."""
        try:
            data = await client.fetch_region(asin, region)
            return region, data, None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return region, None, e  # Definitive miss
            return region, None, e  # Transient error
        except Exception as e:
            return region, None, e

    tasks = [asyncio.create_task(_probe(r), name=f"audnex-{r}") for r in regions]

    winner = (None, None)
    try:
        for fut in asyncio.as_completed(tasks, timeout=timeout):
            region, data, err = await fut
            requests_completed += 1

            if err:
                # Track definitive 404s (not timeouts/5xx)
                if isinstance(err, httpx.HTTPStatusError) and err.response.status_code == 404:
                    definitive_404s.add(region)
                continue

            if data and _is_valid_for_race(data, asin):
                winner = (data, region)
                break  # First valid wins!

    except TimeoutError:
        pass  # Timeout is expected for Stage 1
    finally:
        # Cancel remaining tasks
        for task in tasks:
            if not task.done():
                task.cancel()
        # Drain to avoid "Task destroyed" warnings
        await asyncio.gather(*tasks, return_exceptions=True)

    return winner, definitive_404s, requests_completed
```

---

## Staged Race Implementation

```python
async def _staged_race(
    asin: str,
    cached_region: str | None = None,
) -> tuple[dict | None, str | None, int, int, float]:
    """Two-stage race with timing.

    Returns: (data, region, stage, total_requests, elapsed_seconds)
    - stage: 0=cache hit, 1=stage1, 2=stage2
    """
    import time
    start_time = time.perf_counter()
    total_requests = 0

    # Fast path: try cached region first
    if cached_region:
        region, data, err = await self._probe_region(asin, cached_region)
        total_requests += 1
        if data and _is_valid_for_race(data, asin):
            elapsed = time.perf_counter() - start_time
            return data, region, 0, total_requests, elapsed

    # Stage 1: Race common regions
    winner, stage1_404s, stage1_requests = await self._race_regions(
        asin, STAGE_1_REGIONS, STAGE_1_TIMEOUT
    )
    total_requests += stage1_requests

    if winner[0] is not None:
        elapsed = time.perf_counter() - start_time
        return winner[0], winner[1], 1, total_requests, elapsed

    # Stage 2: Race ALL regions (skip definitive 404s only)
    stage2_regions = [r for r in ALL_REGIONS if r not in stage1_404s]
    winner, _, stage2_requests = await self._race_regions(
        asin, stage2_regions, STAGE_2_TIMEOUT
    )
    total_requests += stage2_requests
    elapsed = time.perf_counter() - start_time

    if winner[0] is not None:
        return winner[0], winner[1], 2, total_requests, elapsed

    return None, None, 2, total_requests, elapsed
```

---

## Two-Level Validation

### Level 1: Race Acceptance (Fast)

Minimal validation to pick a winner quickly:

```python
def _is_valid_for_race(data: dict, expected_asin: str) -> bool:
    """Minimal validation for race winner selection.

    Level 1 accepts anything with ASIN + title + authors.
    """
    if not data:
        return False
    # ASIN must match (case-insensitive)
    if data.get("asin", "").upper() != expected_asin.upper():
        return False
    # Must have title
    if not data.get("title"):
        return False
    # Must have at least one author
    if not data.get("authors") or len(data["authors"]) == 0:
        return False
    return True
```

### Level 2: Quality Checks (After Winner)

Log warnings for missing optional fields, but don't reject:

```python
def _validate_and_log_quality(data: dict, asin: str) -> None:
    """Log warnings for missing optional fields."""
    if not data.get("authors"):
        logger.warning("Audnex response for %s missing authors", asin)
    if not data.get("narrators"):
        logger.warning("Audnex response for %s missing narrators", asin)
```

---

## Key Gotchas

1. **Don't use `tasks[coro]` lookup** — `as_completed()` yields wrappers, not original tasks
2. **Always drain cancelled tasks** — Prevents "Task was destroyed" warnings
3. **Stage 2 re-races all regions** — Timeout ≠ 404, don't skip potentially slow regions
4. **Include region in probe result** — Can't map wrapper back to original task
