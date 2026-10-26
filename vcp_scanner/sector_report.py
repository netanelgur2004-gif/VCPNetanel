"""Render ranked sector/theme ETF results into a self-contained HTML report.

Mirrors report.py / double_sweep_report.py's token-based templating (plain
str.replace, not .format(), since the template's CSS/JS has literal `{...}`).
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import List, Optional

from .sector_scan import SectorResult
from .sector_universe import ETF_LABELS

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "sector_report_template.html"


def _result_to_row(r: SectorResult) -> dict:
    return {
        "rank": r.rs.rank,
        "t": r.ticker,
        "sector": ETF_LABELS.get(r.ticker, r.ticker),
        "rs": r.rs.score,
        "hi": r.rs.at_52w_high,
        "status": r.status,
        "tp": r.trend.passed,
        "tt": r.trend.total,
        "nc": r.vcp.num_contractions,
        "px": round(r.last_close, 2),
        "d": round(r.vcp.pivot_extension_pct, 1) if r.vcp.pivot_extension_pct is not None else None,
    }


def build_html_report(
    results: List[SectorResult],
    universe_label: str = "sector & theme ETFs",
    run_date: Optional[str] = None,
) -> str:
    rows = [_result_to_row(r) for r in results]
    html = _TEMPLATE_PATH.read_text()
    replacements = {
        "__UNIVERSE_LABEL__": universe_label,
        "__RUN_DATE__": run_date or _dt.date.today().isoformat(),
        "__SHOWN__": str(len(results)),
        "__UNIVERSE_SIZE__": str(len(results)),
        "__DATA_JSON__": json.dumps(rows),
    }
    for token, value in replacements.items():
        html = html.replace(token, value)
    return html


def write_html_report(
    results: List[SectorResult],
    path: str,
    universe_label: str = "sector & theme ETFs",
    run_date: Optional[str] = None,
) -> None:
    html = build_html_report(results, universe_label=universe_label, run_date=run_date)
    Path(path).write_text(html)
