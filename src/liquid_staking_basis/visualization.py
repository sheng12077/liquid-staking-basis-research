from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import matplotlib
import polars as pl

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

COLORS = {
    "p1": "#D55E00",
    "p2": "#0072B2",
    "x4": "#D55E00",
    "x5": "#0072B2",
    "grid": "#D7D7D7",
    "text": "#202020",
    "warning": "#E69F00",
    "critical": "#B2182B",
}

SINGLE_COLUMN_WIDTH_IN = 3.45
DOUBLE_COLUMN_WIDTH_IN = 7.10


def normalized_nav(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.height < 2 or "nav" not in frame.columns:
        raise ValueError("NAV frame must contain at least two rows")
    initial = float(frame["nav"][0])
    if initial <= 0:
        raise ValueError("initial NAV must be positive")
    return frame.select("timestamp", (pl.col("nav") / initial * 100.0).alias("normalized_nav"))


def drawdown(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.height < 2 or "nav" not in frame.columns:
        raise ValueError("NAV frame must contain at least two rows")
    return frame.select(
        "timestamp",
        (pl.col("nav") / pl.col("nav").cum_max() - 1.0).alias("drawdown"),
    )


def effective_buffer(frame: pl.DataFrame, breach_timestamp: str | None = None) -> pl.DataFrame:
    required = {
        "timestamp",
        "short_quantity_eth",
        "operational_buffer",
        "risk_operational_buffer",
    }
    if not required.issubset(frame.columns):
        raise ValueError("hourly frame is missing margin-buffer columns")
    result = (
        frame.filter(pl.col("short_quantity_eth") > 0)
        .with_columns(
            pl.min_horizontal("operational_buffer", "risk_operational_buffer").alias("buffer")
        )
        .select("timestamp", "buffer")
        .drop_nulls()
    )
    if breach_timestamp is not None:
        breach = datetime.fromisoformat(breach_timestamp)
        result = result.filter(pl.col("timestamp") <= breach)
    return (
        result.with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by("date")
        .agg(pl.col("buffer").min())
        .sort("date")
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return cast(dict[str, Any], value)


def _primary_nav(data_root: Path, experiment: str) -> pl.DataFrame:
    return pl.read_parquet(
        data_root / "derived" / "liquid_staking_basis" / experiment / "primary_daily.parquet",
        columns=["timestamp", "nav"],
    ).sort("timestamp")


def _hourly(data_root: Path, experiment: str, path_name: str) -> pl.DataFrame:
    return pl.read_parquet(
        data_root / "derived" / "liquid_staking_basis" / experiment / f"{path_name}_hourly.parquet"
    ).sort("timestamp")


def _summary(data_root: Path, experiment: str) -> dict[str, Any]:
    return _load_json(data_root / "derived" / "liquid_staking_basis" / experiment / "summary.json")


def _style_axis(axis: Any) -> None:
    axis.grid(True, axis="y")
    axis.tick_params(which="both", top=False, right=False)
    axis.margins(x=0.025)


def _add_panel_labels(axes: Any, x: float = -0.11, y: float = 1.04) -> None:
    for index, axis in enumerate(axes):
        axis.text(
            x,
            y,
            f"({chr(97 + index)})",
            transform=axis.transAxes,
            ha="left",
            va="bottom",
            fontsize=9.5,
            fontweight="bold",
            color=COLORS["text"],
        )


def _save_svg(figure: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        path,
        format="svg",
        bbox_inches="tight",
        metadata={"Date": None, "Creator": "liquid-staking-basis-research"},
    )
    plt.close(figure)


def plot_normalized_nav(data_root: Path, output: Path) -> None:
    p1 = normalized_nav(_primary_nav(data_root, "experiment_001"))
    p2 = normalized_nav(_primary_nav(data_root, "experiment_002"))
    figure, axis = plt.subplots(figsize=(DOUBLE_COLUMN_WIDTH_IN, 3.35))
    axis.plot(
        p1["timestamp"],
        p1["normalized_nav"],
        color=COLORS["p1"],
        linewidth=1.45,
        linestyle="--",
        label="P1 (40/60)",
    )
    axis.plot(
        p2["timestamp"],
        p2["normalized_nav"],
        color=COLORS["p2"],
        linewidth=1.55,
        label="P2 (25/75)",
    )
    axis.axhline(100.0, color=COLORS["text"], linewidth=0.75, alpha=0.55)
    axis.set_title("Normalized strategy net asset value", loc="left", pad=8)
    axis.set_ylabel("Index (initial capital = 100)")
    axis.xaxis.set_major_locator(mdates.YearLocator())
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axis.legend(frameon=False, loc="upper left", ncol=2)
    _style_axis(axis)
    figure.text(
        0.125,
        0.01,
        "Historical backtest after registered costs. P1 earns more but fails margin stresses; "
        "P2 is the supported isolated allocation.",
        fontsize=7.2,
        color=COLORS["text"],
    )
    _save_svg(figure, output)


def plot_margin_buffers(data_root: Path, output: Path) -> None:
    p1_summary = _summary(data_root, "experiment_001")
    p2_summary = _summary(data_root, "experiment_002")
    figure, axes = plt.subplots(2, 1, figsize=(DOUBLE_COLUMN_WIDTH_IN, 5.15), sharex=True)
    paths = (
        ("X4_margin_mark_1.2x", "X4 adverse mark", COLORS["x4"]),
        ("X5_positive_funding_half", "X5 funding haircut", COLORS["x5"]),
    )
    for path_name, label, color in paths:
        p1 = effective_buffer(
            _hourly(data_root, "experiment_001", path_name),
            p1_summary["paths"][path_name]["breach_timestamp"],
        )
        p2 = effective_buffer(
            _hourly(data_root, "experiment_002", path_name),
            p2_summary["paths"][path_name]["breach_timestamp"],
        )
        axes[0].plot(
            p1["date"],
            p1["buffer"] * 100.0,
            color=color,
            linewidth=1.35,
            label=label,
        )
        if p1_summary["paths"][path_name]["breach_timestamp"] is not None:
            axes[0].scatter(
                p1["date"][-1],
                p1["buffer"][-1] * 100.0,
                color=color,
                marker="X",
                s=30,
                zorder=4,
            )
            axes[0].annotate(
                "breach",
                (p1["date"][-1], p1["buffer"][-1] * 100.0),
                xytext=(5, 7),
                textcoords="offset points",
                fontsize=7.2,
                color=color,
            )
        axes[1].plot(
            p2["date"],
            p2["buffer"] * 100.0,
            color=color,
            linewidth=1.35,
            label=label,
        )
    axes[0].axhline(0.0, color=COLORS["critical"], linewidth=1.1, linestyle="--")
    axes[0].set_title("P1: 40% long / 60% isolated collateral", loc="left")
    axes[1].axhline(
        25.0, color=COLORS["warning"], linewidth=1.0, linestyle="--", label="25% warning"
    )
    axes[1].axhline(10.0, color=COLORS["critical"], linewidth=0.9, linestyle=":")
    axes[1].set_title("P2: 25% long / 75% isolated collateral", loc="left")
    _add_panel_labels(axes)
    for axis in axes:
        axis.set_ylabel("Operational buffer (%)")
        axis.legend(loc="upper right", ncol=3, fontsize=7.5)
        _style_axis(axis)
    axes[1].xaxis.set_major_locator(mdates.YearLocator())
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    figure.suptitle(
        "Isolated margin stress: redesign removes registered breaches",
        x=0.125,
        ha="left",
        fontsize=10.0,
        fontweight="bold",
        color=COLORS["text"],
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.95))
    figure.text(
        0.125,
        0.01,
        "Daily minimum of hourly close and adverse-risk buffers. P1 paths stop at breach; "
        "P2 never enters warning or critical state.",
        fontsize=7.2,
        color=COLORS["text"],
    )
    _save_svg(figure, output)


def plot_p2_drawdown(data_root: Path, output: Path) -> None:
    frame = drawdown(_primary_nav(data_root, "experiment_002"))
    figure, axis = plt.subplots(figsize=(DOUBLE_COLUMN_WIDTH_IN, 3.15))
    values = [float(value) * 100.0 for value in frame["drawdown"].to_list()]
    axis.fill_between(frame["timestamp"], values, 0.0, color=COLORS["p2"], alpha=0.25)
    axis.plot(frame["timestamp"], values, color=COLORS["p2"], linewidth=1.4)
    axis.set_title("P2 drawdown path", loc="left", pad=8)
    axis.set_ylabel("Drawdown (%)")
    axis.xaxis.set_major_locator(mdates.YearLocator())
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    _style_axis(axis)
    figure.text(
        0.125,
        0.01,
        "Maximum drawdown: −1.74%. Historical simulation; not live or blind out-of-sample.",
        fontsize=7.2,
        color=COLORS["text"],
    )
    _save_svg(figure, output)


def generate_figures(data_root: Path, output_dir: Path) -> dict[str, str]:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": [
                "Times New Roman",
                "Times",
                "Nimbus Roman",
                "Liberation Serif",
                "DejaVu Serif",
            ],
            "mathtext.fontset": "stix",
            "font.size": 9,
            "axes.titlesize": 9.5,
            "axes.titleweight": "bold",
            "axes.labelsize": 9,
            "axes.edgecolor": "#303030",
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.axisbelow": True,
            "xtick.labelsize": 8.2,
            "ytick.labelsize": 8.2,
            "legend.fontsize": 8.2,
            "legend.frameon": False,
            "legend.handlelength": 2.4,
            "lines.linewidth": 1.55,
            "lines.markersize": 5.0,
            "grid.color": COLORS["grid"],
            "grid.linestyle": (0, (2, 2)),
            "grid.linewidth": 0.55,
            "grid.alpha": 0.8,
            "axes.facecolor": "white",
            "figure.facecolor": "white",
            "figure.dpi": 120,
            "savefig.dpi": 300,
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.04,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "svg.hashsalt": "liquid-staking-basis-research",
        }
    )
    paths = {
        "normalized_nav": output_dir / "normalized_nav.svg",
        "margin_buffer_stress": output_dir / "margin_buffer_stress.svg",
        "p2_drawdown": output_dir / "p2_drawdown.svg",
    }
    plot_normalized_nav(data_root, paths["normalized_nav"])
    plot_margin_buffers(data_root, paths["margin_buffer_stress"])
    plot_p2_drawdown(data_root, paths["p2_drawdown"])
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic GitHub research figures")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("docs/assets"))
    args = parser.parse_args()
    print(json.dumps(generate_figures(args.data_root, args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
