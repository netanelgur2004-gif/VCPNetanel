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
    }


def build_html_report(
    scores: List[VCPScore],
    universe_size: int,
    universe_label: str = "S&P 500 constituents",
    run_date: Optional[str] = None,
) -> str:
    """Render the ranked results into the self-contained HTML dashboard."""
    rows = sorted((_score_to_row(s) for s in scores), key=lambda r: r["s"], reverse=True)
    html = _TEMPLATE_PATH.read_text()
    # Plain token replacement, not str.format(): the template's CSS/JS is
    # full of literal `{...}` braces that .format() would misparse.
    replacements = {
        "__UNIVERSE_LABEL__": universe_label,
        "__RUN_DATE__": run_date or _dt.date.today().isoformat(),
        "__SCANNED__": str(len(scores)),
        "__UNIVERSE_SIZE__": str(universe_size),
        "__DATA_JSON__": json.dumps(rows),
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
) -> None:
    html = build_html_report(scores, universe_size, universe_label=universe_label, run_date=run_date)
    Path(path).write_text(html)
