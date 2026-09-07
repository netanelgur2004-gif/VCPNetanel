"""Render VCP scan results into the self-contained HTML report/dashboard."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import List, Optional

from .scorer import VCPScore

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "report_template.html"


def _score_to_row(s: VCPScore) -> dict:
    return {
        "t": s.ticker,
        "s": s.score,
        "tp": s.trend.passed,
        "tt": s.trend.total,
        "nc": s.vcp.num_contractions,
        "vd": round(s.vcp.volume_dryup_score, 0),
        "ti": round(s.vcp.tightness_score, 0),
        "pu": round(s.vcp.prior_uptrend_pct, 1) if s.vcp.prior_uptrend_pct is not None else None,
        "rs": int(s.rs_rating) if s.rs_rating is not None else None,
        "px": round(s.last_close, 2),
        "pv": round(s.vcp.pivot_price, 2) if s.vcp.pivot_price is not None else None,
        "d": round(s.vcp.pivot_extension_pct, 1) if s.vcp.pivot_extension_pct is not None else None,
        "pp": round(s.vcp.pivot_proximity_score, 0),
        "sl": s.stop_loss_price,
        "slp": s.stop_loss_pct,
        "slb": s.stop_loss_basis,
    }


def build_html_report(
    scores: List[VCPScore],
    universe_size: int,
    universe_label: str = "S&P 500 constituents",
    run_date: Optional[str] = None,
    fear_greed: Optional[dict] = None,
    filter_note: Optional[str] = None,
    total_scored: Optional[int] = None,
) -> str:
    """Render the ranked results into the self-contained HTML dashboard.

    `scores` is the list actually shown (e.g. after filtering to setups near
    the pivot with a long-enough base) -- `total_scored` is the larger count
    that were scanned and scored before that filtering, for the "X of Y"
    header line. If omitted, `total_scored` defaults to len(scores).
    """
    rows = sorted((_score_to_row(s) for s in scores), key=lambda r: r["s"], reverse=True)
    html = _TEMPLATE_PATH.read_text()
    # Plain token replacement, not str.format(): the template's CSS/JS is
    # full of literal `{...}` braces that .format() would misparse.
    replacements = {
        "__UNIVERSE_LABEL__": universe_label,
        "__RUN_DATE__": run_date or _dt.date.today().isoformat(),
        "__SHOWN__": str(len(scores)),
        "__TOTAL_SCORED__": str(total_scored if total_scored is not None else len(scores)),
        "__UNIVERSE_SIZE__": str(universe_size),
        "__DATA_JSON__": json.dumps(rows),
        "__FNG_JSON__": json.dumps(fear_greed) if fear_greed else "null",
        "__FILTER_NOTE__": filter_note or "",
    }
    for token, value in replacements.items():
        html = html.replace(token, value)
    return html


def write_html_report(
    scores: List[VCPScore],
    path: str,
    universe_size: int,
    universe_label: str = "S&P 500 constituents",
    run_date: Optional[str] = None,
    fear_greed: Optional[dict] = None,
    filter_note: Optional[str] = None,
    total_scored: Optional[int] = None,
) -> None:
    html = build_html_report(
        scores,
        universe_size,
        universe_label=universe_label,
        run_date=run_date,
        fear_greed=fear_greed,
        filter_note=filter_note,
        total_scored=total_scored,
    )
    Path(path).write_text(html)
