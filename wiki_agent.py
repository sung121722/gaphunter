"""
wiki_agent.py — LLM-Wiki maintenance agent (Karpathy pattern)
Manages /wiki markdown directory: ingest scan results, query, lint.
"""

import sys
import json
import datetime
import logging
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config

logger = logging.getLogger(__name__)

WIKI = config.WIKI_DIR

# ─── Wiki file templates ───────────────────────────────────────────────────────

_TEMPLATES = {
    "index.md": """\
# GapHunter Wiki

Auto-maintained knowledge base. Do not edit manually — updated by wiki_agent.py.

## Pages
- [competitors.md](competitors.md) — Competitor content status and decay patterns
- [gaps.md](gaps.md) — Predicted gaps sorted by score
- [keywords.md](keywords.md) — Keyword lifecycle tracking
- [wins.md](wins.md) — Successfully captured gaps and revenue data
- [insights.md](insights.md) — Patterns and system insights
- [log.md](log.md) — Append-only operation log

## Last updated
{timestamp}
""",
    "log.md": """\
# Operation Log

Append-only. Each run appends a new entry.

---

## {timestamp} — Wiki initialized

System initialized. All wiki pages created.

""",
    "competitors.md": """\
# Competitor Content Status

Tracked URLs, decay signals, and content quality scores.

| URL | Keyword | Words | Decay Prob | Age Penalty | Last Checked |
|-----|---------|-------|-----------|-------------|--------------|

""",
    "gaps.md": """\
# Predicted Gaps

Sorted by gap score descending. Updated each daily scan run.

| Keyword | Score | Action | Gap Date | Competitor |
|---------|-------|--------|----------|-----------|

""",
    "keywords.md": """\
# Keyword Lifecycle Tracking

Each keyword's trend history and prediction record.

""",
    "wins.md": """\
# Captured Gaps

Successfully published content that filled predicted gaps.

| Keyword | Published | Gap Score | Post URL | Revenue |
|---------|-----------|-----------|----------|---------|

""",
    "insights.md": """\
# System Insights

Patterns discovered by GapHunter across niches and time.

""",
}


# ─── Core wiki operations ─────────────────────────────────────────────────────

def init_wiki() -> None:
    """Create /wiki directory and initialize all 6 markdown files."""
    WIKI.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    for filename, template in _TEMPLATES.items():
        path = WIKI / filename
        if path.exists():
            logger.info("Wiki file already exists, skipping: %s", filename)
            continue
        content = template.format(timestamp=now)
        path.write_text(content, encoding="utf-8")
        logger.info("Created: %s", path)

    print(f"Wiki initialized at: {WIKI}")


def _append_log(message: str) -> None:
    """Append a timestamped entry to log.md."""
    log_path = WIKI / "log.md"
    if not log_path.exists():
        init_wiki()

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n## {now} — {message}\n"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(entry)


def _read_page(filename: str) -> str:
    path = WIKI / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_page(filename: str, content: str) -> None:
    (WIKI / filename).write_text(content, encoding="utf-8")


# ─── Ingest ───────────────────────────────────────────────────────────────────

def _update_gaps_page(gap_result: dict) -> None:
    """Insert or update a gap entry in gaps.md, keeping sorted by score."""
    content   = _read_page("gaps.md")
    keyword   = gap_result["keyword"]
    score     = gap_result["gap_score"]
    action    = gap_result["action"]
    gap_date  = gap_result["predicted_gap_date"]
    comp_url  = gap_result.get("competitor_url", "")[:50]

    new_row = f"| {keyword} | {score} | {action} | {gap_date} | {comp_url} |"

    # Remove existing row for this keyword if present
    lines = content.splitlines()
    lines = [l for l in lines if f"| {keyword} |" not in l]

    # Find table body insertion point (after header rows)
    table_start = next((i for i, l in enumerate(lines) if l.startswith("|---")), None)
    if table_start is not None:
        lines.insert(table_start + 1, new_row)
    else:
        lines.append(new_row)

    _write_page("gaps.md", "\n".join(lines))


def _update_competitors_page(competitor_predictions: list[dict], keyword: str) -> None:
    """Update competitors.md with latest decay signals."""
    content = _read_page("competitors.md")
    today   = str(datetime.date.today())

    for cp in competitor_predictions:
        url   = cp.get("url", "")[:50]
        words = cp.get("word_count", 0)
        decay = cp.get("decay_probability", 0)
        age   = cp.get("age_penalty", 0)

        new_row = f"| {url} | {keyword} | {words} | {decay:.3f} | {age:.3f} | {today} |"

        lines = content.splitlines()
        lines = [l for l in lines if url not in l]

        table_start = next((i for i, l in enumerate(lines) if l.startswith("|---")), None)
        if table_start is not None:
            lines.insert(table_start + 1, new_row)
        else:
            lines.append(new_row)

        content = "\n".join(lines)

    _write_page("competitors.md", content)


def _update_keywords_page(keyword: str, predictions: dict, gap_result: dict) -> None:
    """Append or update keyword entry in keywords.md."""
    content  = _read_page("keywords.md")
    today    = str(datetime.date.today())
    growth   = predictions["demand"].get("growth_rate", 0)
    score    = gap_result["gap_score"]

    header = f"## {keyword}"
    entry = (
        f"{header}\n"
        f"- Last scanned: {today}\n"
        f"- Growth rate:  {growth:+.3f}\n"
        f"- Gap score:    {score}\n"
        f"- Action:       {gap_result['action']}\n"
        f"- Gap date:     {gap_result['predicted_gap_date']}\n\n"
    )

    # Replace existing section if present
    if header in content:
        pattern = re.compile(
            rf"(## {re.escape(keyword)}\n.*?)(?=## |\Z)", re.DOTALL
        )
        content = pattern.sub(entry, content)
    else:
        content += entry

    _write_page("keywords.md", content)


def ingest(scan_result: dict) -> None:
    """
    Process a full pipeline result and update all relevant wiki pages.

    scan_result: combined output from collector + predictor + scorer + generator
      {
        keyword, geo,
        predictions: {...},      # predictor output
        gap_result: {...},       # scorer output
        post_result: {...},      # generator output (optional)
      }
    """
    keyword     = scan_result.get("keyword", "unknown")
    predictions = scan_result.get("predictions", {})
    gap_result  = scan_result.get("gap_result", {})
    post_result = scan_result.get("post_result", {})

    _update_gaps_page(gap_result)
    _update_competitors_page(
        predictions.get("competitor_predictions", []), keyword
    )
    _update_keywords_page(keyword, predictions, gap_result)

    # Update index.md timestamp
    index = _read_page("index.md")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    index = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", now, index)
    _write_page("index.md", index)

    log_msg = (
        f"Ingested '{keyword}' — score: {gap_result.get('gap_score', '?')} "
        f"({gap_result.get('action', '?')})"
    )
    if post_result and not post_result.get("skipped"):
        log_msg += f" — post generated: {post_result.get('word_count', 0)} words"

    _append_log(log_msg)
    logger.info("Wiki ingested: %s", log_msg)


# ─── Query ────────────────────────────────────────────────────────────────────

def query(question: str) -> str:
    """
    Search wiki pages for relevant content, then answer via Claude API.
    Falls back to wiki-only answer if no API key.
    """
    # Gather all wiki content
    wiki_context = ""
    for page in WIKI.glob("*.md"):
        wiki_context += f"\n\n### {page.name}\n{page.read_text(encoding='utf-8')}"

    if not wiki_context.strip():
        return "Wiki is empty. Run --init first."

    if config.DRY_RUN_MODE or not config.ANTHROPIC_API_KEY:
        # Simple keyword search fallback
        question_lower = question.lower()
        relevant = []
        for line in wiki_context.splitlines():
            if any(word in line.lower() for word in question_lower.split()):
                relevant.append(line)
        if relevant:
            return "Wiki search results:\n" + "\n".join(relevant[:20])
        return "No relevant wiki content found for: " + question

    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system="You are the GapHunter wiki assistant. Answer questions using only the provided wiki context. Be concise and specific.",
        messages=[{
            "role": "user",
            "content": f"Wiki context:\n{wiki_context[:8000]}\n\nQuestion: {question}"
        }],
    )
    return message.content[0].text


# ─── Lint ─────────────────────────────────────────────────────────────────────

def lint() -> dict:
    """
    Scan wiki for health issues:
    - Stale predictions (gap date already passed)
    - Empty pages
    - Orphaned keywords (in keywords.md but not in gaps.md)
    - Keywords with URGENT score not yet acted on
    """
    issues = []
    suggestions = []
    today = datetime.date.today()

    # 1. Stale gap predictions
    gaps_content = _read_page("gaps.md")
    for line in gaps_content.splitlines():
        if "|" not in line or line.startswith("| Keyword") or line.startswith("|---"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) >= 4:
            try:
                gap_date = datetime.date.fromisoformat(parts[3])
                if gap_date < today:
                    issues.append(f"STALE: '{parts[0]}' gap date {parts[3]} has passed")
            except ValueError:
                pass

    # 2. Empty pages
    for filename in _TEMPLATES:
        if filename in ("log.md", "index.md"):
            continue
        content = _read_page(filename)
        table_rows = [l for l in content.splitlines()
                      if l.startswith("|") and not l.startswith("| ---") and not l.startswith("|---")
                      and "---" not in l and not any(
                          h in l for h in ["Keyword", "URL", "Page", "Published"]
                      )]
        if not table_rows and filename in ("gaps.md", "competitors.md"):
            suggestions.append(f"EMPTY TABLE: {filename} has no data rows — run a scan")

    # 3. URGENT gaps not yet in wins.md
    wins_content = _read_page("wins.md")
    for line in gaps_content.splitlines():
        if "GENERATE_NOW" in line and "|" in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if parts and parts[0] not in wins_content:
                suggestions.append(f"ACTION NEEDED: '{parts[0]}' is URGENT but not in wins.md")

    report = {
        "issues":      issues,
        "suggestions": suggestions,
        "pages_found": len(list(WIKI.glob("*.md"))),
        "linted_at":   str(today),
    }

    _append_log(
        f"Lint complete — {len(issues)} issues, {len(suggestions)} suggestions"
    )
    return report


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "--init"

    if cmd == "--init":
        init_wiki()
        print("Wiki pages created:")
        for f in sorted(WIKI.glob("*.md")):
            print(f"  {f.name}")

    elif cmd == "--lint":
        if not WIKI.exists():
            print("Wiki not initialized. Run: py wiki_agent.py --init")
            sys.exit(1)
        report = lint()
        print("\n=== Wiki Lint Report ===")
        print(f"  Pages found : {report['pages_found']}")
        print(f"  Issues      : {len(report['issues'])}")
        for i in report["issues"]:
            print(f"    [!] {i}")
        print(f"  Suggestions : {len(report['suggestions'])}")
        for s in report["suggestions"]:
            print(f"    [>] {s}".encode("ascii", errors="replace").decode("ascii"))

    elif cmd == "--query" and len(sys.argv) > 2:
        question = " ".join(sys.argv[2:])
        print(f"\nQuery: {question}")
        print("-" * 40)
        print(query(question))

    else:
        print("Usage:")
        print("  py wiki_agent.py --init")
        print("  py wiki_agent.py --lint")
        print("  py wiki_agent.py --query 'what gaps are urgent?'")
