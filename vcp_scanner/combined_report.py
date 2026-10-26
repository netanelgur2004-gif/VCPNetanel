"""Render VCP-screener results merged with their sector's RS rank into a
self-contained HTML report.

A separate module/template from report.py -- the main weekly dashboard
(and the Routine that refreshes it) is untouched. Reuses scorer.VCPScore
and sector_scan's stock-tagging output as-is, no duplicated scoring logic.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Dict, List, Optional

from .scorer import VCPScore
from .sector_universe import ETF_LABELS

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "combined_report_template.html"


def _row(s: VCPScore, tag: dict) -> dict:
    etf = tag.get("sector_etf")
    return {
        "t": s.ticker,
        "s": s.score,
        "tp": s.trend.passed,
        "tt": s.trend.total,
        "nc": s.vcp.num_contractions,
        "rs": int(s.rs_rating) if s.rs_rating is not None else None,
        "px": round(s.last_close, 2),
        "d": round(s.vcp.pivot_extension_pct, 1) if s.vcp.pivot_extension_pct is not None else None,
        "sl": s.stop_loss_price,
        "slp": s.stop_loss_pct,
        "sector": etf,
        "sector_name": ETF_LABELS.get(etf, etf) if etf else None,
        "sector_rank": tag.get("sector_rank"),
        "top": bool(tag.get("in_top_sector")),
    }


def build_html_report(
    scores: List[VCPScore],
    tags: Dict[str, dict],
    universe_size: int,
    top_n: int,
    run_date: Optional[str] = None,
) -> str:
    rows = sorted(
        (_row(s, tags.get(s.ticker, {})) for s in scores),
        key=lambda r: (not r["top"], -(r["s"])),
    )
    html = _TEMPLATE_PATH.read_text()
    replacements = {
        "__RUN_DATE__": run_date or _dt.date.today().isoformat(),
        "__SHOWN__": str(len(scores)),
        "__UNIVERSE_SIZE__": str(universe_size),
        "__TOP_N__": str(top_n),
        "__DATA_JSON__": json.dumps(rows),
    }
    for token, value in replacements.items():
        html = html.replace(token, value)
    return html


def write_html_report(
    scores: List[VCPScore],
    tags: Dict[str, dict],
    path: str,
    universe_size: int,
    top_n: int,
    run_date: Optional[str] = None,
) -> None:
    html = build_html_report(scores, tags, universe_size, top_n, run_date=run_date)
    Path(path).write_text(html)
