"""
predictor.py — Demand & decay prediction module
Phase 1: linear regression dummy predictor
Phase 3: swap to Colab TimesFM server via HTTP
"""

import sys
import json
import logging
import datetime
from pathlib import Path

import numpy as np
from sklearn.linear_model import LinearRegression

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _series_to_array(trend_series: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Convert [{date, value}] to (X indices, Y values) arrays."""
    values = np.array([row["value"] for row in trend_series], dtype=float)
    x = np.arange(len(values)).reshape(-1, 1)
    return x, values


def _slope_to_growth_rate(slope: float, mean_value: float) -> float:
    """Normalize slope to a -1.0 ~ +1.0 growth rate relative to mean."""
    if mean_value < 1e-9:
        return 0.0
    rate = slope / mean_value
    return float(np.clip(rate, -1.0, 1.0))


# ─── Dummy predictor (Phase 1) ────────────────────────────────────────────────

def _linear_forecast(values: np.ndarray, horizon: int) -> dict:
    """
    Fit a linear trend on historical values and extrapolate.
    Returns forecast array + naive confidence bands (±1 residual std).
    """
    x = np.arange(len(values)).reshape(-1, 1)
    model = LinearRegression()
    model.fit(x, values)

    future_x = np.arange(len(values), len(values) + horizon).reshape(-1, 1)
    forecast = model.predict(future_x)
    forecast = np.clip(forecast, 0, None)

    residuals = values - model.predict(x)
    std = float(np.std(residuals))

    return {
        "forecast": forecast.tolist(),
        "confidence_lower": np.clip(forecast - std, 0, None).tolist(),
        "confidence_upper": (forecast + std).tolist(),
        "slope": float(model.coef_[0]),
        "intercept": float(model.intercept_),
        "r2": float(model.score(x, values)),
        "model": "linear_regression_dummy",
    }


# ─── Colab Foundation Model client (TimesFM / Chronos) ───────────────────────

def _foundation_forecast(time_series: list[float], horizon: int) -> dict:
    """
    POST to Colab prediction server (TimesFM or Chronos).
    Falls back to linear regression if server is unreachable.

    Expected server response:
        {
            "forecast":         [float, ...],
            "confidence_lower": [float, ...],
            "confidence_upper": [float, ...],
            "model":            str
        }
    """
    import httpx

    url = config.COLAB_PREDICTOR_URL
    if not url:
        logger.warning("COLAB_PREDICTOR_URL not set — falling back to linear regression")
        return _linear_forecast(np.array(time_series), horizon)

    try:
        resp = httpx.post(
            f"{url.rstrip('/')}/predict",
            json={"time_series": time_series, "horizon": horizon},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        # Compute slope from forecast trajectory for growth_rate downstream
        forecast = np.array(data["forecast"])
        if len(forecast) >= 2:
            fx = np.arange(len(forecast)).reshape(-1, 1)
            lr = LinearRegression().fit(fx, forecast)
            data["slope"] = float(lr.coef_[0])
        else:
            data["slope"] = 0.0

        return data
    except Exception as e:
        logger.warning("Colab predictor error (%s) — falling back to linear regression", e)
        return _linear_forecast(np.array(time_series), horizon)


# Backward compat alias
_timesfm_forecast = _foundation_forecast


# ─── Public API ──────────────────────────────────────────────────────────────

def predict_demand(trend_series: list[dict], horizon: int = 30) -> dict:
    """
    Predict future demand for the next `horizon` days/weeks.

    DRY_RUN or COLAB_PREDICTOR_URL unset: linear regression.
    LIVE with URL: Colab TimesFM server.

    Returns:
        {
            forecast: [float, ...],          # horizon-length prediction
            confidence_lower: [float, ...],
            confidence_upper: [float, ...],
            slope: float,                    # trend direction
            growth_rate: float,              # -1.0 (dying) to +1.0 (surging)
            model: str,
        }
    """
    if not trend_series:
        # Long-tail keywords often have no pytrends data (too specific to measure).
        # Use a slight positive default (0.15): deliberate keyword selection implies
        # growing demand, not flat. Better prior than assuming 0.
        logger.warning("predict_demand: empty trend_series — using growth_rate=0.15 default")
        mid = 50.0
        return {
            "forecast": [mid] * horizon,
            "confidence_lower": [mid * 0.8] * horizon,
            "confidence_upper": [mid * 1.2] * horizon,
            "slope": 0.5,
            "growth_rate": 0.15,
            "model": "default_positive",
        }

    x, values = _series_to_array(trend_series)
    mean_val = float(np.mean(values))

    if config.DRY_RUN_MODE or not config.COLAB_PREDICTOR_URL:
        logger.info("[%s] predict_demand: linear regression (%d points → +%d)",
                    "DRY" if config.DRY_RUN_MODE else "LIVE_FALLBACK",
                    len(values), horizon)
        result = _linear_forecast(values, horizon)
    else:
        logger.info("[LIVE] predict_demand: TimesFM (%d points → +%d)", len(values), horizon)
        result = _timesfm_forecast(values.tolist(), horizon)

    result["growth_rate"] = _slope_to_growth_rate(result.get("slope", 0.0), mean_val)
    return result


def predict_decay(serp_history: list[dict]) -> float:
    """
    Estimate probability (0.0–1.0) that a competitor's ranking
    will meaningfully decline within 60 days.

    serp_history: list of {date, rank} dicts (oldest first).
    If only one snapshot is available, estimates from page-age heuristics.

    Scoring logic:
      - Ranking trend (worsening = higher decay prob)
      - Content age (older = higher decay prob)
      - Rank volatility (unstable = higher decay prob)
    """
    if not serp_history:
        return 0.5  # unknown — assume 50%

    ranks = [row.get("rank", 10) for row in serp_history if "rank" in row]

    if len(ranks) < 2:
        # Single snapshot — rank-based decay estimate.
        # Revised: even top-ranked content has ~40% decay chance because
        # most established pages are 1-3 years old and aging continuously.
        # rank 1 = 0.40, rank 5 = 0.56, rank 10 = 0.76
        rank = ranks[0] if ranks else 5
        base_prob = 0.40 + (rank - 1) * 0.04
        return float(np.clip(base_prob, 0.20, 0.90))

    ranks_arr = np.array(ranks, dtype=float)
    x = np.arange(len(ranks_arr)).reshape(-1, 1)
    model = LinearRegression().fit(x, ranks_arr)
    slope = float(model.coef_[0])  # positive slope = rank getting worse (higher number)

    volatility = float(np.std(ranks_arr)) / 10.0  # normalize to 0-1 range

    # slope contribution: worsening rank → higher decay probability
    slope_score = np.clip(slope / 5.0, -0.3, 0.3)

    base = 0.5 + slope_score + (volatility * 0.2)
    return float(np.clip(base, 0.05, 0.95))


def predict_content_age_penalty(published_date_str: str | None) -> float:
    """
    Returns an age penalty score (0.0–1.0).
    Content older than 2 years scores near 1.0 (likely stale).
    Content under 6 months scores near 0.0.
    """
    if not published_date_str:
        return 0.5

    try:
        if "T" in published_date_str:
            published = datetime.datetime.fromisoformat(published_date_str).date()
        else:
            published = datetime.date.fromisoformat(published_date_str[:10])
    except (ValueError, TypeError):
        return 0.5

    age_days = (datetime.date.today() - published).days
    # 0 days = 0.0, 180 days = 0.3, 365 days = 0.6, 730+ days = 1.0
    penalty = np.clip(age_days / 730.0, 0.0, 1.0)
    return float(penalty)


def run_predictions(snapshot: dict) -> dict:
    """
    Run all predictions on a collector snapshot.
    Returns a predictions dict ready for scorer.py.
    """
    trend_series = snapshot.get("trend_series", [])
    serp = snapshot.get("serp", [])
    competitors = snapshot.get("competitors", [])

    demand = predict_demand(trend_series, horizon=30)

    # Build per-competitor SERP history (single snapshot for now)
    competitor_predictions = []
    for i, comp in enumerate(competitors):
        serp_entry = serp[i] if i < len(serp) else {}
        rank_history = [{"date": snapshot.get("collected_at", ""), "rank": serp_entry.get("rank", 10)}]

        decay_prob = predict_decay(rank_history)
        age_penalty = predict_content_age_penalty(comp.get("published_date"))

        competitor_predictions.append({
            "url": comp.get("url", ""),
            "rank": serp_entry.get("rank", i + 1),
            "word_count": comp.get("word_count", 0),
            "published_date": comp.get("published_date"),
            "decay_probability": round(decay_prob, 3),
            "age_penalty": round(age_penalty, 3),
        })

    return {
        "keyword": snapshot.get("keyword", ""),
        "geo": snapshot.get("geo", "US"),
        "demand": demand,
        "competitor_predictions": competitor_predictions,
        "predicted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ─── CLI test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    snapshot_path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        config.TRENDS_DIR / "camping_chairs_US.json"

    if not snapshot_path.exists():
        print(f"Snapshot not found: {snapshot_path}")
        print("Run: py core/collector.py first")
        sys.exit(1)

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    predictions = run_predictions(snapshot)

    d = predictions["demand"]
    print("\n=== Demand Forecast ===")
    print(f"  model       : {d['model']}")
    print(f"  growth_rate : {d['growth_rate']:+.3f}  (-1=dying, +1=surging)")
    print(f"  slope       : {d.get('slope', 0):+.3f}")
    print(f"  R2          : {d.get('r2', 0):.3f}")
    print(f"  forecast[0] : {d['forecast'][0]:.1f}")
    print(f"  forecast[-1]: {d['forecast'][-1]:.1f}")

    print("\n=== Competitor Decay Predictions ===")
    print(f"  {'Rank':<5} {'Decay':>6} {'Age':>6}  URL")
    print(f"  {'-'*5} {'-'*6} {'-'*6}  {'-'*45}")
    for cp in predictions["competitor_predictions"]:
        print(
            f"  {cp['rank']:<5} {cp['decay_probability']:>6.3f} "
            f"{cp['age_penalty']:>6.3f}  {cp['url'][:50]}"
        )
