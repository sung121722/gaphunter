"""
main.py — GapHunter pipeline orchestrator
CLI entry point for all operations.
"""

import sys
import json
import argparse
import logging
import datetime
from pathlib import Path

import config

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("main")


# ─── Pipeline ─────────────────────────────────────────────────────────────────

def run_pipeline(niche: str, geo: str, lang: str, dry_run: bool, report_only: bool) -> dict:
    from core.collector  import collect
    from core.predictor  import run_predictions
    from core.scorer     import score_gap
    from core.generator  import generate_post
    from wiki_agent      import ingest

    mode_tag = "[DRY RUN]" if dry_run else "[LIVE]"
    print(f"\n{'='*55}")
    print(f"  GapHunter {mode_tag}")
    print(f"  Niche : {niche}")
    print(f"  Geo   : {geo}  |  Lang: {lang}")
    print(f"  Date  : {datetime.date.today()}")
    print(f"{'='*55}\n")

    # ── Step 1: Collect ──────────────────────────────────────
    print("[1/4] Collecting data ...")
    snapshot = collect(niche, geo=geo)

    # ── Step 2: Predict ──────────────────────────────────────
    print("\n[2/4] Running predictions ...")
    predictions = run_predictions(snapshot)
    demand = predictions["demand"]
    print(f"  growth_rate : {demand['growth_rate']:+.3f}")
    print(f"  model       : {demand['model']}")

    # ── Step 3: Score ────────────────────────────────────────
    print("\n[3/4] Scoring gap opportunity ...")
    gap_result = score_gap(niche, predictions)
    score  = gap_result["gap_score"]
    action = gap_result["action"]
    print(f"  gap_score : {score}")
    print(f"  action    : {action}")
    print(f"  gap_date  : {gap_result['predicted_gap_date']} ({gap_result['days_until_gap']} days)")

    # ── Step 4: Generate (if score qualifies) ────────────────
    post_result = {}
    if not report_only and score >= config.GAP_SCORE_HIGH:
        print(f"\n[4/4] Generating content (score={score} >= {config.GAP_SCORE_HIGH}) ...")
        post_result = generate_post(niche, gap_result, language=lang)
        if post_result.get("skipped"):
            print(f"  Content generation skipped: {post_result.get('reason')}")
        else:
            print(f"  Words    : {post_result['word_count']}")
            print(f"  Saved to : {post_result['file_path']}")
            if post_result["ai_signature_warnings"]:
                print(f"  Warnings : {post_result['ai_signature_warnings']}")
    elif report_only:
        print("\n[4/4] Skipped (--report-only)")
    else:
        print(f"\n[4/4] Skipped (score {score} < threshold {config.GAP_SCORE_HIGH})")

    # ── Step 5: Publish ──────────────────────────────────────
    pub_result = {}
    if post_result and not post_result.get("skipped"):
        from core.publisher import publish
        print("\n[5/5] Publishing ...")
        title   = f"{niche} 추천 2026" if lang == "ko" else f"Best {niche.title()} 2026"
        content = post_result.get("content", "")
        pub_result = publish(title, content, language=lang, dry_run=dry_run)
        status = pub_result.get("status", "unknown")
        print(f"  status   : {status}")
        if status in ("published", "dry_run"):
            print(f"  post_url : {pub_result.get('post_url', '')}")
        elif status == "blocked":
            for issue in pub_result.get("issues", []):
                print(f"  [!] {issue}")

    # ── Wiki ingest ──────────────────────────────────────────
    scan_result = {
        "keyword":     niche,
        "geo":         geo,
        "predictions": predictions,
        "gap_result":  gap_result,
        "post_result": post_result,
    }
    ingest(scan_result)
    print("\n  Wiki updated.")

    # ── Summary ──────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  RESULT: {niche}")
    print(f"  Score : {score}/100  ->  {action}")
    print(f"  Gap opens in {gap_result['days_until_gap']} days ({gap_result['predicted_gap_date']})")
    if post_result and not post_result.get("skipped"):
        print(f"  Post  : {Path(post_result['file_path']).name}")
    if pub_result and pub_result.get("status") in ("published", "dry_run"):
        print(f"  Publish : {pub_result.get('post_url', pub_result.get('status'))}")
    print(f"{'='*55}\n")

    return scan_result


# ─── CLI handlers ─────────────────────────────────────────────────────────────

def cmd_init() -> None:
    from wiki_agent import init_wiki
    init_wiki()
    print("\nGapHunter initialized.")
    print("Next step: py main.py --niche 'camping chairs' --dry-run\n")


def cmd_wiki_lint() -> None:
    from wiki_agent import lint
    report = lint()
    print("\n=== Wiki Lint ===")
    print(f"  Pages     : {report['pages_found']}")
    print(f"  Issues    : {len(report['issues'])}")
    for i in report["issues"]:
        print(f"    [!] {i}")
    print(f"  Suggestions: {len(report['suggestions'])}")
    for s in report["suggestions"]:
        safe = s.encode("ascii", errors="replace").decode("ascii")
        print(f"    [>] {safe}")


def cmd_report(niche: str, geo: str) -> None:
    """Print gap report from cached snapshot without re-collecting."""
    from core.predictor import run_predictions
    from core.scorer    import score_gap

    slug = niche.replace(" ", "_")
    snapshot_path = config.TRENDS_DIR / f"{slug}_{geo}.json"

    if not snapshot_path.exists():
        print(f"No cached snapshot for '{niche}' ({geo}).")
        print(f"Run: py main.py --niche \"{niche}\" --dry-run  first")
        sys.exit(1)

    snapshot    = json.loads(snapshot_path.read_text(encoding="utf-8"))
    predictions = run_predictions(snapshot)
    gap_result  = score_gap(niche, predictions)

    print(f"\n=== Gap Report: {niche} ({geo}) ===")
    print(f"  Score      : {gap_result['gap_score']}/100")
    print(f"  Action     : {gap_result['action']}")
    print(f"  Gap date   : {gap_result['predicted_gap_date']}")
    print(f"  Days left  : {gap_result['days_until_gap']}")
    print(f"  Competitor : {gap_result['competitor_url'][:55]}")
    print(f"  Decay prob : {gap_result['decay_probability']}")
    print()
    print("  Sub-scores:")
    for k, v in gap_result["sub_scores"].items():
        bar = "#" * int(v * 20)
        print(f"    {k:<22} {v:.3f}  |{bar:<20}|")


# ─── Argument parser ─────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gaphunter",
        description="GapHunter — SEO gap prediction and content generation",
    )
    p.add_argument("--init",        action="store_true", help="Initialize wiki directory")
    p.add_argument("--wiki-lint",   action="store_true", help="Lint wiki for issues")
    p.add_argument("--niche",       type=str,            help="Target niche keyword")
    p.add_argument("--geo",         type=str, default="US", help="Geographic market (default: US)")
    p.add_argument("--lang",        type=str, default="en",
                   choices=["en", "ko"], help="Content language: en (default) or ko")
    p.add_argument("--dry-run",     action="store_true", help="Use dummy data, no real API calls")
    p.add_argument("--report-only", action="store_true", help="Score only, skip content generation")
    return p


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    # --init
    if args.init:
        cmd_init()
        return

    # --wiki-lint
    if args.wiki_lint:
        cmd_wiki_lint()
        return

    # --niche required for everything else
    if not args.niche:
        parser.print_help()
        sys.exit(1)

    # Apply dry-run override
    if args.dry_run:
        config.DRY_RUN_MODE = True

    # Validate config
    missing = config.validate_config(dry_run=config.DRY_RUN_MODE)
    if missing:
        print(f"\n[ERROR] Missing API keys for live mode: {missing}")
        print("Set DRY_RUN_MODE=true or add keys to .env\n")
        sys.exit(1)

    config.print_config_summary()

    # --report-only (uses cached snapshot)
    if args.report_only:
        cmd_report(args.niche, args.geo)
        return

    # Auto-set geo/lang defaults for Korean
    lang = args.lang
    geo  = args.geo
    if lang == "ko" and geo == "US":
        geo = "KR"

    # Full pipeline
    run_pipeline(
        niche       = args.niche,
        geo         = geo,
        lang        = lang,
        dry_run     = config.DRY_RUN_MODE,
        report_only = args.report_only,
    )


if __name__ == "__main__":
    main()
