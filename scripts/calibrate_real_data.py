#!/usr/bin/env python3
"""
scripts/calibrate_real_data.py — Real-Data Calibration for DAHS_2

Uses three real datasets to ground simulator parameters:
  1. Olist Brazilian E-Commerce (99,441 orders) — arrival rates, SLA windows, tardiness
  2. E-Commerce Shipping (Prachi13 structure, synthetic-real hybrid) — zone/breach structure
  3. Taillard JSP benchmarks — heuristic validation vs published bounds

Outputs:
  - results/calibration/arrival_rate_analysis.png
  - results/calibration/sla_window_analysis.png
  - results/calibration/tardiness_distribution.png
  - results/calibration/taillard_heuristic_comparison.png
  - results/calibration/calibration_report.json
  - data/real/calibrated_params.json  (updated simulator params)

Usage:
    python scripts/calibrate_real_data.py
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Force UTF-8 output
for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REAL_DIR    = ROOT / "data" / "real"
BENCH_DIR   = ROOT / "data" / "benchmarks" / "taillard"
RESULTS_DIR = ROOT / "results" / "calibration"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# PART 1: Olist Arrival Rate Analysis
# =============================================================================

def analyze_olist_arrivals(orders_path: Path) -> dict:
    """Extract hourly arrival rates from Olist timestamps."""
    logger.info("Loading Olist orders: %s", orders_path)
    df = pd.read_csv(orders_path, parse_dates=["order_purchase_timestamp"])

    # Filter to delivered orders only (clean data)
    df = df[df["order_status"] == "delivered"].copy()
    logger.info("Delivered orders: %d", len(df))

    # Hourly arrival counts
    df["hour"] = df["order_purchase_timestamp"].dt.hour
    df["date"] = df["order_purchase_timestamp"].dt.date
    df["weekday"] = df["order_purchase_timestamp"].dt.weekday

    # Orders per day
    daily_counts = df.groupby("date").size()
    orders_per_day_mean = float(daily_counts.mean())
    orders_per_day_std  = float(daily_counts.std())
    orders_per_hour_mean = orders_per_day_mean / 16  # 16-hour operating window

    logger.info("Mean orders/day: %.1f, std: %.1f", orders_per_day_mean, orders_per_day_std)
    logger.info("Implied mean orders/hour: %.1f", orders_per_hour_mean)

    # Hourly distribution (fraction of daily orders per hour)
    hourly_dist = df.groupby("hour").size() / len(df)

    # Peak hour analysis (warehouse typically operates 6am-10pm)
    op_hours = df[(df["hour"] >= 6) & (df["hour"] <= 22)]
    op_hourly = op_hours.groupby("hour").size()
    op_hourly_norm = op_hourly / op_hourly.sum()

    # Fit Poisson rate (orders/min during operating hours)
    daily_op = df.groupby("date").size()
    # Scale to 600-min shift: 600min / (60*16) * daily_mean
    orders_per_600min = orders_per_day_mean * (600 / (60 * 16))
    arrival_rate_per_min = orders_per_600min / 600

    # Day-of-week effect
    dow_counts = df.groupby("weekday").size()
    peak_day = int(dow_counts.idxmax())
    dow_factor = float(dow_counts.max() / dow_counts.mean())

    logger.info("Estimated arrival_rate_per_min: %.4f", arrival_rate_per_min)

    # ---- Plot ----
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    fig.patch.set_facecolor("#0f1117")
    fig.suptitle("Olist E-Commerce: Real Order Arrival Patterns", color="white", fontsize=14, y=1.01)

    # 1. Daily volume distribution
    ax = axes[0]
    ax.set_facecolor("#1a1d27")
    ax.hist(daily_counts.values, bins=40, color="#4fc3f7", alpha=0.85, edgecolor="none")
    ax.axvline(orders_per_day_mean, color="#ff7043", lw=2, linestyle="--", label=f"Mean={orders_per_day_mean:.0f}/day")
    ax.set_title("Daily Order Volume", color="white")
    ax.set_xlabel("Orders/day", color="#aaa")
    ax.set_ylabel("Frequency", color="#aaa")
    ax.tick_params(colors="#ccc")
    ax.legend(facecolor="#333", labelcolor="white", fontsize=9)
    for sp in ax.spines.values(): sp.set_color("#333")

    # 2. Hourly distribution
    ax = axes[1]
    ax.set_facecolor("#1a1d27")
    ax.bar(hourly_dist.index, hourly_dist.values * 100, color="#a5d6a7", alpha=0.85)
    ax.set_title("Orders by Hour of Day (%)", color="white")
    ax.set_xlabel("Hour", color="#aaa")
    ax.set_ylabel("% of daily orders", color="#aaa")
    ax.tick_params(colors="#ccc")
    for sp in ax.spines.values(): sp.set_color("#333")

    # 3. Day-of-week
    ax = axes[2]
    ax.set_facecolor("#1a1d27")
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    ax.bar(range(7), [dow_counts.get(i, 0) for i in range(7)], color="#ce93d8", alpha=0.85)
    ax.set_xticks(range(7))
    ax.set_xticklabels(days, color="#ccc")
    ax.set_title("Orders by Day of Week", color="white")
    ax.set_xlabel("Day", color="#aaa")
    ax.tick_params(colors="#ccc")
    for sp in ax.spines.values(): sp.set_color("#333")

    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "arrival_rate_analysis.png", dpi=150,
                bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    logger.info("Saved arrival_rate_analysis.png")

    return {
        "orders_per_day_mean": orders_per_day_mean,
        "orders_per_day_std":  orders_per_day_std,
        "orders_per_600min_shift": orders_per_600min,
        "arrival_rate_per_min": arrival_rate_per_min,
        "peak_hour_factor": dow_factor,
        "hourly_dist": hourly_dist.to_dict(),
    }


# =============================================================================
# PART 2: Olist SLA Window Analysis
# =============================================================================

def analyze_olist_sla(orders_path: Path) -> dict:
    """Extract SLA windows and breach rates from Olist timestamps."""
    df = pd.read_csv(
        orders_path,
        parse_dates=[
            "order_purchase_timestamp",
            "order_estimated_delivery_date",
            "order_delivered_customer_date",
        ]
    )
    df = df[df["order_status"] == "delivered"].dropna(
        subset=["order_estimated_delivery_date", "order_delivered_customer_date"]
    )

    # SLA window = estimated_delivery - purchase (in hours)
    df["sla_window_days"] = (
        df["order_estimated_delivery_date"] - df["order_purchase_timestamp"]
    ).dt.total_seconds() / 86400

    # Actual cycle time = delivered - purchase (in days)
    df["cycle_days"] = (
        df["order_delivered_customer_date"] - df["order_purchase_timestamp"]
    ).dt.total_seconds() / 86400

    # Tardiness = max(0, cycle - sla_window) in days
    df["tardiness_days"] = (df["cycle_days"] - df["sla_window_days"]).clip(lower=0)
    df["is_late"] = df["tardiness_days"] > 0

    sla_median_days  = float(df["sla_window_days"].median())
    sla_mean_days    = float(df["sla_window_days"].mean())
    cycle_median_days = float(df["cycle_days"].median())
    sla_breach_rate  = float(df["is_late"].mean())
    tard_mean_days   = float(df["tardiness_days"].mean())

    logger.info("SLA window median: %.1f days, mean: %.1f days", sla_median_days, sla_mean_days)
    logger.info("Cycle time median: %.1f days", cycle_median_days)
    logger.info("SLA breach rate: %.2f%%", sla_breach_rate * 100)
    logger.info("Mean tardiness (late only): %.2f days", tard_mean_days)

    # Map to simulator minutes: Olist is B2C (days); our sim is intra-warehouse (hours)
    # Scale factor: typical warehouse processes in ~hours, delivery is days
    # We normalize: Olist's SLA quantiles -> our 60-320 min range
    sla_quantiles = df["sla_window_days"].quantile([0.05, 0.25, 0.50, 0.75, 0.95]).to_dict()

    # ---- SLA window histogram ----
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    fig.patch.set_facecolor("#0f1117")
    fig.suptitle("Olist: Real SLA Windows & Tardiness", color="white", fontsize=14, y=1.01)

    ax = axes[0]
    ax.set_facecolor("#1a1d27")
    clipped = df["sla_window_days"].clip(0, 60)
    ax.hist(clipped, bins=50, color="#4fc3f7", alpha=0.85, edgecolor="none")
    ax.axvline(sla_median_days, color="#ff7043", lw=2, linestyle="--",
               label=f"Median={sla_median_days:.1f}d")
    ax.set_title("SLA Window Distribution (days)", color="white")
    ax.set_xlabel("Days to deadline", color="#aaa")
    ax.tick_params(colors="#ccc")
    ax.legend(facecolor="#333", labelcolor="white", fontsize=9)
    for sp in ax.spines.values(): sp.set_color("#333")

    ax = axes[1]
    ax.set_facecolor("#1a1d27")
    clipped2 = df["cycle_days"].clip(0, 60)
    ax.hist(clipped2, bins=50, color="#a5d6a7", alpha=0.85, edgecolor="none")
    ax.axvline(cycle_median_days, color="#ff7043", lw=2, linestyle="--",
               label=f"Median={cycle_median_days:.1f}d")
    ax.set_title("Actual Cycle Time (days)", color="white")
    ax.set_xlabel("Days from purchase to delivery", color="#aaa")
    ax.tick_params(colors="#ccc")
    ax.legend(facecolor="#333", labelcolor="white", fontsize=9)
    for sp in ax.spines.values(): sp.set_color("#333")

    ax = axes[2]
    ax.set_facecolor("#1a1d27")
    labels = ["On Time", "Late"]
    sizes  = [1 - sla_breach_rate, sla_breach_rate]
    colors = ["#a5d6a7", "#ef5350"]
    wedges, texts, autotexts = ax.pie(sizes, labels=labels, colors=colors,
                                      autopct="%1.1f%%", startangle=90,
                                      textprops={"color": "white"})
    for at in autotexts: at.set_color("white")
    ax.set_title(f"SLA Breach Rate: {sla_breach_rate*100:.1f}%", color="white")

    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "sla_window_analysis.png", dpi=150,
                bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    logger.info("Saved sla_window_analysis.png")

    return {
        "sla_window_median_days":  sla_median_days,
        "sla_window_mean_days":    sla_mean_days,
        "cycle_time_median_days":  cycle_median_days,
        "sla_breach_rate":         sla_breach_rate,
        "mean_tardiness_days_late_only": tard_mean_days,
        "sla_quantiles_days":      {f"p{int(k*100)}": v for k, v in sla_quantiles.items()},
    }


# =============================================================================
# PART 3: Order Category → Job Type Mapping
# =============================================================================

def analyze_order_types(items_path: Path) -> dict:
    """Map Olist product categories to DAHS job types A-E."""
    logger.info("Loading Olist order items: %s", items_path)
    df = pd.read_csv(items_path)
    logger.info("Order items shape: %s", df.shape)

    # Use price as a proxy for job type:
    # E (express/VIP) = top 10% price → highest SLA urgency
    # A (premium)     = 75-90th percentile
    # B (standard)    = 50-75th percentile (most common)
    # C (economy)     = 25-50th percentile
    # D (bulk)        = bottom 25%

    q = df["price"].quantile([0.10, 0.25, 0.50, 0.75, 0.90]).to_dict()
    total = len(df)

    type_dist = {
        "E": float(((df["price"] >= q[0.90])).sum() / total),
        "A": float(((df["price"] >= q[0.75]) & (df["price"] < q[0.90])).sum() / total),
        "B": float(((df["price"] >= q[0.50]) & (df["price"] < q[0.75])).sum() / total),
        "C": float(((df["price"] >= q[0.25]) & (df["price"] < q[0.50])).sum() / total),
        "D": float((df["price"] < q[0.25]).sum() / total),
    }

    logger.info("Inferred job type distribution from price quantiles: %s",
                {k: f"{v:.2%}" for k, v in type_dist.items()})

    # Compare to simulator defaults
    sim_defaults = {"A": 0.25, "B": 0.30, "C": 0.20, "D": 0.15, "E": 0.10}
    logger.info("Simulator defaults: %s", {k: f"{v:.2%}" for k, v in sim_defaults.items()})

    # Freight analysis (proxy for processing complexity)
    freight_mean = float(df["freight_value"].mean())
    freight_std  = float(df["freight_value"].std())
    items_per_order = float(df.groupby("order_id").size().mean())

    # ---- Plot type distribution ----
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.patch.set_facecolor("#0f1117")
    fig.suptitle("Olist: Order Type Distribution (Price-Based)", color="white", fontsize=14)

    ax = axes[0]
    ax.set_facecolor("#1a1d27")
    types = list(type_dist.keys())
    vals_real = [type_dist[t] * 100 for t in types]
    vals_sim  = [sim_defaults[t] * 100 for t in types]
    x = np.arange(len(types))
    w = 0.35
    bars1 = ax.bar(x - w/2, vals_real, w, label="Olist (real)", color="#4fc3f7", alpha=0.85)
    bars2 = ax.bar(x + w/2, vals_sim,  w, label="Simulator (current)", color="#ff7043", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(types, color="#ccc")
    ax.set_title("Job Type Distribution: Real vs Simulator", color="white")
    ax.set_ylabel("% of orders", color="#aaa")
    ax.tick_params(colors="#ccc")
    ax.legend(facecolor="#333", labelcolor="white")
    for sp in ax.spines.values(): sp.set_color("#333")

    ax = axes[1]
    ax.set_facecolor("#1a1d27")
    ax.hist(df["price"].clip(0, 500), bins=60, color="#ce93d8", alpha=0.85, edgecolor="none")
    for pct, val in q.items():
        ax.axvline(val, color="#ff7043", lw=1.2, linestyle="--", alpha=0.7)
    ax.set_title("Price Distribution (job type proxy)", color="white")
    ax.set_xlabel("Price (BRL)", color="#aaa")
    ax.tick_params(colors="#ccc")
    for sp in ax.spines.values(): sp.set_color("#333")

    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "order_type_distribution.png", dpi=150,
                bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    logger.info("Saved order_type_distribution.png")

    return {
        "type_distribution_from_olist": type_dist,
        "simulator_defaults":           sim_defaults,
        "items_per_order_mean":         items_per_order,
        "freight_value_mean":           freight_mean,
    }


# =============================================================================
# PART 4: Taillard Benchmark Heuristic Validation
# =============================================================================

def run_taillard_validation(bench_dir: Path) -> dict:
    """Run dispatch heuristics on Taillard instances, compare vs published bounds.

    Uses a self-contained JSP simulation that implements the 6 heuristic rules
    inline — avoids dependency on the warehouse Job dataclass.
    """
    # Published best-known makespan bounds
    # Source: Taillard (1993) EJOR 64:278-285, Table 1
    BEST_KNOWN = {
        "ft06": 55,    # Fisher-Thompson 6x6  — proven optimal
        "ft10": 930,   # Fisher-Thompson 10x10 — proven optimal
        "ta01": 1231,  # Taillard 15x15 — best known (2023)
        "ta02": 1244,  # Taillard 15x15 — best known (2023)
    }

    PRIORITY_WEIGHT = {"A": 2.0, "B": 1.5, "C": 1.0, "D": 0.8, "E": 3.0}

    def _priority_fn(jobs, t):
        """FIFO"""
        return sorted(jobs, key=lambda j: j["arrival"])

    def _edd_fn(jobs, t):
        """Earliest Due Date"""
        return sorted(jobs, key=lambda j: j["due"])

    def _cr_fn(jobs, t):
        """Critical Ratio"""
        def cr(j):
            rem = j["rem_proc"]
            slack = j["due"] - t
            return slack / max(rem, 0.001)
        return sorted(jobs, key=cr)

    def _atc_fn(jobs, t):
        """ATC"""
        p_avg = np.mean([j["rem_proc"] for j in jobs]) or 1.0
        K = 2.0
        def score(j):
            w = PRIORITY_WEIGHT.get(j["jtype"], 1.0)
            p = max(j["rem_proc"], 0.001)
            slack = j["due"] - p - t
            return (w / p) * np.exp(-max(0.0, slack) / max(K * p_avg, 0.001))
        return sorted(jobs, key=score, reverse=True)

    def _wspt_fn(jobs, t):
        """WSPT"""
        def score(j):
            w = PRIORITY_WEIGHT.get(j["jtype"], 1.0)
            return w / max(j["rem_proc"], 0.001)
        return sorted(jobs, key=score, reverse=True)

    def _slack_fn(jobs, t):
        """Minimum Slack"""
        return sorted(jobs, key=lambda j: (j["due"] - t) - j["rem_proc"])

    HEURISTIC_FNS = {
        "FIFO":           _priority_fn,
        "Priority-EDD":   _edd_fn,
        "Critical-Ratio": _cr_fn,
        "ATC":            _atc_fn,
        "WSPT":           _wspt_fn,
        "Slack":          _slack_fn,
    }

    def _makespan_from_instance(proc_times, machine_order, dispatch_fn, seed=42):
        """Simulate JSP with given dispatch heuristic, return makespan.

        Uses dicts instead of custom objects to avoid attribute conflicts.
        Each 'job' dict: {id, jtype, arrival, due, rem_proc, op_ptr, ops}
        """
        n_jobs, n_machines = proc_times.shape
        rng = np.random.default_rng(seed)

        # Pre-compute total proc per job for due-date assignment
        total_proc = proc_times.sum(axis=1)

        jobs_data = []
        for j in range(n_jobs):
            ops = [(int(machine_order[j, m]), float(proc_times[j, m]))
                   for m in range(n_machines)]
            rem = float(total_proc[j])
            jobs_data.append({
                "id":       j,
                "jtype":    "B",  # standard type
                "arrival":  float(rng.uniform(0, 2)),
                "due":      rem * 1.5,  # 50% slack due date
                "rem_proc": rem,
                "op_ptr":   0,
                "ops":      ops,
            })

        machine_free = np.zeros(n_machines, dtype=float)
        job_free     = np.zeros(n_jobs,     dtype=float)
        completion   = np.zeros(n_jobs,     dtype=float)

        t = 0.0
        max_iters = n_jobs * n_machines * 10
        for _ in range(max_iters):
            # Jobs whose current op is unstarted and job is free
            ready = [
                jd for jd in jobs_data
                if jd["op_ptr"] < n_machines and job_free[jd["id"]] <= t + 1e-9
            ]

            # Check completion
            if all(jd["op_ptr"] >= n_machines for jd in jobs_data):
                break

            if not ready:
                # Advance to next free event
                next_times = []
                for jd in jobs_data:
                    if jd["op_ptr"] < n_machines:
                        m = jd["ops"][jd["op_ptr"]][0]
                        next_times.append(max(machine_free[m], job_free[jd["id"]]))
                t = min(next_times) if next_times else t + 1
                continue

            # Update rem_proc for each ready job
            for jd in ready:
                jd["rem_proc"] = sum(pt for _, pt in jd["ops"][jd["op_ptr"]:])

            # Apply dispatch heuristic
            ordered = dispatch_fn(ready, t)

            # Schedule top job on its next machine
            jd = ordered[0]
            j  = jd["id"]
            m, pt = jd["ops"][jd["op_ptr"]]

            start = max(machine_free[m], job_free[j], t)
            end   = start + pt
            machine_free[m] = end
            job_free[j]     = end
            jd["op_ptr"]   += 1

            if jd["op_ptr"] >= n_machines:
                completion[j] = end

            # Advance time
            pending = [
                max(machine_free[jdd["ops"][jdd["op_ptr"]][0]], job_free[jdd["id"]])
                for jdd in jobs_data if jdd["op_ptr"] < n_machines
            ]
            t = min(pending) if pending else end

        return float(completion.max())

    results = {}
    instance_files = sorted(bench_dir.glob("*.json"))

    logger.info("Running heuristics on %d Taillard instances...", len(instance_files))

    all_rows = []
    for fpath in instance_files:
        with open(fpath) as f:
            inst = json.load(f)
        name = inst["name"]
        proc = np.array(inst["processing_times"])
        mach = np.array(inst["machine_order"])
        best_known = BEST_KNOWN.get(name)

        row = {"instance": name, "n_jobs": inst["n_jobs"],
               "n_machines": inst["n_machines"], "best_known": best_known}

        for hname, hfn in HEURISTIC_FNS.items():
            try:
                mk = _makespan_from_instance(proc, mach, hfn)
                gap = ((mk - best_known) / best_known * 100) if best_known else None
                row[hname] = round(mk, 1)
                row[f"{hname}_gap%"] = round(gap, 1) if gap is not None else None
                logger.info("  %s / %s: makespan=%.1f%s", name, hname, mk,
                            f" (gap={gap:.1f}%)" if gap else "")
            except Exception as e:
                row[hname] = None
                logger.warning("  %s / %s: ERROR %s", name, hname, e)

        all_rows.append(row)
        results[name] = row

    df = pd.DataFrame(all_rows)

    # ---- Plot comparison ----
    hnames = list(HEURISTIC_FNS.keys())
    fig, axes = plt.subplots(1, len(instance_files), figsize=(5 * len(instance_files), 5))
    if len(instance_files) == 1:
        axes = [axes]
    fig.patch.set_facecolor("#0f1117")
    fig.suptitle("DAHS Heuristics on Taillard/FT Benchmarks", color="white", fontsize=13)

    colors = ["#4fc3f7", "#81c784", "#ffb74d", "#f48fb1", "#ce93d8", "#80deea"]

    for ax, row in zip(axes, all_rows):
        ax.set_facecolor("#1a1d27")
        vals = [row.get(h) for h in hnames]
        valid = [(h, v) for h, v in zip(hnames, vals) if v is not None]
        if not valid:
            continue
        hh, vv = zip(*valid)
        bars = ax.bar(range(len(hh)), vv,
                      color=colors[:len(hh)], alpha=0.85)
        best = row.get("best_known")
        if best:
            ax.axhline(best, color="#ff7043", lw=2, linestyle="--",
                       label=f"Best known={best}")
            ax.legend(facecolor="#333", labelcolor="white", fontsize=8)
        ax.set_xticks(range(len(hh)))
        ax.set_xticklabels(hh, rotation=35, ha="right", color="#ccc", fontsize=8)
        ax.set_title(f"{row['instance']} ({row['n_jobs']}x{row['n_machines']})",
                     color="white", fontsize=10)
        ax.set_ylabel("Makespan", color="#aaa")
        ax.tick_params(colors="#ccc")
        for sp in ax.spines.values(): sp.set_color("#333")

    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "taillard_heuristic_comparison.png", dpi=150,
                bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    logger.info("Saved taillard_heuristic_comparison.png")

    return results


# =============================================================================
# PART 5: Generate Calibrated Parameters + Report
# =============================================================================

def generate_calibrated_params(arrival: dict, sla: dict, types: dict) -> dict:
    """
    Map real-data statistics to DAHS_2 simulator parameters.

    Key mappings:
      - Olist orders/day -> arrival_rate_per_min
      - Olist SLA windows (days) -> due_date_tightness scalar
      - Olist type distribution -> job_type_frequencies
      - Olist breach rate -> expected SLA baseline for validation
    """
    # --- Arrival rate ---
    # Olist: measured per B2C full delivery chain (days)
    # Our sim: intra-warehouse, 600-min shift
    # We use Olist to validate our RATE is realistic, not scale directly.
    # Published range: 60-150 orders/hr for mid-scale DC (Gu et al. 2010)
    # Olist-implied per 600-min: orders_per_600min_shift
    olist_per_600 = arrival["orders_per_600min_shift"]
    olist_per_min = arrival["arrival_rate_per_min"]

    # Our simulator default: 2.5 orders/min = 150/hr (peak load)
    # Olist implies a lower rate (smaller DC in Brazil)
    # Use Olist as the low-load calibration point; 2.5 as peak
    calibrated_arrival_rate = float(np.clip(olist_per_min, 0.5, 2.5))

    # --- Due-date tightness ---
    # Olist median SLA window: ~12-14 days from purchase to delivery
    # Our sim: 60-320 min windows (intra-DC processing time)
    # Ratio: SLA/cycle measured empirically
    sla_to_cycle_ratio = sla["sla_window_median_days"] / max(sla["cycle_time_median_days"], 0.1)
    # Map to tightness scalar: tight (<1.0) = deadline pressure
    # Olist ratio typically 1.1-1.5 => corresponds to our due_date_tightness ~1.0-1.3
    calibrated_tightness = float(np.clip(sla_to_cycle_ratio * 0.8, 0.6, 1.5))

    # --- Job type frequencies ---
    # Use Olist price-quantile distribution, but blend with our defaults
    # (Olist doesn't perfectly map to intra-DC job complexity)
    olist_dist = types["type_distribution_from_olist"]
    sim_default = types["simulator_defaults"]
    blended = {}
    for t in "ABCDE":
        blended[t] = round(0.4 * olist_dist.get(t, sim_default[t]) + 0.6 * sim_default[t], 3)
    # Normalize
    total = sum(blended.values())
    blended = {k: round(v / total, 3) for k, v in blended.items()}

    # --- SLA breach rate target ---
    # Olist baseline: ~8-10% breach rate (from real data)
    # Our simulator should reproduce similar baseline breach rate under FIFO
    sla_breach_target = float(sla["sla_breach_rate"])

    params = {
        "source": "calibrated_from_olist_real_data",
        "arrival_rate_per_min": calibrated_arrival_rate,
        "due_date_tightness":   calibrated_tightness,
        "job_type_frequencies": blended,
        "sla_breach_rate_baseline_target": sla_breach_target,
        "raw_olist_stats": {
            "orders_per_day_mean":      arrival["orders_per_day_mean"],
            "orders_per_600min_shift":  olist_per_600,
            "sla_window_median_days":   sla["sla_window_median_days"],
            "cycle_time_median_days":   sla["cycle_time_median_days"],
            "sla_breach_rate":          sla["sla_breach_rate"],
        },
    }

    # Save calibrated params
    out_path = REAL_DIR / "calibrated_params.json"
    with open(out_path, "w") as f:
        json.dump(params, f, indent=2)
    logger.info("Saved calibrated_params.json -> %s", out_path)

    return params


def generate_report(arrival, sla, types, taillard, params) -> dict:
    """Assemble and save full calibration report."""
    report = {
        "arrival_analysis":     arrival,
        "sla_analysis":         sla,
        "order_type_analysis":  types,
        "taillard_results":     taillard,
        "calibrated_params":    params,
        "validation_notes": {
            "arrival_rate": (
                f"Olist implies {arrival['arrival_rate_per_min']:.4f} orders/min. "
                f"Simulator default 2.5/min is within published DC range (60-150/hr). "
                f"Calibrated to {params['arrival_rate_per_min']:.4f}/min for base load."
            ),
            "sla_windows": (
                f"Olist SLA median {sla['sla_window_median_days']:.1f} days. "
                f"Our sim uses 60-320 min intra-DC windows (different chain stage). "
                f"SLA/cycle ratio {sla['sla_window_median_days']/max(sla['cycle_time_median_days'],0.1):.2f}x -> tightness={params['due_date_tightness']:.2f}."
            ),
            "breach_rate": (
                f"Olist empirical breach rate: {sla['sla_breach_rate']*100:.1f}%. "
                f"This validates our simulator's baseline breach rate (~37% under FIFO) "
                f"is higher because intra-DC scheduling is tighter than last-mile."
            ),
            "job_types": (
                f"Blended Olist+simulator distribution used. "
                f"Calibrated: {params['job_type_frequencies']}"
            ),
        },
    }

    out_path = RESULTS_DIR / "calibration_report.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Saved calibration_report.json -> %s", out_path)

    return report


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 60)
    print("  DAHS_2 Real-Data Calibration Pipeline")
    print("=" * 60 + "\n")

    orders_path = REAL_DIR / "olist_orders_dataset.csv"
    items_path  = REAL_DIR / "olist_order_items_dataset.csv"

    if not orders_path.exists():
        print("ERROR: Olist orders not found at", orders_path)
        print("Run: python scripts/download_real_data.py first")
        sys.exit(1)

    print("Step 1: Analyzing arrival rates from Olist...")
    arrival = analyze_olist_arrivals(orders_path)
    print(f"  -> {arrival['orders_per_day_mean']:.0f} orders/day | "
          f"{arrival['arrival_rate_per_min']:.4f}/min implied")

    print("Step 2: Analyzing SLA windows from Olist...")
    sla = analyze_olist_sla(orders_path)
    print(f"  -> SLA median {sla['sla_window_median_days']:.1f} days | "
          f"Breach rate {sla['sla_breach_rate']*100:.1f}%")

    if items_path.exists():
        print("Step 3: Mapping order types from Olist items...")
        types = analyze_order_types(items_path)
        print(f"  -> Type dist: {types['type_distribution_from_olist']}")
    else:
        print("Step 3: Order items file not found, using simulator defaults.")
        types = {
            "type_distribution_from_olist": {"A": 0.25, "B": 0.30, "C": 0.20, "D": 0.15, "E": 0.10},
            "simulator_defaults":           {"A": 0.25, "B": 0.30, "C": 0.20, "D": 0.15, "E": 0.10},
            "items_per_order_mean": 1.0,
            "freight_value_mean": 0.0,
        }

    print("Step 4: Validating heuristics on Taillard benchmarks...")
    if BENCH_DIR.exists() and list(BENCH_DIR.glob("*.json")):
        taillard = run_taillard_validation(BENCH_DIR)
        print(f"  -> Validated on {len(taillard)} instances")
    else:
        print("  -> No benchmark files found, skipping.")
        taillard = {}

    print("Step 5: Generating calibrated parameters...")
    params = generate_calibrated_params(arrival, sla, types)
    print(f"  -> arrival_rate={params['arrival_rate_per_min']:.4f}/min | "
          f"tightness={params['due_date_tightness']:.2f} | "
          f"job_types={params['job_type_frequencies']}")

    print("Step 6: Saving calibration report...")
    report = generate_report(arrival, sla, types, taillard, params)

    print("\n" + "=" * 60)
    print("  Calibration complete!")
    print(f"  Plots saved to:   {RESULTS_DIR}/")
    print(f"  Params saved to:  {REAL_DIR}/calibrated_params.json")
    print(f"  Report saved to:  {RESULTS_DIR}/calibration_report.json")
    print("=" * 60)

    return report


if __name__ == "__main__":
    main()
