#!/usr/bin/env python3
"""Audible Catalog Data Gathering Tool.

Fetches audiobook metadata from Audible's catalog API for building test datasets.
Uses the `audible` Python package for authenticated API access.

Authentication Setup:
    1. Run with --login to create credentials file
    2. Follow prompts for Amazon login (2FA supported)
    3. Credentials stored encrypted in data/audible_auth.json

Usage:
    # First time: Login and register device
    python scripts/data_gathering/audible_catalog.py --login

    # Test API with a sample search
    python scripts/data_gathering/audible_catalog.py --test

    # Search catalog by keywords
    python scripts/data_gathering/audible_catalog.py search --keywords "progression fantasy"

    # Fetch by category
    python scripts/data_gathering/audible_catalog.py category --id 18580628011 --pages 5

    # Batch fetch by genre strategies
    python scripts/data_gathering/audible_catalog.py gather --strategy litrpg --max-items 500
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Add src to path for shelfr imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

try:
    import audible
    from audible import AsyncClient
except ImportError:
    print("ERROR: audible package not installed.")
    print("Install with: pip install git+https://github.com/mkb79/Audible.git")
    sys.exit(1)

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
AUTH_FILE = DATA_DIR / "audible_auth.json"
CATALOG_OUTPUT = DATA_DIR / "audible_catalog_samples.jsonl"
CATALOG_ENRICHED_OUTPUT = DATA_DIR / "audible_catalog_enriched.jsonl"

# Load environment variables
load_dotenv(CONFIG_DIR / ".env")

# Get encryption password from environment
AUDIBLE_PASSWORD = os.getenv("AUDIBLE_PASSWORD")
if not AUDIBLE_PASSWORD:
    logger.warning("AUDIBLE_PASSWORD not set in config/.env - using default password")
    AUDIBLE_PASSWORD = "shelfr-audible-2026"  # Default if not in .env

# Schema version for tracking format changes
SCHEMA_VERSION = "1.0.0"


# =============================================================================
# Pydantic Schemas for Audible Catalog Response
# =============================================================================


class Author(BaseModel):
    """Author information."""

    asin: str | None = None
    name: str


class Narrator(BaseModel):
    """Narrator information."""

    name: str


class SeriesInfo(BaseModel):
    """Series relationship."""

    asin: str | None = None
    title: str
    sequence: str | None = None
    url: str | None = None


class CategoryLadder(BaseModel):
    """Category hierarchy."""

    id: str
    name: str


class CategoryInfo(BaseModel):
    """Full category with ladder."""

    root: str | None = None
    ladder: list[CategoryLadder] = Field(default_factory=list)


class Rating(BaseModel):
    """Rating information."""

    num_reviews: int = 0
    overall_distribution: dict[str, Any] | None = None
    performance_distribution: dict[str, Any] | None = None
    story_distribution: dict[str, Any] | None = None


class AudibleProduct(BaseModel):
    """Audible catalog product - normalized schema.

    This represents the key fields we care about for audiobook naming/metadata.
    """

    # Core identifiers
    asin: str
    sku: str | None = None
    title: str
    subtitle: str | None = None

    # Attribution
    authors: list[Author] = Field(default_factory=list)
    narrators: list[Narrator] = Field(default_factory=list)
    publisher_name: str | None = None

    # Series
    series: list[SeriesInfo] = Field(default_factory=list)
    publication_name: str | None = None  # Often series name

    # Content info
    runtime_length_min: int | None = None
    language: str | None = None
    format_type: str | None = None  # unabridged, abridged
    release_date: str | None = None
    copyright: str | None = None

    # Categories/Genre
    category_ladders: list[CategoryInfo] = Field(default_factory=list)
    thesaurus_subject_keywords: list[str] = Field(default_factory=list)
    platinum_keywords: list[str] = Field(default_factory=list)

    # Descriptions
    publisher_summary: str | None = None
    merchandising_summary: str | None = None
    short_description: str | None = None

    # Ratings
    rating: Rating | None = None

    # Metadata about fetch
    fetched_at: str | None = None
    marketplace: str | None = None

    @classmethod
    def from_api_response(cls, data: dict[str, Any], marketplace: str = "us") -> AudibleProduct:
        """Parse raw API response into normalized schema."""
        # Handle nested structures safely
        product_details = data.get("product_details") or {}
        subtitle = (
            data.get("subtitle")
            or product_details.get("subtitle")
            or product_details.get("sub_title")
        )
        authors = [Author(**a) for a in data.get("authors", [])]
        narrators = [Narrator(**n) for n in data.get("narrators", [])]
        series = [SeriesInfo(**s) for s in data.get("series", [])]

        # Category ladders need special handling
        category_ladders = []
        for cat in data.get("category_ladders", []):
            ladder = [CategoryLadder(**c) for c in cat.get("ladder", [])]
            category_ladders.append(CategoryInfo(root=cat.get("root"), ladder=ladder))

        # Rating
        rating_data = data.get("rating")
        rating = Rating(**rating_data) if rating_data else None

        return cls(
            asin=data["asin"],
            sku=data.get("sku"),
            title=data.get("title", ""),
            subtitle=subtitle,
            authors=authors,
            narrators=narrators,
            publisher_name=data.get("publisher_name"),
            series=series,
            publication_name=data.get("publication_name"),
            runtime_length_min=data.get("runtime_length_min"),
            language=data.get("language"),
            format_type=data.get("format_type"),
            release_date=data.get("release_date"),
            copyright=data.get("copyright"),
            category_ladders=category_ladders,
            thesaurus_subject_keywords=data.get("thesaurus_subject_keywords", []),
            platinum_keywords=data.get("platinum_keywords", []),
            publisher_summary=data.get("publisher_summary"),
            merchandising_summary=data.get("merchandising_summary"),
            short_description=data.get("short_description"),
            rating=rating,
            fetched_at=datetime.now(UTC).isoformat(),
            marketplace=marketplace,
        )


# =============================================================================
# Search Strategies for Different Genre Types
# =============================================================================


@dataclass
class SearchStrategy:
    """A search strategy for gathering specific types of audiobooks."""

    name: str
    description: str
    keywords: list[str] = field(default_factory=list)
    category_ids: list[int] = field(default_factory=list)
    max_pages: int = 10


# Known Audible category IDs (US marketplace)
# These can be discovered via /1.0/catalog/categories endpoint
CATEGORY_IDS = {
    # Main genres
    "science_fiction_fantasy": 18580628011,
    "mystery_thriller": 18580606011,
    "romance": 18580612011,
    "literature_fiction": 18580518011,
    "business": 18571910011,
    "self_help": 18573754011,
    "biography_memoir": 18571951011,
    "history": 18572091011,
    "science_technology": 18573609011,
    "young_adult": 18580641011,
    # Subgenres (SF&F)
    "epic_fantasy": 18580631011,
    "urban_fantasy": 18580634011,
    "paranormal_fantasy": 18580632011,
    "space_opera": 18580638011,
    "cyberpunk": 18580636011,
    # LitRPG/Progression (often under SF&F or search)
}

# Search strategies targeting specific audiobook types
SEARCH_STRATEGIES: dict[str, SearchStrategy] = {
    "litrpg": SearchStrategy(
        name="LitRPG & GameLit",
        description="LitRPG, GameLit, cultivation novels",
        keywords=[
            "LitRPG",
            "GameLit",
            "progression fantasy",
            "cultivation novel",
            "xianxia",
            "isekai",
            "dungeon core",
            "tower climbing",
        ],
        max_pages=20,
    ),
    "fantasy": SearchStrategy(
        name="Fantasy",
        description="Epic, urban, and paranormal fantasy",
        keywords=[
            "epic fantasy",
            "urban fantasy",
            "dark fantasy",
            "sword and sorcery",
            "high fantasy",
        ],
        category_ids=[18580628011, 18580631011, 18580634011],
        max_pages=15,
    ),
    "scifi": SearchStrategy(
        name="Science Fiction",
        description="Space opera, cyberpunk, hard SF",
        keywords=[
            "space opera",
            "military science fiction",
            "hard science fiction",
            "cyberpunk",
            "post-apocalyptic",
        ],
        category_ids=[18580636011, 18580638011],
        max_pages=15,
    ),
    "romance": SearchStrategy(
        name="Romance",
        description="Contemporary, paranormal, historical romance",
        keywords=[
            "contemporary romance",
            "paranormal romance",
            "historical romance",
            "romantic comedy",
        ],
        category_ids=[18580612011],
        max_pages=10,
    ),
    "thriller": SearchStrategy(
        name="Thriller & Mystery",
        description="Crime, psychological, legal thrillers",
        keywords=[
            "psychological thriller",
            "crime thriller",
            "legal thriller",
            "cozy mystery",
            "detective",
        ],
        category_ids=[18580606011],
        max_pages=10,
    ),
    "nonfiction": SearchStrategy(
        name="Non-Fiction",
        description="Biography, self-help, business",
        keywords=[
            "biography",
            "memoir",
            "self improvement",
            "business leadership",
            "popular science",
        ],
        category_ids=[18571951011, 18573754011, 18571910011],
        max_pages=10,
    ),
    "light_novel": SearchStrategy(
        name="Light Novels",
        description="Japanese light novels and manga adaptations",
        keywords=[
            "light novel",
            "japanese light novel",
            "isekai light novel",
            "slice of life",
        ],
        max_pages=15,
    ),
    "horror": SearchStrategy(
        name="Horror",
        description="Horror, supernatural, dark fiction",
        keywords=[
            "horror",
            "supernatural horror",
            "cosmic horror",
            "haunted house",
            "psychological horror",
            "monster",
            "vampire",
            "werewolf",
            "zombie",
        ],
        category_ids=[18580645011],  # Horror category
        max_pages=15,
    ),
    "crime": SearchStrategy(
        name="Crime & Detective",
        description="Crime fiction, detective stories, police procedurals",
        keywords=[
            "crime fiction",
            "detective novel",
            "police procedural",
            "true crime",
            "noir",
            "hard boiled",
            "whodunit",
            "serial killer",
        ],
        category_ids=[18580606011],  # Mystery/Thriller category
        max_pages=15,
    ),
}


# =============================================================================
# API Client
# =============================================================================


class AudibleCatalogClient:
    """Client for fetching Audible catalog data."""

    # Response groups for comprehensive metadata
    RESPONSE_GROUPS = ",".join(
        [
            "contributors",
            "product_attrs",
            "product_desc",
            "product_extended_attrs",
            "product_details",
            "rating",
            "series",
            "category_ladders",
            "relationships",
            "media",
        ]
    )

    def __init__(self, auth_file: Path, marketplace: str = "us"):
        self.auth_file = auth_file
        self.marketplace = marketplace
        self._auth: audible.Authenticator | None = None

    def load_auth(self) -> audible.Authenticator:
        """Load encrypted authentication from file."""
        if not self.auth_file.exists():
            raise FileNotFoundError(
                f"Auth file not found: {self.auth_file}\n" "Run with --login to create credentials."
            )

        self._auth = audible.Authenticator.from_file(
            str(self.auth_file),
            password=AUDIBLE_PASSWORD,
        )
        logger.info(f"Loaded auth for marketplace: {self._auth.locale.country_code}")
        return self._auth

    @staticmethod
    def login_interactive(auth_file: Path, locale: str = "us") -> audible.Authenticator:
        """Interactive login to create encrypted auth file."""
        print("\n" + "=" * 60)
        print("Audible Device Registration")
        print("=" * 60)
        print(f"Marketplace: {locale.upper()}")
        print("\nThis will register a virtual Audible device.")
        print("You'll need your Amazon credentials and may need 2FA.\n")

        username = input("Amazon Email: ")
        password = input("Amazon Password: ")

        try:
            auth = audible.Authenticator.from_login(
                username,
                password,
                locale=locale,
                with_username=False,
            )

            # Save encrypted with password from .env
            auth_file.parent.mkdir(parents=True, exist_ok=True)
            auth.to_file(
                str(auth_file),
                password=AUDIBLE_PASSWORD,
                encryption="json",
            )
            print(f"\n✓ Auth saved to: {auth_file}")
            print("  (encrypted with password from AUDIBLE_PASSWORD in .env)")

            return auth

        except Exception as e:
            logger.error(f"Login failed: {e}")
            raise

    async def search_catalog(
        self,
        keywords: str | None = None,
        category_id: int | None = None,
        num_results: int = 50,
        page: int = 1,
        sort_by: str = "-ReleaseDate",
    ) -> list[dict[str, Any]]:
        """Search the Audible catalog.

        Args:
            keywords: Search keywords
            category_id: Category filter
            num_results: Results per page (max 50)
            page: Page number
            sort_by: Sort order

        Returns:
            List of product dictionaries
        """
        if not self._auth:
            self.load_auth()

        params: dict[str, Any] = {
            "num_results": min(num_results, 50),
            "page": page,
            "products_sort_by": sort_by,
            "response_groups": self.RESPONSE_GROUPS,
        }

        if keywords:
            params["keywords"] = keywords
        if category_id:
            params["category_id"] = category_id

        async with AsyncClient(auth=self._auth) as client:
            response = await client.get("1.0/catalog/products", **params)

        products = response.get("products", [])
        total = response.get("total_results", 0)
        logger.info(f"Fetched {len(products)} products (page {page}, total: {total})")

        return products

    async def get_product(self, asin: str) -> dict[str, Any] | None:
        """Get detailed product info by ASIN."""
        if not self._auth:
            self.load_auth()

        async with AsyncClient(auth=self._auth) as client:
            try:
                response = await client.get(
                    f"1.0/catalog/products/{asin}",
                    response_groups=self.RESPONSE_GROUPS,
                )
                return response.get("product")
            except Exception as e:
                logger.warning(f"Failed to fetch {asin}: {e}")
                return None

    async def gather_by_strategy(
        self,
        strategy: SearchStrategy,
        max_items: int = 500,
        delay: float = 0.5,
    ) -> list[AudibleProduct]:
        """Gather products using a search strategy."""
        seen_asins: set[str] = set()
        products: list[AudibleProduct] = []

        # Search by keywords
        for keyword in strategy.keywords:
            if len(products) >= max_items:
                break

            logger.info(f"Searching: {keyword!r}")
            for page in range(1, strategy.max_pages + 1):
                if len(products) >= max_items:
                    break

                try:
                    results = await self.search_catalog(keywords=keyword, page=page)

                    if not results:
                        break

                    for item in results:
                        asin = item.get("asin")
                        if asin and asin not in seen_asins:
                            seen_asins.add(asin)
                            products.append(
                                AudibleProduct.from_api_response(item, self.marketplace)
                            )

                    await asyncio.sleep(delay)

                except Exception as e:
                    logger.error(f"Search error: {e}")
                    break

        # Search by category
        for cat_id in strategy.category_ids:
            if len(products) >= max_items:
                break

            logger.info(f"Fetching category: {cat_id}")
            for page in range(1, strategy.max_pages + 1):
                if len(products) >= max_items:
                    break

                try:
                    results = await self.search_catalog(category_id=cat_id, page=page)

                    if not results:
                        break

                    for item in results:
                        asin = item.get("asin")
                        if asin and asin not in seen_asins:
                            seen_asins.add(asin)
                            products.append(
                                AudibleProduct.from_api_response(item, self.marketplace)
                            )

                    await asyncio.sleep(delay)

                except Exception as e:
                    logger.error(f"Category fetch error: {e}")
                    break

        logger.info(f"Strategy '{strategy.name}' gathered {len(products)} unique products")
        return products


# =============================================================================
# Output Helpers
# =============================================================================


def save_products_jsonl(products: list[AudibleProduct], output_path: Path) -> None:
    """Save products to JSONL format (append mode)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "a", encoding="utf-8") as f:
        for product in products:
            f.write(product.model_dump_json() + "\n")

    logger.info(f"Appended {len(products)} products to {output_path}")


def load_asins_from_jsonl(path: Path) -> set[str]:
    """Load ASINs already present in a JSONL output file (for resume)."""
    asins: set[str] = set()
    if not path.exists():
        return asins
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            asin = obj.get("asin")
            if asin:
                asins.add(asin)
    return asins


def iter_products_from_jsonl(path: Path) -> Iterable[AudibleProduct]:
    """Stream AudibleProduct rows from a JSONL file."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            # Old rows won't have subtitle; that's fine (optional field).
            yield AudibleProduct(**obj)


def print_product_summary(products: list[AudibleProduct]) -> None:
    """Print summary of fetched products."""
    print("\n" + "=" * 60)
    print(f"Fetched {len(products)} Products")
    print("=" * 60)

    # Sample titles
    print("\nSample Titles:")
    for p in products[:10]:
        authors = ", ".join(a.name for a in p.authors[:2])
        series = f" [{p.series[0].title}]" if p.series else ""
        print(f"  • {p.title}{series} - {authors}")

    # Stats
    with_series = sum(1 for p in products if p.series)
    print(f"\n  With series: {with_series}/{len(products)}")

    # Unique authors
    authors = {a.name for p in products for a in p.authors}
    print(f"  Unique authors: {len(authors)}")


# =============================================================================
# CLI
# =============================================================================


async def cmd_test(args: argparse.Namespace) -> int:
    """Test API connection with a sample search."""
    client = AudibleCatalogClient(AUTH_FILE, args.marketplace)

    try:
        client.load_auth()
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    logger.info("Testing API with sample search...")
    products = await client.search_catalog(keywords="fantasy", num_results=5)

    if products:
        print("\n✓ API working! Sample results:")
        for p in products[:5]:
            print(f"  • {p.get('title', 'Unknown')} ({p.get('asin', 'N/A')})")
        return 0
    else:
        logger.error("No results returned")
        return 1


async def cmd_search(args: argparse.Namespace) -> int:
    """Search catalog by keywords."""
    client = AudibleCatalogClient(AUTH_FILE, args.marketplace)

    try:
        client.load_auth()
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    products: list[AudibleProduct] = []

    for page in range(1, args.pages + 1):
        raw = await client.search_catalog(
            keywords=args.keywords,
            page=page,
            num_results=50,
        )
        if not raw:
            break

        for item in raw:
            products.append(AudibleProduct.from_api_response(item, args.marketplace))

        await asyncio.sleep(0.5)

    print_product_summary(products)

    if args.output:
        save_products_jsonl(products, Path(args.output))

    return 0


async def cmd_gather(args: argparse.Namespace) -> int:
    """Gather products using a search strategy."""
    if args.strategy not in SEARCH_STRATEGIES:
        logger.error(f"Unknown strategy: {args.strategy}")
        logger.info(f"Available: {', '.join(SEARCH_STRATEGIES.keys())}")
        return 1

    strategy = SEARCH_STRATEGIES[args.strategy]
    logger.info(f"Strategy: {strategy.name} - {strategy.description}")

    client = AudibleCatalogClient(AUTH_FILE, args.marketplace)

    try:
        client.load_auth()
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    products = await client.gather_by_strategy(
        strategy,
        max_items=args.max_items,
        delay=args.delay,
    )

    print_product_summary(products)

    output = Path(args.output) if args.output else CATALOG_OUTPUT
    save_products_jsonl(products, output)

    return 0


async def cmd_enrich(args: argparse.Namespace) -> int:
    """Enrich an existing JSONL dataset with single-ASIN product_details (e.g., subtitle)."""
    client = AudibleCatalogClient(AUTH_FILE, args.marketplace)

    try:
        client.load_auth()
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return 1

    output_path = Path(args.output) if args.output else CATALOG_ENRICHED_OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)

    done_asins = load_asins_from_jsonl(output_path) if args.resume else set()
    logger.info(f"Resume enabled: {args.resume} (already have {len(done_asins)} ASINs)")

    queue: asyncio.Queue[AudibleProduct] = asyncio.Queue()
    passthrough: list[AudibleProduct] = []

    total_in = 0
    queued = 0
    for p in iter_products_from_jsonl(input_path):
        total_in += 1
        if args.resume and p.asin in done_asins:
            continue
        if args.only_missing and p.subtitle:
            passthrough.append(p)
            continue
        queue.put_nowait(p)
        queued += 1

    logger.info(f"Loaded {total_in} rows from input")
    logger.info(f"Queued for enrichment: {queued} | Pass-through: {len(passthrough)}")

    write_lock = asyncio.Lock()
    processed = 0

    # Write pass-through rows first (if any)
    if passthrough:
        async with write_lock:
            with open(output_path, "a", encoding="utf-8") as f:
                for p in passthrough:
                    f.write(p.model_dump_json() + "\n")
        logger.info(f"Wrote {len(passthrough)} pass-through rows to {output_path}")

    async def enrich_worker(worker_id: int) -> None:
        nonlocal processed
        # One HTTP client per worker (faster than opening/closing for every ASIN)
        async with AsyncClient(auth=client._auth) as api:
            while True:
                try:
                    p = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return

                try:
                    # Single-ASIN endpoint
                    resp = await api.get(
                        f"1.0/catalog/products/{p.asin}",
                        response_groups=client.RESPONSE_GROUPS,
                    )
                    prod = resp.get("product") or {}
                    if prod:
                        enriched = AudibleProduct.from_api_response(prod, client.marketplace)
                        # Fill only what we care about / what's missing
                        p.subtitle = enriched.subtitle
                        if not p.series and enriched.series:
                            p.series = enriched.series
                        if not p.publication_name and enriched.publication_name:
                            p.publication_name = enriched.publication_name

                except Exception as e:
                    logger.warning(f"[enrich w{worker_id}] Failed {p.asin}: {e}")

                async with write_lock:
                    with open(output_path, "a", encoding="utf-8") as f:
                        f.write(p.model_dump_json() + "\n")

                processed += 1
                if processed % max(1, args.log_every) == 0:
                    logger.info(f"Enriched {processed}/{queued}...")

                queue.task_done()
                if args.delay > 0:
                    await asyncio.sleep(args.delay)

    workers = max(1, args.workers)
    logger.info(f"Starting enrichment: workers={workers} delay={args.delay}s")
    await asyncio.gather(*(enrich_worker(i) for i in range(1, workers + 1)))

    logger.info(f"Enrichment complete. Output: {output_path}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    """Interactive login to create auth file."""
    try:
        AudibleCatalogClient.login_interactive(AUTH_FILE, args.marketplace)
        return 0
    except Exception:
        return 1


def cmd_list_strategies(args: argparse.Namespace) -> int:
    """List available search strategies."""
    print("\nAvailable Search Strategies:")
    print("=" * 60)
    for key, strategy in SEARCH_STRATEGIES.items():
        print(f"\n  {key}:")
        print(f"    {strategy.description}")
        if strategy.keywords:
            print(f"    Keywords: {', '.join(strategy.keywords[:3])}...")
        if strategy.category_ids:
            print(f"    Categories: {len(strategy.category_ids)} IDs")
    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Audible Catalog Data Gathering Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--marketplace",
        "-m",
        default="us",
        help="Audible marketplace (default: us)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Login
    login_parser = subparsers.add_parser("login", help="Login and create auth file")
    login_parser.set_defaults(func=cmd_login)

    # Test
    test_parser = subparsers.add_parser("test", help="Test API connection")
    test_parser.set_defaults(func=lambda a: asyncio.run(cmd_test(a)))

    # Search
    search_parser = subparsers.add_parser("search", help="Search catalog")
    search_parser.add_argument("--keywords", "-k", required=True, help="Search keywords")
    search_parser.add_argument("--pages", "-p", type=int, default=3, help="Pages to fetch")
    search_parser.add_argument("--output", "-o", help="Output JSONL file")
    search_parser.set_defaults(func=lambda a: asyncio.run(cmd_search(a)))

    # Gather
    gather_parser = subparsers.add_parser("gather", help="Gather by strategy")
    gather_parser.add_argument(
        "--strategy",
        "-s",
        required=True,
        help="Strategy name (use 'list' to see options)",
    )
    gather_parser.add_argument("--max-items", type=int, default=500, help="Max items to gather")
    gather_parser.add_argument("--delay", type=float, default=0.5, help="Delay between requests")
    gather_parser.add_argument("--output", "-o", help="Output JSONL file")
    gather_parser.set_defaults(func=lambda a: asyncio.run(cmd_gather(a)))

    # Enrich
    enrich_parser = subparsers.add_parser(
        "enrich", help="Enrich JSONL via single-ASIN product_details"
    )
    enrich_parser.add_argument("--input", "-i", required=True, help="Input JSONL file to enrich")
    enrich_parser.add_argument(
        "--output",
        "-o",
        help="Output JSONL file (default: data/audible_catalog_enriched.jsonl)",
    )
    enrich_parser.add_argument("--workers", type=int, default=8, help="Concurrent workers")
    enrich_parser.add_argument(
        "--delay", type=float, default=0.25, help="Delay between requests per worker"
    )
    enrich_parser.add_argument(
        "--resume", action="store_true", help="Skip ASINs already in output file"
    )
    enrich_parser.add_argument(
        "--only-missing", action="store_true", help="Only enrich rows missing subtitle"
    )
    enrich_parser.add_argument("--log-every", type=int, default=100, help="Progress log interval")
    enrich_parser.set_defaults(func=lambda a: asyncio.run(cmd_enrich(a)))

    # List strategies
    list_parser = subparsers.add_parser("list", help="List search strategies")
    list_parser.set_defaults(func=cmd_list_strategies)

    # Legacy flags for backwards compat
    parser.add_argument("--login", action="store_true", help="Login mode (use 'login' subcommand)")
    parser.add_argument("--test", action="store_true", help="Test mode (use 'test' subcommand)")

    args = parser.parse_args()

    # Handle legacy flags
    if args.login:
        return cmd_login(args)
    if args.test:
        return asyncio.run(cmd_test(args))

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
