#!/usr/bin/env python3
"""Build a multi-day GPU utilization report for caller-specified OpenShift clusters.

Pulls DCGM_FI_DEV_GPU_UTIL / DCGM_FI_DEV_FB_USED from each cluster's OpenShift
Prometheus through a local kubectl port-forward and renders a self-contained
Plotly HTML report with cluster-level, per-node, and per-GPU time series.

Cluster topology (name, kubeconfig, port, DCGM hostname label) is entirely
supplied by the caller, e.g.:

  python3 gpu_utilization_report.py \
    --cluster my-cluster-a --kubeconfig /path/a.kc --port 9090 --hostlabel hostname \
    --cluster my-cluster-b --kubeconfig /path/b.kc --port 9093 --hostlabel Hostname \
    --days 14 --step 3600 --out-dir /tmp/reports

  python3 gpu_utilization_report.py --no-fetch   # re-render from saved data
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
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly
import plotly.express as px
from plotly.graph_objects import Figure

ROOT = Path(__file__).resolve().parent

DEFAULT_DAYS = 14
DEFAULT_STEP = 3600
DEFAULT_PORT = 9090
DEFAULT_HOSTLABEL = "hostname"
FB_ACTIVE_THRESHOLD_MIB = 1024


def queries_for(hostlabel: str) -> dict:
    return {
        "cluster": "avg(DCGM_FI_DEV_GPU_UTIL)",
        "active": f"count(DCGM_FI_DEV_FB_USED > {FB_ACTIVE_THRESHOLD_MIB})",
        "node": f"avg by ({hostlabel})(DCGM_FI_DEV_GPU_UTIL)",
        "gpu": f"avg by ({hostlabel}, gpu)(DCGM_FI_DEV_GPU_UTIL)",
    }


def node_short(hostname: str) -> str:
    parts = hostname.rsplit("-", 3)
    return "-".join(parts[-2:]) if len(parts) >= 2 else hostname


def parse_clusters(parser: argparse.ArgumentParser, args) -> dict:
    """Validate the repeated --cluster/--kubeconfig/--port/--hostlabel options."""
    if not args.cluster:
        return {}
    n = len(args.cluster)
    if len(args.cluster) != len(set(args.cluster)):
        parser.error("duplicate --cluster name")
    for flag, values in (
        ("--kubeconfig", args.kubeconfig),
        ("--port", args.port),
        ("--hostlabel", args.hostlabel),
    ):
        if values and len(values) != n:
            parser.error(f"{flag} must be given once per --cluster ({n} needed, got {len(values)})")
    if n > 1 and not args.port:
        parser.error("--port is required when passing more than one --cluster")
    kubeconfigs = args.kubeconfig or [None] * n
    ports = args.port or [DEFAULT_PORT] * n
    hostlabels = args.hostlabel or [DEFAULT_HOSTLABEL] * n
    clusters = {}
    for name, kc, port, hostlabel in zip(args.cluster, kubeconfigs, ports, hostlabels):
        if not kc:
            parser.error(f"--kubeconfig is required for cluster {name}")
        clusters[name] = {"kubeconfig": kc, "port": port, "hostlabel": hostlabel}
    return clusters


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


def fetch_cluster(name: str, cfg: dict, forwards: dict) -> dict:
    port = cfg["port"]
    if name not in forwards:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                pass  # already reachable, reuse
        except OSError:
            forwards[name] = start_forward(cfg["kubeconfig"], port)
    token = subprocess.run(
        ["kubectl", "--kubeconfig", cfg["kubeconfig"], "-n", "openshift-monitoring", "create", "token", "prometheus-k8s", "--duration=1800s"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    end = int(time.time())
    start = end - cfg["days"] * 86400
    result = {}
    for key, query in queries_for(cfg["hostlabel"]).items():
        url = (
            f"https://localhost:{port}/api/v1/query_range?"
            + urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": cfg["step"]})
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
            if cfg["hostlabel"] in metric:
                metric["host"] = metric.pop(cfg["hostlabel"])
            vals = [[float(t), None if v == "NaN" else float(v)] for t, v in item["values"]]
            series.append({"metric": metric, "values": vals})
        result[key] = series
        print(f"  {name} {key}: {len(series)} series")
    return result


def cluster_names(data: dict) -> list[str]:
    return [k for k in data if k != "_meta"]


def summarize(data: dict, days: int, step: int) -> list[dict]:
    rows = []
    for name in cluster_names(data):
        util = data[name]["cluster"][0]["values"]
        active = data[name]["active"][0]["values"]
        utils = [v for _, v in util if v is not None]
        counts = [v for _, v in active if v is not None]
        gpus = max(len(data[name]["gpu"]), 1)
        gpu_hours = sum(counts) * (step / 3600)
        rows.append({
            "cluster": name,
            "gpus": gpus,
            "avg_util_pct": round(sum(utils) / len(utils), 1),
            "peak_1h_avg_pct": round(max(utils), 1),
            "active_gpu_hours": round(gpu_hours, 0),
            "pct_window_active": round(100 * gpu_hours / (days * 24 * gpus), 1),
        })
    return rows


def step_label(step: int) -> str:
    return f"{step // 3600}h" if step % 3600 == 0 else f"{step}s"


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


def chart_cluster(data: dict, days: int, step: int) -> Figure:
    names = cluster_names(data)
    util = to_frame(data, "cluster", lambda name, _m: name)
    active = to_frame(data, "active", lambda name, _m: name)
    fig = px.line(
        util, x="time", y="value", color="cluster",
        labels={"value": "Avg GPU utilization %", "cluster": "", "time": ""},
    )
    fig_active = px.line(
        active, x="time", y="value", color="cluster",
        labels={"value": "", "cluster": "", "time": ""},
    )
    fig_active.for_each_trace(
        lambda t: t.update(yaxis="y2", name=f"{t.name} active GPUs", line_dash="dot")
    )
    fig.add_traces(fig_active.data)
    fig.update_layout(
        title=f"Cluster-level GPU utilization — last {days} days ({step_label(step)} buckets, UTC)",
        yaxis=dict(title="Avg GPU utilization %", range=[0, 105]),
        yaxis2=dict(title="Active GPUs (VRAM > 1 GiB)", overlaying="y", side="right", range=[-2, 40], showgrid=False),
        legend=dict(orientation="h", y=1.12),
        height=420,
    )
    return fig


def chart_node(data: dict, days: int, step: int) -> Figure:
    df = to_frame(data, "node", lambda name, m: f"{node_short(m['host'])} ({name})")
    fig = px.line(
        df, x="time", y="value", color="label",
        labels={"value": "Avg GPU utilization %", "label": "", "time": ""},
        title=f"Per-node average GPU utilization — last {days} days ({step_label(step)} buckets, UTC)",
    )
    fig.update_layout(
        yaxis=dict(range=[0, 105]),
        legend=dict(orientation="h", y=1.12),
        height=460,
    )
    return fig


def chart_gpu(data: dict, days: int, step: int) -> Figure:
    names = cluster_names(data)
    df = to_frame(data, "gpu", lambda name, m: f"{node_short(m['host'])} gpu{m['gpu']}")
    faceted = len(names) > 1
    fig = px.line(
        df, x="time", y="value", color="label",
        facet_row="cluster" if faceted else None,
        labels={"value": "Avg GPU utilization %", "label": "", "time": ""},
        title=f"Per-GPU average utilization — last {days} days ({step_label(step)} buckets, UTC)",
    )
    if faceted:
        for ax in range(2, len(names) + 1):
            fig.update_layout(**{f"xaxis{ax}_matches": "x", f"xaxis{ax}_visible": False})
        for row, name in enumerate(names, start=1):
            fig.update_yaxes(title_text=f"{name} avg util %", range=[0, 105], row=row, col=1)
        counts = df.groupby("cluster")["label"].nunique().to_dict()
        for a in fig.layout.annotations:
            text = a.text.split("=", 1)[1] if "=" in a.text else a.text
            if text in counts:
                a.text = f"{text} — {counts[text]} GPUs"
                a.font = dict(size=13, weight="bold")
    fig.update_layout(
        legend=dict(orientation="h", y=1.12),
        height=950,
    )
    return fig


def render(data: dict, days: int, step: int, out_path: Path) -> None:
    summaries = summarize(data, days, step)
    rows_html = "".join(
        "<tr><td>{cluster}</td><td>{gpus}</td><td>{avg_util_pct}%</td><td>{peak_1h_avg_pct}%</td>"
        "<td>{active_gpu_hours:.0f}</td><td>{pct_window_active}%</td></tr>".format(**row)
        for row in summaries
    )
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    start = datetime.fromtimestamp(time.time() - days * 86400, tz=timezone.utc).strftime("%Y-%m-%d")
    names = cluster_names(data)
    cluster_desc = " and ".join(f"<b>{n}</b> ({len(data[n]['gpu'])} GPUs)" for n in names)
    figures = {
        "c1": chart_cluster(data, days, step),
        "c2": chart_node(data, days, step),
        "c3": chart_gpu(data, days, step),
    }
    plotly_js = plotly.offline.get_plotlyjs()
    figure_scripts = "\n".join(
        f'<div id="{div}" style="margin-bottom: 32px;"></div>\n'
        f'<script>Plotly.newPlot("{div}", {fig.to_json()}, {{responsive: true}});</script>'
        for div, fig in figures.items()
    )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>GPU utilization {days}d report</title>
<script>{plotly_js}</script>
</head><body style="font-family: -apple-system, sans-serif; max-width: 1200px; margin: 24px auto; color: #111;">
<h1>GPU utilization — last {days} days</h1>
<p>Clusters: {cluster_desc}.
Window: {start} to now (UTC), {step_label(step)} buckets.
"Active GPU" = VRAM usage above {FB_ACTIVE_THRESHOLD_MIB} MiB. Generated {generated}.</p>
<table border="1" cellspacing="0" cellpadding="6" style="border-collapse: collapse; margin-bottom: 24px;">
<tr style="background:#eee;"><th>Cluster</th><th>GPUs</th><th>Window avg util</th><th>Peak 1h avg</th><th>Active GPU-hours</th><th>% of GPU-time active</th></tr>
{rows_html}
</table>
{figure_scripts}
</body></html>"""
    out_path.write_text(html)
    print(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster", action="append", metavar="NAME",
                        help="cluster name; repeat together with --kubeconfig for multiple clusters")
    parser.add_argument("--kubeconfig", action="append", metavar="PATH",
                        help="kubeconfig path for the matching --cluster")
    parser.add_argument("--port", action="append", type=int, metavar="PORT",
                        help="local port for the matching --cluster Prometheus port-forward")
    parser.add_argument("--hostlabel", action="append", metavar="LABEL",
                        help="DCGM hostname metric label for the matching --cluster")
    parser.add_argument("--no-fetch", action="store_true", help="render from saved data JSON")
    parser.add_argument("--only", metavar="NAME", help="fetch/render a single cluster only")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="look-back window in days")
    parser.add_argument("--step", type=int, default=DEFAULT_STEP, help="query step in seconds")
    parser.add_argument("--out-dir", type=Path, default=ROOT, help="directory for data JSON and HTML report")
    args = parser.parse_args()

    days, step = args.days, args.step
    out_dir = args.out_dir
    data_path = out_dir / f"gpu-utilization-{days}d-data.json"
    out_path = out_dir / f"gpu-utilization-{days}d-report.html"

    clusters = parse_clusters(parser, args)
    for cfg in clusters.values():
        cfg["days"] = days
        cfg["step"] = step

    if args.no_fetch:
        data = json.loads(data_path.read_text())
        if args.only:
            data = {k: v for k, v in data.items() if k == args.only or k == "_meta"}
        render(data, days, step, out_path)
        return

    if not clusters:
        parser.error("at least one --cluster/--kubeconfig pair is required (or use --no-fetch)")
    if args.only:
        clusters = {n: c for n, c in clusters.items() if n == args.only}
        if not clusters:
            parser.error(f"--only {args.only} not among the --cluster names")

    forwards: dict[str, subprocess.Popen] = {}
    data = {}
    try:
        for name, cfg in clusters.items():
            print(f"Fetching {name} ...")
            data[name] = fetch_cluster(name, cfg, forwards)
        data["_meta"] = {
            "generated": datetime.now(timezone.utc).isoformat(),
            "days": days,
            "step_seconds": step,
            "active_threshold_mib": FB_ACTIVE_THRESHOLD_MIB,
        }
        data_path.write_text(json.dumps(data, indent=1))
        print(data_path)
    finally:
        for proc in forwards.values():
            proc.terminate()
            proc.wait()
    render(data, days, step, out_path)


if __name__ == "__main__":
    main()
