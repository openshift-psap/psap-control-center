#!/usr/bin/env python3
"""Build the 14-day GPU utilization report for psap-h200-fire-athena and psap-h100-diadochos.

Pulls DCGM_FI_DEV_GPU_UTIL / DCGM_FI_DEV_FB_USED from each cluster's OpenShift
Prometheus through a local kubectl port-forward and renders a self-contained
Plotly HTML report with cluster-level, per-node, and per-GPU time series.

Prerequisites (run before invoking):
  kubectl --kubeconfig <fire-athena-kc> -n openshift-monitoring port-forward svc/prometheus-k8s 9090:9091 &
  kubectl --kubeconfig <diadochos-kc>    -n openshift-monitoring port-forward svc/prometheus-k8s 9093:9091 &

Usage:
  python3 generate_gpu_utilization_14d_report.py <fire-athena-kubeconfig> <diadochos-kubeconfig>
  python3 generate_gpu_utilization_14d_report.py --no-fetch   # re-render from saved data
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly
import plotly.express as px
from plotly.graph_objects import Figure

ROOT = Path(__file__).resolve().parent
DATA_OUTPUT = ROOT / "gpu-utilization-14d-data.json"
OUTPUT = ROOT / "gpu-utilization-14d-report.html"

RANGE_DAYS = 14
STEP_SECONDS = 3600
FA_PORT = 9090
DC_PORT = 9093
FB_ACTIVE_THRESHOLD_MIB = 1024

CLUSTERS = {
    "psap-h200-fire-athena": {"port": FA_PORT, "color": "#0072B2", "color2": "#56B4E9", "gpus": 16, "node": "H200", "hostlabel": "hostname",
                              "nodepalette": ["#0072B2", "#56B4E9"]},
    "psap-h100-diadochos": {"port": DC_PORT, "color": "#D55E00", "color2": "#F4A582", "gpus": 32, "node": "H100", "hostlabel": "Hostname",
                            "nodepalette": ["#D55E00", "#F4A582", "#F9CB9C", "#8B3A00"]},
}

GPU_PALETTES = {
    "psap-h200-fire-athena": ["#0072B2", "#009E73", "#D55E00", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442", "#999999", "#7570B3", "#6A51A3", "#B4332F", "#33A02C", "#FB9A99", "#A6761D", "#1F78B4", "#FF7F00"],
    "psap-h100-diadochos": ["#E31A1C", "#FF7F00", "#FEB24C", "#FDB863", "#E34A33", "#B33626", "#8B0000", "#CC3311", "#FF6655", "#D95319", "#C7254E", "#91278D", "#7741FF", "#6610F2", "#3A87AD", "#2C7BB6", "#21918C", "#21A58E", "#33B5E5", "#4DBDD5", "#00A9AD", "#00BFBD", "#00C2D8", "#00CFFF", "#2CA8FF", "#2D74DA", "#2E44EF", "#3329EE", "#3900B5", "#3E008A", "#4E006E", "#7E2F8E"],
}


def queries_for(name: str) -> dict:
    h = CLUSTERS[name]["hostlabel"]
    return {
        "cluster": "avg(DCGM_FI_DEV_GPU_UTIL)",
        "active": f"count(DCGM_FI_DEV_FB_USED > {FB_ACTIVE_THRESHOLD_MIB})",
        "node": f"avg by ({h})(DCGM_FI_DEV_GPU_UTIL)",
        "gpu": f"avg by ({h}, gpu)(DCGM_FI_DEV_GPU_UTIL)",
    }


def node_short(hostname: str) -> str:
    parts = hostname.rsplit("-", 3)
    return "-".join(parts[-2:]) if len(parts) >= 2 else hostname


def start_forward(kc: str, port: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        ["kubectl", "--kubeconfig", kc, "-n", "openshift-monitoring", "port-forward", "svc/prometheus-k8s", f"{port}:9091"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return proc
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError(f"port-forward on :{port} exited early")
            time.sleep(1)
    proc.terminate()
    raise RuntimeError(f"port-forward on :{port} did not become ready in 45s")


def fetch_cluster(name: str, kc: str, forwards: dict) -> dict:
    port = CLUSTERS[name]["port"]
    if name not in forwards:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                pass  # already reachable, reuse
        except OSError:
            forwards[name] = start_forward(kc, port)
    token = subprocess.run(
        ["kubectl", "--kubeconfig", kc, "-n", "openshift-monitoring", "create", "token", "prometheus-k8s", "--duration=1800s"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    end = int(time.time())
    start = end - RANGE_DAYS * 86400
    hostlabel = CLUSTERS[name]["hostlabel"]
    result = {}
    for key, query in queries_for(name).items():
        url = (
            f"https://localhost:{port}/api/v1/query_range?"
            + urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": STEP_SECONDS})
        )
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            payload = json.load(resp)
        if payload.get("status") != "success":
            raise RuntimeError(f"{name} query '{query}' failed: {payload}")
        series = []
        for item in payload["data"]["result"]:
            metric = dict(item["metric"])
            if hostlabel in metric:
                metric["host"] = metric.pop(hostlabel)
            vals = [[float(t), None if v == "NaN" else float(v)] for t, v in item["values"]]
            series.append({"metric": metric, "values": vals})
        result[key] = series
        print(f"  {name} {key}: {len(series)} series")
    return result


def cluster_names(data: dict) -> list[str]:
    return [k for k in data if k != "_meta"]


def summarize(data: dict) -> list[dict]:
    rows = []
    for name in cluster_names(data):
        util = data[name]["cluster"][0]["values"]
        active = data[name]["active"][0]["values"]
        utils = [v for _, v in util if v is not None]
        counts = [v for _, v in active if v is not None]
        gpu_hours = sum(counts) * (STEP_SECONDS / 3600)
        rows.append({
            "cluster": name,
            "gpus": CLUSTERS[name]["gpus"],
            "avg_util_pct": round(sum(utils) / len(utils), 1),
            "peak_1h_avg_pct": round(max(utils), 1),
            "active_gpu_hours": round(gpu_hours, 0),
            "pct_window_active": round(100 * gpu_hours / (RANGE_DAYS * 24 * CLUSTERS[name]["gpus"]), 1),
        })
    return rows


def to_frame(data: dict, key: str, label_fn) -> pd.DataFrame:
    """Flatten raw query results into a long-form DataFrame for plotly express."""
    rows = []
    for name in cluster_names(data):
        for series in data[name][key]:
            label = label_fn(name, series["metric"])
            for t, v in series["values"]:
                if v is None:
                    continue
                rows.append({
                    "cluster": name,
                    "time": datetime.fromtimestamp(t, tz=timezone.utc),
                    "label": label,
                    "value": v,
                })
    return pd.DataFrame(rows, columns=["cluster", "time", "label", "value"])


def chart_cluster(data: dict) -> Figure:
    names = cluster_names(data)
    cmap = {name: CLUSTERS[name]["color"] for name in names}
    util = to_frame(data, "cluster", lambda name, _m: name)
    active = to_frame(data, "active", lambda name, _m: name)
    fig = px.line(
        util, x="time", y="value", color="cluster", color_discrete_map=cmap,
        labels={"value": "Avg GPU utilization %", "cluster": "", "time": ""},
    )
    fig_active = px.line(
        active, x="time", y="value", color="cluster", color_discrete_map=cmap,
        labels={"value": "", "cluster": "", "time": ""},
    )
    fig_active.for_each_trace(
        lambda t: t.update(yaxis="y2", name=f"{t.name} active GPUs", line_dash="dot")
    )
    fig.add_traces(fig_active.data)
    fig.update_layout(
        title="Cluster-level GPU utilization — last 14 days (1h buckets, UTC)",
        yaxis=dict(title="Avg GPU utilization %", range=[0, 105]),
        yaxis2=dict(title="Active GPUs (VRAM > 1 GiB)", overlaying="y", side="right", range=[-2, 40], showgrid=False),
        legend=dict(orientation="h", y=1.12),
        height=420,
    )
    return fig


def chart_node(data: dict) -> Figure:
    cmap, dmap = {}, {}
    for name in cluster_names(data):
        cfg = CLUSTERS[name]
        hosts = sorted(data[name]["node"], key=lambda s: s["metric"]["host"])
        for i, s in enumerate(hosts):
            label = f"{node_short(s['metric']['host'])} ({name})"
            cmap[label] = cfg["color"] if i == 0 else cfg["color2"]
            dmap[label] = "solid" if i == 0 else "dash"
    df = to_frame(data, "node", lambda name, m: f"{node_short(m['host'])} ({name})")
    fig = px.line(
        df, x="time", y="value", color="label",
        color_discrete_map=cmap,
        labels={"value": "Avg GPU utilization %", "label": "", "time": "", "cluster": None},
        title="Per-node average GPU utilization — last 14 days (1h buckets, UTC)",
    )
    fig.for_each_trace(lambda t: t.update(line_dash=dmap[t.name]))
    fig.update_layout(
        yaxis=dict(range=[0, 105]),
        legend=dict(orientation="h", y=1.12),
        height=460,
    )
    return fig


def chart_gpu(data: dict) -> Figure:
    names = cluster_names(data)
    cmap = {}
    for name in names:
        palette = GPU_PALETTES[name]
        series_list = sorted(
            data[name]["gpu"], key=lambda s: (s["metric"]["host"], int(s["metric"]["gpu"]))
        )
        for i, s in enumerate(series_list):
            label = f"{node_short(s['metric']['host'])} gpu{s['metric']['gpu']}"
            cmap[label] = palette[i % len(palette)]
    df = to_frame(data, "gpu", lambda name, m: f"{node_short(m['host'])} gpu{m['gpu']}")
    faceted = len(names) > 1
    fig = px.line(
        df, x="time", y="value", color="label", color_discrete_map=cmap,
        facet_row="cluster" if faceted else None,
        labels={"value": "Avg GPU utilization %", "label": "", "time": ""},
        title="Per-GPU average utilization — last 14 days (1h buckets, UTC)",
    )
    if faceted:
        for ax in range(2, len(names) + 1):
            fig.update_layout(**{f"xaxis{ax}_matches": "x", f"xaxis{ax}_visible": False})
        for row, name in enumerate(names, start=1):
            fig.update_yaxes(title_text=f"{name} avg util %", range=[0, 105], row=row, col=1)
        for a in fig.layout.annotations:
            text = a.text.split("=", 1)[1] if "=" in a.text else a.text
            if text in CLUSTERS:
                cfg = CLUSTERS[text]
                a.text = f"{text} — {cfg['gpus']}x {cfg['node']}"
                a.font = dict(size=13, weight="bold")
    fig.update_layout(
        legend=dict(orientation="h", y=1.12),
        height=950,
    )
    return fig


def render(data: dict) -> None:
    summaries = summarize(data)
    rows_html = "".join(
        "<tr><td>{cluster}</td><td>{gpus}</td><td>{avg_util_pct}%</td><td>{peak_1h_avg_pct}%</td>"
        "<td>{active_gpu_hours:.0f}</td><td>{pct_window_active}%</td></tr>".format(**row)
        for row in summaries
    )
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    start = datetime.fromtimestamp(time.time() - RANGE_DAYS * 86400, tz=timezone.utc).strftime("%Y-%m-%d")
    names = cluster_names(data)
    cluster_desc = " and ".join(f"<b>{n}</b> ({CLUSTERS[n]['gpus']}x {CLUSTERS[n]['node']})" for n in names)
    figures = {
        "c1": chart_cluster(data),
        "c2": chart_node(data),
        "c3": chart_gpu(data),
    }
    plotly_js = plotly.offline.get_plotlyjs()
    figure_scripts = "\n".join(
        f'<div id="{div}" style="margin-bottom: 32px;"></div>\n'
        f'<script>Plotly.newPlot("{div}", {fig.to_json()}, {{responsive: true}});</script>'
        for div, fig in figures.items()
    )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>GPU utilization 14d — fire-athena + diadochos</title>
<script>{plotly_js}</script>
</head><body style="font-family: -apple-system, sans-serif; max-width: 1200px; margin: 24px auto; color: #111;">
<h1>GPU utilization — last {RANGE_DAYS} days</h1>
<p>Clusters: {cluster_desc}.
Window: {start} to now (UTC), 1-hour buckets over 30s DCGM samples.
"Active GPU" = VRAM usage above {FB_ACTIVE_THRESHOLD_MIB} MiB. Generated {generated}.</p>
<table border="1" cellspacing="0" cellpadding="6" style="border-collapse: collapse; margin-bottom: 24px;">
<tr style="background:#eee;"><th>Cluster</th><th>GPUs</th><th>Window avg util</th><th>Peak 1h avg</th><th>Active GPU-hours</th><th>% of GPU-time active</th></tr>
{rows_html}
</table>
{figure_scripts}
</body></html>"""
    OUTPUT.write_text(html)
    print(OUTPUT)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fa_kc", nargs="?", help="fire-athena kubeconfig path")
    parser.add_argument("dc_kc", nargs="?", help="diadochos kubeconfig path")
    parser.add_argument("--no-fetch", action="store_true", help="render from saved data JSON")
    parser.add_argument("--only", choices=sorted(CLUSTERS), help="fetch/render a single cluster only")
    args = parser.parse_args()

    pairs = [("psap-h200-fire-athena", args.fa_kc), ("psap-h100-diadochos", args.dc_kc)]
    if args.only:
        pairs = [p for p in pairs if p[0] == args.only]

    if args.no_fetch:
        data = json.loads(DATA_OUTPUT.read_text())
        if args.only:
            data = {k: v for k, v in data.items() if k == args.only or k == "_meta"}
        render(data)
        return

    missing = [name for name, kc in pairs if not kc]
    if missing:
        parser.error(f"kubeconfig path(s) missing for: {', '.join(missing)}")
    forwards: dict[str, subprocess.Popen] = {}
    data = {}
    try:
        for name, kc in pairs:
            print(f"Fetching {name} ...")
            data[name] = fetch_cluster(name, kc, forwards)
        data["_meta"] = {
            "generated": datetime.now(timezone.utc).isoformat(),
            "range_days": RANGE_DAYS,
            "step_seconds": STEP_SECONDS,
            "active_threshold_mib": FB_ACTIVE_THRESHOLD_MIB,
        }
        DATA_OUTPUT.write_text(json.dumps(data, indent=1))
        print(DATA_OUTPUT)
    finally:
        for proc in forwards.values():
            proc.terminate()
            proc.wait()
    render(data)


if __name__ == "__main__":
    main()
