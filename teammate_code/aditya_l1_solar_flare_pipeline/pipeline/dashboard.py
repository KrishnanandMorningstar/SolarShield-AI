"""
dashboard.py
============
Generates the interactive visualization required by the brief's third
expected outcome: "Interface that visualizes the X-ray light curves and
triggers with visual alerts when a flare is nowcasted or forecasted."

Produces a single self-contained HTML file (Plotly, no server needed)
showing:
  - Top panel: SoLEXS soft X-ray flux (log scale, GOES-style)
  - Middle panel: HEL1OS hard X-ray count rate
  - Bottom panel: forecaster's predicted flare probability over time
  - Shaded vertical bands for nowcasted (detected) flare events, colored
    by confidence (confirmed / sxr_only / hxr_only)
  - Markers for forecast alerts that crossed the probability threshold
  - Hover tooltips with flare class, peak values, lead time

Run standalone: `python dashboard.py` regenerates the full pipeline output
and writes outputs/dashboard.html
"""

import html
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import config


# Console/instrument-panel palette: dark background, desaturated grid,
# distinct alert colors that read clearly against dark - this is an
# operations tool (akin to a mission-control console), not a marketing page.
COLORS = {
    "bg": "#0b0e14",
    "panel_bg": "#11151c",
    "grid": "#232a36",
    "text": "#c8d0dc",
    "muted_text": "#7a8494",
    "sxr_line": "#5ec8f2",      # cool cyan - soft X-ray
    "hxr_line": "#f2945e",      # warm orange - hard X-ray
    "proba_line": "#9b6ef2",    # violet - model probability
    "confirmed": "rgba(242, 94, 94, 0.28)",   # red band - high confidence flare
    "sxr_only": "rgba(94, 200, 242, 0.18)",   # cyan band - medium confidence
    "hxr_only": "rgba(242, 148, 94, 0.14)",   # orange band - low confidence
    "alert_marker": "#f23e6e",
    "threshold_line": "#5a6275",
}

CLASS_COLOR = {"A": "#7a8494", "B": "#5ec8f2", "C": "#f2d35e", "M": "#f2945e", "X": "#f23e6e"}


def _flare_class_letter(class_str):
    if pd.isna(class_str) or not isinstance(class_str, str) or len(class_str) == 0:
        return "?"
    c = class_str[0]
    return c if c in CLASS_COLOR else "?"


def _downsample_for_display(feat: pd.DataFrame, max_points=20000) -> pd.DataFrame:
    """
    Browser-side line charts become sluggish/huge (tens of MB of embedded
    JSON) past a few tens of thousands of points. For DISPLAY purposes we
    downsample by taking a max-aggregate over fixed-size bins, which
    preserves flare peaks (the most important visual feature) rather than
    averaging them away the way a naive mean-resample would.
    All quantitative analysis (detection, forecasting) still runs on the
    FULL-resolution data elsewhere in the pipeline - this function is
    purely for keeping the HTML dashboard file size and render time sane.
    """
    n = len(feat)
    if n <= max_points:
        return feat
    bin_size = int(np.ceil(n / max_points))
    grouped = feat.groupby(np.arange(n) // bin_size)
    agg = grouped.agg({
        config.TIME_COL: "first",
        config.SXR_COL: "max",
        config.HXR_COL: "max",
    }).reset_index(drop=True)
    return agg


def _fmt_time(value) -> str:
    if pd.isna(value):
        return "-"
    return pd.to_datetime(value, utc=True).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_float(value, precision=2) -> str:
    if pd.isna(value):
        return "-"
    return f"{float(value):.{precision}f}"


def _fmt_sci(value) -> str:
    if pd.isna(value):
        return "-"
    return f"{float(value):.2e}"


def _forecast_alert_summary(forecast_times, forecast_proba):
    if forecast_times is None or forecast_proba is None or len(forecast_proba) == 0:
        return {
            "active": False,
            "latest_probability": None,
            "peak_probability": None,
            "alert_episodes": 0,
            "last_alert_time": None,
        }

    times = pd.to_datetime(pd.Series(forecast_times), utc=True).reset_index(drop=True)
    proba = pd.Series(forecast_proba).reset_index(drop=True)
    above = proba >= config.ALERT_PROBABILITY_THRESHOLD
    episodes = int((above & ~above.shift(fill_value=False)).sum())
    return {
        "active": bool(above.iloc[-1]),
        "latest_probability": float(proba.iloc[-1]),
        "peak_probability": float(proba.max()),
        "alert_episodes": episodes,
        "last_alert_time": times[above].iloc[-1] if above.any() else None,
    }


def _status_counts(master_catalogue: pd.DataFrame) -> dict:
    if master_catalogue is None or len(master_catalogue) == 0:
        return {"confirmed": 0, "sxr_only": 0, "hxr_only": 0}
    counts = master_catalogue["status"].value_counts().to_dict()
    return {key: int(counts.get(key, 0)) for key in ["confirmed", "sxr_only", "hxr_only"]}


def _render_event_table(master_catalogue: pd.DataFrame, limit=18) -> str:
    if master_catalogue is None or len(master_catalogue) == 0:
        return "<p class='empty-state'>No nowcasted events were detected in this run.</p>"

    rows = []
    table = master_catalogue.copy()
    table["onset_time"] = pd.to_datetime(table["onset_time"], utc=True)
    table = table.sort_values("onset_time", ascending=False).head(limit)
    for _, ev in table.iterrows():
        status = html.escape(str(ev.get("status", "-")))
        cls = html.escape(str(ev.get("flare_class", "-")))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(ev.get('event_id', '-')))}</td>"
            f"<td><span class='status-pill status-{status}'>{status.replace('_', ' ')}</span></td>"
            f"<td>{cls}</td>"
            f"<td>{_fmt_time(ev.get('onset_time'))}</td>"
            f"<td>{_fmt_sci(ev.get('peak_sxr_flux_w_m2'))}</td>"
            f"<td>{_fmt_float(ev.get('peak_hxr_counts_s'), 1)}</td>"
            f"<td>{_fmt_float(ev.get('hxr_leads_sxr_minutes'), 1)}</td>"
            "</tr>"
        )

    return (
        "<div class='table-wrap'>"
        "<table>"
        "<thead><tr>"
        "<th>ID</th><th>Status</th><th>Class</th><th>Onset</th>"
        "<th>Peak SXR W/m^2</th><th>Peak HXR counts/s</th><th>HXR Lead min</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
    )


def _write_frontend_html(
    fig,
    feat: pd.DataFrame,
    master_catalogue: pd.DataFrame,
    forecast_times,
    forecast_proba,
    save_path,
):
    counts = _status_counts(master_catalogue)
    alert = _forecast_alert_summary(forecast_times, forecast_proba)
    start_time = _fmt_time(feat[config.TIME_COL].iloc[0])
    end_time = _fmt_time(feat[config.TIME_COL].iloc[-1])
    duration_days = (pd.to_datetime(feat[config.TIME_COL].iloc[-1]) - pd.to_datetime(feat[config.TIME_COL].iloc[0])).total_seconds() / 86400
    total_events = len(master_catalogue) if master_catalogue is not None else 0
    latest_probability = "-" if alert["latest_probability"] is None else f"{alert['latest_probability']:.2f}"
    peak_probability = "-" if alert["peak_probability"] is None else f"{alert['peak_probability']:.2f}"
    alert_state = "ACTIVE" if alert["active"] else "Nominal"
    alert_class = "alert-active" if alert["active"] else "alert-nominal"
    plot_html = fig.to_html(
        full_html=False,
        include_plotlyjs=True,
        config={"responsive": True, "displaylogo": False},
    )
    event_table = _render_event_table(master_catalogue)

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Aditya-L1 Solar Flare Console</title>
  <style>
    :root {{
      --bg: #090b10;
      --surface: #11151c;
      --surface-2: #171c25;
      --line: #283142;
      --text: #e6edf7;
      --muted: #8e99aa;
      --cyan: #5ec8f2;
      --orange: #f2945e;
      --red: #f25e5e;
      --yellow: #f2d35e;
      --violet: #9b6ef2;
      --green: #72d391;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }}
    .app-shell {{ min-height: 100vh; }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-start;
      padding: 24px 28px;
      border-bottom: 1px solid var(--line);
      background: #0d1118;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      line-height: 1.1;
      font-weight: 720;
    }}
    .subtitle {{
      margin: 0;
      color: var(--muted);
      max-width: 880px;
      line-height: 1.45;
    }}
    .run-window {{
      text-align: right;
      color: var(--muted);
      min-width: 260px;
      line-height: 1.45;
      font-size: 13px;
    }}
    .content {{
      width: min(1500px, calc(100% - 32px));
      margin: 0 auto;
      padding: 20px 0 32px;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .kpi {{
      min-height: 104px;
      padding: 14px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .kpi-label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    .kpi-value {{
      margin-top: 10px;
      font-size: 28px;
      line-height: 1;
      font-weight: 720;
    }}
    .kpi-note {{
      margin-top: 9px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }}
    .alert-active .kpi-value {{ color: var(--red); }}
    .alert-nominal .kpi-value {{ color: var(--green); }}
    .confirmed-color {{ color: var(--red); }}
    .sxr-color {{ color: var(--cyan); }}
    .hxr-color {{ color: var(--orange); }}
    .main-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 16px;
      align-items: start;
    }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .panel-header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--surface-2);
    }}
    .panel-header h2 {{
      margin: 0;
      font-size: 15px;
      line-height: 1.2;
    }}
    .panel-header span {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }}
    .chart-wrap {{ min-height: 850px; }}
    .side-stack {{
      display: grid;
      gap: 16px;
    }}
    .method-list {{
      margin: 0;
      padding: 14px 16px 16px;
      list-style: none;
      display: grid;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.42;
    }}
    .method-list strong {{
      display: block;
      color: var(--text);
      margin-bottom: 2px;
      font-size: 13px;
    }}
    .legend {{
      display: grid;
      gap: 10px;
      padding: 14px 16px 16px;
      color: var(--muted);
      font-size: 13px;
    }}
    .legend-row {{
      display: flex;
      align-items: center;
      gap: 9px;
    }}
    .swatch {{
      width: 12px;
      height: 12px;
      border-radius: 3px;
      display: inline-block;
    }}
    .event-panel {{ margin-top: 16px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      white-space: nowrap;
    }}
    th {{
      color: var(--muted);
      font-weight: 620;
      background: #10141b;
    }}
    .status-pill {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 3px 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      color: var(--text);
      font-size: 12px;
      text-transform: capitalize;
    }}
    .status-confirmed {{ border-color: rgba(242,94,94,.5); color: #ff9b9b; }}
    .status-sxr_only {{ border-color: rgba(94,200,242,.5); color: #9de2ff; }}
    .status-hxr_only {{ border-color: rgba(242,148,94,.5); color: #ffc19b; }}
    .empty-state {{ margin: 0; padding: 16px; color: var(--muted); }}
    @media (max-width: 1100px) {{
      .kpi-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .main-grid {{ grid-template-columns: 1fr; }}
      .run-window {{ text-align: left; }}
      .topbar {{ flex-direction: column; }}
    }}
    @media (max-width: 720px) {{
      .content {{ width: min(100% - 20px, 1500px); }}
      .topbar {{ padding: 20px 14px; }}
      .kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      h1 {{ font-size: 23px; }}
      .kpi-value {{ font-size: 23px; }}
      .chart-wrap {{ min-height: 760px; }}
    }}
  </style>
</head>
<body>
  <main class="app-shell">
    <header class="topbar">
      <div>
        <h1>Aditya-L1 Solar Flare Console</h1>
        <p class="subtitle">Combined SoLEXS soft X-ray and HEL1OS hard X-ray nowcasting and forecasting interface. The chart links both light curves with detected flare bands and forecast alert crossings.</p>
      </div>
      <div class="run-window">
        <div><strong>Data window</strong></div>
        <div>{start_time}</div>
        <div>{end_time}</div>
      </div>
    </header>

    <section class="content">
      <div class="kpi-grid" aria-label="Pipeline summary">
        <article class="kpi">
          <div class="kpi-label">Nowcasted Events</div>
          <div class="kpi-value">{total_events}</div>
          <div class="kpi-note">{duration_days:.1f} days at {config.RESAMPLE_CADENCE_S}s cadence</div>
        </article>
        <article class="kpi">
          <div class="kpi-label">Confirmed</div>
          <div class="kpi-value confirmed-color">{counts['confirmed']}</div>
          <div class="kpi-note">SXR and HXR coincidence</div>
        </article>
        <article class="kpi">
          <div class="kpi-label">SXR Only</div>
          <div class="kpi-value sxr-color">{counts['sxr_only']}</div>
          <div class="kpi-note">Thermal flare signature</div>
        </article>
        <article class="kpi">
          <div class="kpi-label">HXR Only</div>
          <div class="kpi-value hxr-color">{counts['hxr_only']}</div>
          <div class="kpi-note">Impulsive or review-needed burst</div>
        </article>
        <article class="kpi {alert_class}">
          <div class="kpi-label">Forecast State</div>
          <div class="kpi-value">{alert_state}</div>
          <div class="kpi-note">Latest probability {latest_probability}</div>
        </article>
        <article class="kpi">
          <div class="kpi-label">Alert Episodes</div>
          <div class="kpi-value">{alert['alert_episodes']}</div>
          <div class="kpi-note">Peak probability {peak_probability}</div>
        </article>
      </div>

      <div class="main-grid">
        <section class="panel">
          <div class="panel-header">
            <h2>Light Curves and Alert Timeline</h2>
            <span>Vertical bands are nowcasted flare events. X markers are forecast threshold crossings.</span>
          </div>
          <div class="chart-wrap">{plot_html}</div>
        </section>

        <aside class="side-stack">
          <section class="panel">
            <div class="panel-header"><h2>Signal Legend</h2></div>
            <div class="legend">
              <div class="legend-row"><span class="swatch" style="background: var(--cyan)"></span> SoLEXS soft X-ray flux</div>
              <div class="legend-row"><span class="swatch" style="background: var(--orange)"></span> HEL1OS hard X-ray count rate</div>
              <div class="legend-row"><span class="swatch" style="background: var(--violet)"></span> Forecast probability</div>
              <div class="legend-row"><span class="swatch" style="background: rgba(242,94,94,.55)"></span> Confirmed nowcast</div>
              <div class="legend-row"><span class="swatch" style="background: rgba(94,200,242,.55)"></span> SXR-only nowcast</div>
              <div class="legend-row"><span class="swatch" style="background: rgba(242,148,94,.55)"></span> HXR-only nowcast</div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-header"><h2>Pipeline Logic</h2></div>
            <ul class="method-list">
              <li><strong>Preprocess</strong>Estimate rolling quiet-Sun background, smooth both channels, and derive excess flux, ratios, slopes, and volatility.</li>
              <li><strong>Nowcast</strong>Run independent SXR ratio and HXR sigma detectors, then match peaks within {config.COINCIDENCE_WINDOW_MIN} minutes into a master catalogue.</li>
              <li><strong>Forecast</strong>Use {config.LOOKBACK_WINDOW_MIN}-minute combined-channel feature windows to estimate flare probability over the next {config.FORECAST_HORIZON_MIN} minutes.</li>
              <li><strong>Alert</strong>Trigger when probability crosses {config.ALERT_PROBABILITY_THRESHOLD:.2f}; lead time is measured from first valid alert to flare onset.</li>
            </ul>
          </section>
        </aside>
      </div>

      <section class="panel event-panel">
        <div class="panel-header">
          <h2>Automated Nowcast Catalogue</h2>
          <span>Most recent events from outputs/nowcast_master_catalogue.csv</span>
        </div>
        {event_table}
      </section>
    </section>
  </main>
</body>
</html>
"""
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(page)


def build_dashboard(
    feat: pd.DataFrame,
    master_catalogue: pd.DataFrame,
    forecast_times: pd.Series = None,
    forecast_proba: np.ndarray = None,
    title: str = "Aditya-L1 Solar Flare Nowcasting & Forecasting Dashboard",
    save_path=None,
    max_display_points: int = 20000,
):
    """
    feat: output of preprocessing.build_feature_frame
    master_catalogue: output of nowcasting.build_master_catalogue
    forecast_times / forecast_proba: optional, aligned arrays from the
        forecasting model (e.g. results["splits"]["test"][2] and
        results["test_proba"]) to overlay predicted-probability + alerts.
        If omitted, the dashboard shows nowcasting only.
    max_display_points: downsample the light curve to roughly this many
        points for rendering performance (see _downsample_for_display).
    """
    has_forecast = forecast_times is not None and forecast_proba is not None
    n_rows = 3 if has_forecast else 2
    row_heights = [0.4, 0.4, 0.2] if has_forecast else [0.5, 0.5]

    display_feat = _downsample_for_display(feat, max_points=max_display_points)

    fig = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=row_heights,
        subplot_titles=(
            ["SoLEXS Soft X-ray Flux (W/m\u00b2, GOES-equivalent)",
             "HEL1OS Hard X-ray Count Rate (counts/s)"]
            + (["Forecaster: P(flare in next %d min)" % config.FORECAST_HORIZON_MIN] if has_forecast else [])
        ),
    )

    # ---------------------------------------------------------------
    # Row 1: SXR light curve
    # ---------------------------------------------------------------
    fig.add_trace(
        go.Scattergl(
            x=display_feat[config.TIME_COL], y=display_feat[config.SXR_COL],
            mode="lines", name="SoLEXS (SXR)",
            line=dict(color=COLORS["sxr_line"], width=1),
            hovertemplate="%{x}<br>SXR: %{y:.2e} W/m\u00b2<extra></extra>",
        ),
        row=1, col=1,
    )
    fig.update_yaxes(type="log", title_text="W/m\u00b2", row=1, col=1,
                      gridcolor=COLORS["grid"], color=COLORS["text"])

    # GOES class threshold reference lines
    for cls, thresh in config.FLARE_CLASS_THRESHOLDS.items():
        fig.add_hline(
            y=thresh, row=1, col=1,
            line=dict(color=CLASS_COLOR[cls], width=0.6, dash="dot"),
            annotation_text=cls, annotation_position="right",
            annotation_font=dict(color=CLASS_COLOR[cls], size=10),
        )

    # ---------------------------------------------------------------
    # Row 2: HXR light curve
    # ---------------------------------------------------------------
    fig.add_trace(
        go.Scattergl(
            x=display_feat[config.TIME_COL], y=display_feat[config.HXR_COL],
            mode="lines", name="HEL1OS (HXR)",
            line=dict(color=COLORS["hxr_line"], width=1),
            hovertemplate="%{x}<br>HXR: %{y:.1f} counts/s<extra></extra>",
        ),
        row=2, col=1,
    )
    fig.update_yaxes(type="log", title_text="counts/s", row=2, col=1,
                      gridcolor=COLORS["grid"], color=COLORS["text"])

    # ---------------------------------------------------------------
    # Nowcast event shading (both rows) + hover markers with details
    # ---------------------------------------------------------------
    band_color_map = {"confirmed": COLORS["confirmed"], "sxr_only": COLORS["sxr_only"], "hxr_only": COLORS["hxr_only"]}
    legend_shown = set()
    for _, ev in master_catalogue.iterrows():
        status = ev["status"]
        color = band_color_map.get(status, "rgba(150,150,150,0.15)")
        onset = pd.to_datetime(ev["onset_time"]) if pd.notna(ev["onset_time"]) else pd.to_datetime(ev["peak_time_hxr"])
        end = pd.to_datetime(ev["end_time"]) if pd.notna(ev["end_time"]) else onset + pd.Timedelta(minutes=10)
        for r in [1, 2]:
            fig.add_vrect(
                x0=onset, x1=end, row=r, col=1,
                fillcolor=color, line_width=0, layer="below",
            )
        # one annotation marker per event on row 1, at peak
        peak_t = ev["peak_time_sxr"] if pd.notna(ev.get("peak_time_sxr")) else onset
        cls_letter = _flare_class_letter(ev.get("flare_class"))
        showlegend = status not in legend_shown
        legend_shown.add(status)
        fig.add_trace(
            go.Scatter(
                x=[peak_t], y=[feat[config.SXR_COL].max() * 1.3],
                mode="markers",
                marker=dict(symbol="triangle-down", size=9,
                            color=CLASS_COLOR.get(cls_letter, "#888")),
                name=f"Nowcast: {status}",
                legendgroup=status,
                showlegend=showlegend,
                hovertemplate=(
                    f"Event: {ev['event_id']}<br>Status: {status}<br>"
                    f"Class: {ev.get('flare_class','?')}<br>"
                    f"Onset: {onset}<br>"
                    f"HXR leads SXR by: {ev.get('hxr_leads_sxr_minutes', 'n/a')} min"
                    "<extra></extra>"
                ),
            ),
            row=1, col=1,
        )

    # ---------------------------------------------------------------
    # Row 3: forecast probability + alert threshold + alert markers
    # ---------------------------------------------------------------
    if has_forecast:
        times_full = pd.to_datetime(pd.Series(forecast_times)).reset_index(drop=True)
        proba_full = pd.Series(forecast_proba).reset_index(drop=True)

        if len(times_full) > max_display_points:
            bin_size = int(np.ceil(len(times_full) / max_display_points))
            idx_groups = np.arange(len(times_full)) // bin_size
            # use max probability per bin so brief alert spikes aren't averaged away
            times = times_full.groupby(idx_groups).first().reset_index(drop=True)
            proba = proba_full.groupby(idx_groups).max().reset_index(drop=True)
        else:
            times, proba = times_full, proba_full

        fig.add_trace(
            go.Scatter(
                x=times, y=proba, mode="lines", name="Forecast probability",
                line=dict(color=COLORS["proba_line"], width=1.4),
                fill="tozeroy", fillcolor="rgba(155,110,242,0.12)",
                hovertemplate="%{x}<br>P(flare): %{y:.2f}<extra></extra>",
            ),
            row=3, col=1,
        )
        fig.add_hline(
            y=config.ALERT_PROBABILITY_THRESHOLD, row=3, col=1,
            line=dict(color=COLORS["threshold_line"], width=1, dash="dash"),
            annotation_text=f"alert threshold ({config.ALERT_PROBABILITY_THRESHOLD})",
            annotation_font=dict(color=COLORS["threshold_line"], size=10),
        )
        alert_mask = proba_full >= config.ALERT_PROBABILITY_THRESHOLD
        if alert_mask.any():
            fig.add_trace(
                go.Scatter(
                    x=times_full[alert_mask], y=proba_full[alert_mask], mode="markers",
                    name="Forecast ALERT",
                    marker=dict(symbol="x", size=6, color=COLORS["alert_marker"]),
                    hovertemplate="ALERT FIRED<br>%{x}<br>P=%{y:.2f}<extra></extra>",
                ),
                row=3, col=1,
            )
        fig.update_yaxes(title_text="Probability", range=[0, 1], row=3, col=1,
                          gridcolor=COLORS["grid"], color=COLORS["text"])

    # ---------------------------------------------------------------
    # Global layout
    # ---------------------------------------------------------------
    fig.update_layout(
        title=dict(text=title, font=dict(color=COLORS["text"], size=18, family="Consolas, Menlo, monospace")),
        plot_bgcolor=COLORS["panel_bg"],
        paper_bgcolor=COLORS["bg"],
        font=dict(color=COLORS["text"], family="Consolas, Menlo, monospace", size=11),
        legend=dict(bgcolor=COLORS["panel_bg"], bordercolor=COLORS["grid"], borderwidth=1,
                    orientation="h", y=-0.08),
        height=850 if has_forecast else 650,
        margin=dict(l=60, r=40, t=70, b=40),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor=COLORS["grid"], color=COLORS["text"], row=n_rows, col=1,
                      title_text="Time (UTC)")
    for r in range(1, n_rows + 1):
        fig.update_xaxes(gridcolor=COLORS["grid"], color=COLORS["text"], row=r, col=1)

    if save_path:
        _write_frontend_html(fig, feat, master_catalogue, forecast_times, forecast_proba, save_path)

    return fig


if __name__ == "__main__":
    from teammate_code.aditya_l1_solar_flare_pipeline.pipeline.data_loader import load_light_curve
    from teammate_code.aditya_l1_solar_flare_pipeline.pipeline.preprocessing import build_feature_frame
    from teammate_code.aditya_l1_solar_flare_pipeline.pipeline.nowcasting import run_nowcasting_pipeline
    from teammate_code.aditya_l1_solar_flare_pipeline.pipeline.forecasting import train_forecaster

    df = load_light_curve()
    feat = build_feature_frame(df)
    master, _, _ = run_nowcasting_pipeline(feat, save=True)

    catalogue = pd.read_csv(config.SAMPLE_DIR / "ground_truth_flares.csv")
    results = train_forecaster(feat, catalogue, save=True)
    _, _, t_test = results["splits"]["test"]

    # Slice the light curve to roughly the test period +/- a bit of context,
    # so the dashboard stays responsive (336h of 1Hz data is ~1.2M points -
    # fine for the full nowcast view, but we zoom the default view for usability)
    out_path = config.OUTPUT_DIR / "dashboard.html"
    build_dashboard(
        feat, master,
        forecast_times=t_test, forecast_proba=results["test_proba"],
        save_path=out_path,
    )
    print(f"Dashboard written to {out_path}")
