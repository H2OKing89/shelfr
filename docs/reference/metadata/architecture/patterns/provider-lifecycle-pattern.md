# Provider Lifecycle Pattern

> Code reference for async provider startup/shutdown

---

## The Problem

Network providers need shared resources (HTTP clients, rate limiters, caches). Creating these per-request is wasteful and can cause rate limit violations.

## Solution: Explicit Lifecycle

```python
from contextlib import AsyncExitStack

class AudnexProvider:
    """Provider with explicit lifecycle management."""

    name: str = "audnex"
    priority: int = 70
    kind: Literal["network"] = "network"

    def __init__(self):
        self._client: AudnexAsyncClient | None = None
        self._stack: AsyncExitStack | None = None
        self._started = False

    async def startup(self) -> None:
        """Initialize resources. Call once at process start."""
        if self._started:
            raise RuntimeError("Already started")

        self._stack = AsyncExitStack()
        self._client = await self._stack.enter_async_context(
            AudnexAsyncClient()
        )
        self._started = True

    async def shutdown(self) -> None:
        """Release resources. Safe to call multiple times."""
        if self._stack:
            await self._stack.aclose()
            self._stack = None
        self._client = None
        self._started = False

    async def fetch(self, ctx: LookupContext, id_type: str) -> ProviderResult:
        """Fetch metadata. Must call startup() first."""
        if not self._started:
            raise RuntimeError("Provider not started - call startup() first")

        # Use shared client
        data, region = await self._client.fetch_book_parallel(ctx.asin)
        # ... build result
```

---

## Why AsyncExitStack?

Cleanly manages multiple async context managers:

```python
async def startup(self) -> None:
    self._stack = AsyncExitStack()

    # Each enter_async_context() is cleaned up on aclose()
    self._client = await self._stack.enter_async_context(AudnexAsyncClient())
    self._cache = await self._stack.enter_async_context(SomeCache())
    self._other = await self._stack.enter_async_context(SomeOther())

async def shutdown(self) -> None:
    # One call cleans up everything in reverse order
    await self._stack.aclose()
```

---

## Orchestration Usage

```python
async def process_batch(asins: list[str]) -> list[dict]:
    provider = AudnexProvider()
    await provider.startup()

    try:
        results = []
        for asin in asins:
            ctx = LookupContext.from_asin(asin=asin)
            result = await provider.fetch(ctx, "asin")
            results.append(result)
        return results
    finally:
        await provider.shutdown()
```

Or with context manager pattern:

```python
class AudnexProvider:
    async def __aenter__(self) -> Self:
        await self.startup()
        return self

    async def __aexit__(self, *args) -> None:
        await self.shutdown()

# Usage
async with AudnexProvider() as provider:
    result = await provider.fetch(ctx, "asin")
```

---

## Sync Wrapper (for sync code paths)

```python
def _fetch_audnex_with_provider(asin: str) -> tuple[dict | None, str | None]:
    """Sync wrapper for async provider."""
    provider = AudnexProvider()

    async def run():
        await provider.startup()
        try:
            ctx = LookupContext.from_asin(asin=asin)
            result = await provider.fetch(ctx, "asin")
            return result.raw_data, result.fields.get("source_region")
        finally:
            await provider.shutdown()

    return asyncio.run(run())
```

---

## Key Gotchas

1. **Always call shutdown()** — Use try/finally or context manager
2. **Check started state** — Fail fast if fetch() called before startup()
3. **Idempotent shutdown** — Safe to call multiple times
4. **AsyncExitStack** — Cleanly manages multiple resources
5. **One provider per run** — Don't create/destroy per-request
