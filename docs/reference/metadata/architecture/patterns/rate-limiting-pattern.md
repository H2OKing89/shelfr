# Rate Limiting Pattern

> Code reference for dual rate limiters and batch concurrency control

---

## The Problem

Audnex has rate limits (~90 requests/minute). If we create a new rate limiter per-fetch, each one thinks it's allowed 90/min → aggregate exceeds limits.

## Solution: Shared Client with Dual Limiters

```python
from aiolimiter import AsyncLimiter

class AudnexAsyncClient:
    """Async client with proper lifecycle and shared rate limiters."""

    def __init__(self):
        # Dual limiters: sustained + burst protection
        self._rate_limiter = AsyncLimiter(90, 60.0)   # 90 req/min sustained
        self._burst_limiter = AsyncLimiter(10, 5.0)   # 10 req/5s burst cap
        self._http_client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._http_client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *args) -> None:
        if self._http_client:
            await self._http_client.aclose()
```

---

## Why Dual Limiters?

| Limiter | Rate | Purpose |
| --------- | ------ | --------- |
| Sustained | 90/min | Stay under API quota |
| Burst | 10/5s | Prevent hammering on race start |

Without burst limiting, a 10-region race fires 10 requests instantly → may trigger rate limiting even if under 90/min average.

---

## Using the Limiters

```python
async def _probe_region(self, asin: str, region: str) -> tuple[str, dict | None, Exception | None]:
    """Probe a single region with rate limiting."""
    # Acquire BOTH limiters before making request
    async with self._rate_limiter, self._burst_limiter:
        try:
            url = f"https://api.audnex.us/books/{asin}?region={region}"
            response = await self._http_client.get(url)
            response.raise_for_status()
            return region, response.json(), None
        except Exception as e:
            return region, None, e
```

---

## Batch Concurrency with Semaphore

For batch operations, limit concurrent ASIN lookups:

```python
class AudnexAsyncClient:
    def __init__(self, max_concurrent_asins: int = 5):
        self._asin_semaphore = asyncio.Semaphore(max_concurrent_asins)

    async def fetch_batch(
        self, asins: list[str]
    ) -> list[tuple[str, dict | None, str | None]]:
        """Fetch multiple ASINs with controlled concurrency."""

        async def fetch_one(asin: str) -> tuple[str, dict | None, str | None]:
            async with self._asin_semaphore:
                data, region = await self.fetch_book_parallel(asin)
                return asin, data, region

        tasks = [fetch_one(asin) for asin in asins]
        return await asyncio.gather(*tasks)
```

**Why semaphore?** Each ASIN lookup may make 1-10 requests (staged race). Without limiting, 100 ASINs × 10 requests = 1000 concurrent requests → overwhelms everything.

---

## Lifecycle Pattern

⚠️ **Critical:** Create ONE client per process/run, not per-fetch.

```python
# ❌ WRONG: Fresh client per call (each has fresh limiter)
async def fetch_many_wrong(asins: list[str]):
    for asin in asins:
        async with AudnexAsyncClient() as client:  # New limiter each time!
            await client.fetch_book_parallel(asin)

# ✅ CORRECT: Single shared client
async def fetch_many_correct(asins: list[str]):
    async with AudnexAsyncClient() as client:
        for asin in asins:
            await client.fetch_book_parallel(asin)
```

---

## Provider Integration

The provider manages client lifecycle:

```python
class AudnexProvider:
    def __init__(self):
        self._client: AudnexAsyncClient | None = None
        self._stack: AsyncExitStack | None = None

    async def startup(self) -> None:
        """Initialize shared client. Call once at process start."""
        self._stack = AsyncExitStack()
        self._client = await self._stack.enter_async_context(AudnexAsyncClient())

    async def shutdown(self) -> None:
        """Close shared client. Call at process end."""
        if self._stack:
            await self._stack.aclose()
        self._client = None

    async def fetch(self, ctx: LookupContext, id_type: str) -> ProviderResult:
        """Fetch using shared client."""
        if not self._client:
            raise RuntimeError("Provider not started")
        data, region = await self._client.fetch_book_parallel(ctx.asin)
        # ... build ProviderResult
```

---

## Configuration

```python
# Tunables (could be config-driven)
RATE_LIMIT_SUSTAINED = 90       # requests per minute
RATE_LIMIT_BURST = 10           # requests per 5 seconds
MAX_CONCURRENT_ASINS = 5        # parallel ASIN lookups
```

---

## Key Gotchas

1. **Shared client** — ONE client per run, not per-fetch
2. **Dual limiters** — Sustained + burst for smooth traffic
3. **Semaphore for batches** — Limit concurrent ASINs, not just requests
4. **Context manager** — Ensures cleanup on exit
5. **AsyncExitStack** — Provider manages client lifecycle cleanly
