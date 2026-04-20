"""
collector.py — Data collection module
Fetches keyword trends, Search Console data, SERP rankings, and competitor pages.
"""

import os
import sys
import time
import random
import sqlite3
import json
import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import logging

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

# ─── SQLite setup ────────────────────────────────────────────────────────────

DB_PATH = config.RAW_DIR / "trends.db"


def _get_db() -> sqlite3.Connection:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trend_snapshots (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword   TEXT NOT NULL,
            geo       TEXT NOT NULL,
            date      TEXT NOT NULL,
            value     REAL,
            source    TEXT,
            captured_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS serp_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword     TEXT NOT NULL,
            rank        INTEGER,
            url         TEXT,
            title       TEXT,
            captured_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def _save_trend_rows(keyword: str, geo: str, series: dict, source: str) -> None:
    conn = _get_db()
    rows = [(keyword, geo, date, float(val), source) for date, val in series.items()]
    conn.executemany(
        "INSERT INTO trend_snapshots (keyword, geo, date, value, source) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


# ─── Dummy data generators ───────────────────────────────────────────────────

def _dummy_trend_series(keyword: str) -> dict:
    """Generate a plausible 12-month relative trend series (0-100)."""
    import numpy as np
    random.seed(hash(keyword) % 2**32)
    base = random.randint(30, 70)
    dates = []
    values = []
    today = datetime.date.today()
    for i in range(52):  # 52 weeks
        d = today - datetime.timedelta(weeks=51 - i)
        dates.append(str(d))
        noise = random.gauss(0, 5)
        trend = i * random.uniform(-0.3, 0.5)
        val = max(0, min(100, base + trend + noise))
        values.append(round(val, 1))
    return dict(zip(dates, values))


def _dummy_gsc_data(keyword: str, days: int = 90) -> dict:
    """Simulated GSC clicks + impressions for the past N days."""
    random.seed(hash(keyword + "gsc") % 2**32)
    today = datetime.date.today()
    records = []
    base_clicks = random.randint(50, 500)
    base_impressions = base_clicks * random.randint(10, 50)
    for i in range(days):
        d = today - datetime.timedelta(days=days - 1 - i)
        noise = random.gauss(1.0, 0.15)
        records.append({
            "date": str(d),
            "clicks": max(0, int(base_clicks * noise)),
            "impressions": max(0, int(base_impressions * noise)),
            "ctr": round(base_clicks / base_impressions, 4),
            "position": round(random.uniform(1.5, 15.0), 1),
        })
    return {"keyword": keyword, "records": records}


def _dummy_serp(keyword: str, num_results: int = 10) -> list[dict]:
    domains = [
        "rei.com", "outdoorgearlab.com", "wirecutter.com",
        "amazon.com", "backcountry.com", "cleverhiker.com",
        "switchbacktravel.com", "outdoorlife.com", "cabelas.com", "moosejaw.com",
    ]
    random.seed(hash(keyword + "serp") % 2**32)
    random.shuffle(domains)
    results = []
    for rank, domain in enumerate(domains[:num_results], start=1):
        slug = keyword.lower().replace(" ", "-")
        results.append({
            "rank": rank,
            "url": f"https://www.{domain}/{slug}",
            "title": f"Best {keyword.title()} — {domain.split('.')[0].title()} Guide",
            "snippet": f"Top picks for {keyword} reviewed by experts at {domain}.",
        })
    return results


def _dummy_page(url: str) -> dict:
    random.seed(hash(url) % 2**32)
    return {
        "url": url,
        "title": f"Best Products — {url.split('/')[2]}",
        "word_count": random.randint(800, 3500),
        "published_date": str(
            datetime.date.today() - datetime.timedelta(days=random.randint(30, 730))
        ),
        "headings": ["Introduction", "Top Picks", "Buying Guide", "FAQ", "Conclusion"],
        "internal_links": random.randint(3, 25),
        "external_links": random.randint(1, 10),
    }


# ─── pytrends (live) ─────────────────────────────────────────────────────────

def _build_pytrends():
    from pytrends.request import TrendReq
    return TrendReq(
        hl="en-US",
        tz=360,
        timeout=(10, 25),
        retries=2,
        backoff_factor=0.5,
    )


@retry(
    stop=stop_after_attempt(config.PYTRENDS_MAX_RETRIES),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _fetch_pytrends_with_retry(keyword: str, timeframe: str, geo: str) -> dict:
    pt = _build_pytrends()
    pt.build_payload([keyword], timeframe=timeframe, geo=geo)
    df = pt.interest_over_time()
    if df.empty:
        return {}
    series = df[keyword].to_dict()
    return {str(k.date()): float(v) for k, v in series.items()}


# ─── Public API ──────────────────────────────────────────────────────────────

def get_keyword_trends(
    keyword: str,
    timeframe: str = "today 12-m",
    geo: str = "US",
) -> dict:
    """
    Returns weekly trend series {date_str: value}.
    DRY_RUN: dummy data. LIVE: pytrends with exponential backoff + random delay.
    """
    if config.DRY_RUN_MODE:
        logger.info("[DRY] get_keyword_trends: %s", keyword)
        series = _dummy_trend_series(keyword)
        _save_trend_rows(keyword, geo, series, "dummy")
        return series

    delay = random.uniform(config.PYTRENDS_DELAY_MIN, config.PYTRENDS_DELAY_MAX)
    logger.info("Fetching pytrends for '%s' (delay %.1fs)", keyword, delay)
    time.sleep(delay)

    series = _fetch_pytrends_with_retry(keyword, timeframe, geo)
    if series:
        _save_trend_rows(keyword, geo, series, "pytrends")
    return series


def get_search_console_data(keyword: str, days: int = 90) -> dict:
    """
    Returns GSC clicks + impressions for the past N days.
    DRY_RUN: dummy data. LIVE: Google Search Console API.
    """
    if config.DRY_RUN_MODE:
        logger.info("[DRY] get_search_console_data: %s", keyword)
        return _dummy_gsc_data(keyword, days)

    # Live GSC requires service account credentials
    if not config.GOOGLE_SERVICE_ACCOUNT or not Path(config.GOOGLE_SERVICE_ACCOUNT).exists():
        logger.warning("GSC service account not configured — returning empty")
        return {"keyword": keyword, "records": []}

    from googleapiclient.discovery import build
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT,
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    service = build("searchconsole", "v1", credentials=creds)

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days)
    body = {
        "startDate": str(start_date),
        "endDate": str(end_date),
        "dimensions": ["date"],
        "dimensionFilterGroups": [{
            "filters": [{
                "dimension": "query",
                "operator": "equals",
                "expression": keyword,
            }]
        }],
    }
    resp = service.searchanalytics().query(
        siteUrl=config.GOOGLE_CSE_ID, body=body
    ).execute()

    records = [
        {
            "date": row["keys"][0],
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": round(row.get("ctr", 0), 4),
            "position": round(row.get("position", 0), 1),
        }
        for row in resp.get("rows", [])
    ]
    return {"keyword": keyword, "records": records}


def merge_trend_data(pytrends_data: dict, gsc_data: dict) -> list[dict]:
    """
    Combines relative pytrends values with absolute GSC clicks
    to produce an approximate absolute time series for TimesFM input.

    Strategy: scale pytrends (0-100) to match GSC click magnitude,
    then fill gaps where GSC data is missing.
    """
    gsc_by_date = {r["date"]: r for r in gsc_data.get("records", [])}

    if not gsc_by_date:
        # No GSC data — use pytrends as-is
        return [
            {"date": d, "value": v, "source": "pytrends_only"}
            for d, v in sorted(pytrends_data.items())
        ]

    # Compute scaling factor from overlapping dates
    overlap_pt, overlap_gsc = [], []
    for date, gsc_row in gsc_by_date.items():
        if date in pytrends_data and gsc_row["clicks"] > 0:
            overlap_pt.append(pytrends_data[date])
            overlap_gsc.append(gsc_row["clicks"])

    if overlap_pt:
        import numpy as np
        scale = float(np.mean(overlap_gsc)) / (float(np.mean(overlap_pt)) + 1e-9)
    else:
        scale = 1.0

    merged = []
    all_dates = sorted(set(list(pytrends_data.keys()) + list(gsc_by_date.keys())))
    for date in all_dates:
        if date in gsc_by_date:
            merged.append({
                "date": date,
                "value": gsc_by_date[date]["clicks"],
                "source": "gsc",
            })
        elif date in pytrends_data:
            merged.append({
                "date": date,
                "value": round(pytrends_data[date] * scale, 1),
                "source": "pytrends_scaled",
            })

    return merged


def get_serp_rankings(keyword: str, num_results: int = 10) -> list[dict]:
    """
    Returns top N SERP results with rank, URL, title.
    DRY_RUN: dummy data. LIVE: SerpAPI.
    """
    if config.DRY_RUN_MODE:
        logger.info("[DRY] get_serp_rankings: %s", keyword)
        return _dummy_serp(keyword, num_results)

    if not config.SERPAPI_KEY:
        logger.warning("SERPAPI_KEY not set — returning empty")
        return []

    params = {
        "q": keyword,
        "api_key": config.SERPAPI_KEY,
        "num": num_results,
        "gl": "us",
        "hl": "en",
    }
    resp = httpx.get("https://serpapi.com/search", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for i, item in enumerate(data.get("organic_results", [])[:num_results], start=1):
        results.append({
            "rank": i,
            "url": item.get("link", ""),
            "title": item.get("title", ""),
            "snippet": item.get("snippet", ""),
        })
    return results


def crawl_competitor_page(url: str) -> dict:
    """
    Fetches a competitor page and extracts: title, word count,
    published date, heading structure.
    DRY_RUN: dummy data. LIVE: httpx + BeautifulSoup.
    """
    if config.DRY_RUN_MODE:
        logger.info("[DRY] crawl_competitor_page: %s", url)
        return _dummy_page(url)

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Failed to crawl %s: %s", url, e)
        return {"url": url, "error": str(e)}

    soup = BeautifulSoup(resp.text, "lxml")

    title = soup.title.string.strip() if soup.title else ""
    body_text = soup.get_text(separator=" ", strip=True)
    word_count = len(body_text.split())

    headings = [
        tag.get_text(strip=True)
        for tag in soup.find_all(["h1", "h2", "h3"])
    ][:10]

    # Try common published-date patterns
    published_date = None
    for selector in [
        {"name": "meta", "attrs": {"property": "article:published_time"}},
        {"name": "time"},
    ]:
        tag = soup.find(**selector)
        if tag:
            published_date = tag.get("content") or tag.get("datetime") or tag.get_text()
            break

    internal_links = len([
        a for a in soup.find_all("a", href=True)
        if url.split("/")[2] in a["href"]
    ])
    external_links = len([
        a for a in soup.find_all("a", href=True)
        if a["href"].startswith("http") and url.split("/")[2] not in a["href"]
    ])

    return {
        "url": url,
        "title": title,
        "word_count": word_count,
        "published_date": published_date,
        "headings": headings,
        "internal_links": internal_links,
        "external_links": external_links,
    }


# ─── Full collection run ─────────────────────────────────────────────────────

def collect(keyword: str, geo: str = "US") -> dict:
    """
    Run the full collection pipeline for one keyword.
    Returns a structured snapshot ready for predictor + scorer.
    """
    from rich.console import Console
    from rich.table import Table
    console = Console()

    console.print(f"\n[bold cyan]Collecting:[/] {keyword} ({geo})")

    # 1. Trends
    console.print("  [1/4] pytrends ...", end=" ")
    trends = get_keyword_trends(keyword, geo=geo)
    console.print(f"[green]{len(trends)} weeks[/]")

    # 2. GSC
    console.print("  [2/4] Search Console ...", end=" ")
    gsc = get_search_console_data(keyword)
    console.print(f"[green]{len(gsc.get('records', []))} days[/]")

    # 3. Merge
    merged = merge_trend_data(trends, gsc)

    # 4. SERP
    console.print("  [3/4] SERP rankings ...", end=" ")
    serp = get_serp_rankings(keyword)
    console.print(f"[green]{len(serp)} results[/]")

    # 5. Crawl top 3 competitors
    console.print("  [4/4] Crawling top 3 competitors ...")
    competitor_pages = []
    for item in serp[:3]:
        page = crawl_competitor_page(item["url"])
        competitor_pages.append(page)
        console.print(
            f"    [dim]{item['url'][:60]}[/] → "
            f"{page.get('word_count', '?')} words"
        )

    snapshot = {
        "keyword": keyword,
        "geo": geo,
        "collected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "trend_series": merged,
        "serp": serp,
        "competitors": competitor_pages,
        "raw_trends_count": len(trends),
        "gsc_days": len(gsc.get("records", [])),
    }

    # Persist to raw/
    out_path = config.TRENDS_DIR / f"{keyword.replace(' ', '_')}_{geo}.json"
    config.TRENDS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"\n  [bold green]Saved:[/] {out_path.name}")

    return snapshot


# ─── CLI test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    keyword = sys.argv[1] if len(sys.argv) > 1 else "camping chairs"
    geo = sys.argv[2] if len(sys.argv) > 2 else "US"
    result = collect(keyword, geo)

    from rich import print as rprint
    rprint("\n[bold]Snapshot summary:[/]")
    rprint(f"  keyword     : {result['keyword']}")
    rprint(f"  trend weeks : {result['raw_trends_count']}")
    rprint(f"  gsc days    : {result['gsc_days']}")
    rprint(f"  serp hits   : {len(result['serp'])}")
    rprint(f"  competitors : {len(result['competitors'])}")
    rprint(f"\n[dim]Trend series (last 5):[/]")
    for row in result["trend_series"][-5:]:
        rprint(f"  {row['date']}  {row['value']:>8.1f}  [{row['source']}]")
    rprint(f"\n[dim]Top SERP:[/]")
    for s in result["serp"][:3]:
        rprint(f"  #{s['rank']}  {s['url'][:60]}")
