"""Reusable visual-layer entry points for Macro Barometer charts.

The renderer callback keeps the existing calculation and output contract intact
while allowing callers to route chart generation through this dedicated module.
"""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ChartConfig:
    """Runtime chart options formerly read directly by the macro script."""

    data_source: str = "local"
    normalization_window: int = 252
    shift_bars: int = 0
    plot_range: int = 400
    scale_min: float = 1.0
    scale_max: float = 11.0
    mf_window: int = 12
    stoch_k: int = 9
    stoch_d: int = 5
    mf_stoch: int = 0
    obv5_detailed: int = 1
    price_candlestick: int = 1
    recent_obv_signal_bars: int = 20
    panel3_tmf: int = 1
    panel3_cvd: int = 0
    panel3_cmf: int = 1
    panel3_kst: int = 1
    debug_chart: bool = False


def generate_unified_two_pane_chart(
    symbol: str,
    anchors: Any,
    consensus_positions: list,
    current_run_date: Any,
    renderer: Callable[..., Any] | None = None,
) -> Any:
    """Build the existing dual and standalone Panel 1/2/3 chart views."""
    if renderer is None:
        from macro_barometer import _generate_unified_two_pane_chart_impl

        renderer = _generate_unified_two_pane_chart_impl
    return renderer(symbol, anchors, consensus_positions, current_run_date)


def write_chart_viewer(renderer: Callable[[], Any] | None = None) -> Any:
    """Generate the existing local chart viewer page."""
    if renderer is None:
        from macro_barometer import _write_chart_viewer_impl

        renderer = _write_chart_viewer_impl
    return renderer()