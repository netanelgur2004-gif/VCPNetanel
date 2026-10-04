"""Render Double-Sweep Base scan results into a self-contained HTML report.

Mirrors report.py's token-based templating (plain str.replace, not
.format(), since the template's CSS/JS is full of literal `{...}` braces)
but with its own template and data shape -- this stays a separate module
so it has zero effect on the main VCP dashboard.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import List, Optional

from .double_sweep import DoubleSweepResult

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "double_sweep_report_template.html"


def _result_to_row(r: DoubleSweepResult) -> dict:
    return {
        "t": r.ticker,
        "s": r.score,
        "bd": round(r.base.depth_pct, 1) if r.base else None,
        "hsd": r.high_sweep.date.date().isoformat() if r.high_sweep else None,
        "hsl": round(r.high_sweep.level, 2) if r.high_sweep else None,
        "lsd": r.low_sweep.date.date().isoformat() if r.low_sweep else None,
        "lsl": round(r.low_sweep.level, 2) if r.low_sweep else None,
        "nc": len(r.contraction.legs_pct) if r.contraction else None,
        "fc": round(r.contraction.final_contraction_pct, 1) if r.contraction and r.contraction.final_contraction_pct is not None else None,
        "vd": round(r.contraction.volume_dryup_ratio, 2) if r.contraction and r.contraction.volume_dryup_ratio is not None else None,
        "px": round(r.last_close, 2),
        "pv": round(r.pivot_price, 2) if r.pivot_price is not None else None,
        "d": round(r.distance_to_pivot_pct, 1) if r.distance_to_pivot_pct is not None else None,
        "sl": round(r.stop_price, 2) if r.stop_price is not None else None,
    }


def build_html_report(
    results: List[DoubleSweepResult],
    universe_size: int,
    universe_label: str = "S&P 500 constituents",
    run_date: Optional[str] = None,
    filter_note: Optional[str] = None,
    total_scanned: Optional[int] = None,
) -> str:
    """Render matched Double-Sweep Base results into the HTML dashboard.

    `results` should already be filtered to `matched=True` and sorted by
    score (descending) -- `total_scanned` is the larger count that were
    actually analyzed before filtering, for the "X of Y" header line.
    """
    rows = [_result_to_row(r) for r in results]
    html = _TEMPLATE_PATH.read_text()
    replacements = {
        "__UNIVERSE_LABEL__": universe_label,
        "__RUN_DATE__": run_date or _dt.date.today().isoformat(),
        "__SHOWN__": str(len(results)),
        "__TOTAL_SCANNED__": str(total_scanned if total_scanned is not None else len(results)),
        "__UNIVERSE_SIZE__": str(universe_size),
        "__DATA_JSON__": json.dumps(rows),
        "__FILTER_NOTE__": filter_note or "",
    }
    for token, value in replacements.items():
        html = html.replace(token, value)
    return html


def write_html_report(
    results: List[DoubleSweepResult],
    path: str,
    universe_size: int,
    universe_label: str = "S&P 500 constituents",
    run_date: Optional[str] = None,
    filter_note: Optional[str] = None,
    total_scanned: Optional[int] = None,
) -> None:
    html = build_html_report(
        results,
        universe_size,
        universe_label=universe_label,
        run_date=run_date,
        filter_note=filter_note,
        total_scanned=total_scanned,
    )
    Path(path).write_text(html)
