"""Unit tests for scripts.gpu_utilization_14d_report (offline, mocked I/O)."""

import io
import json
import subprocess
import sys
import time
from unittest import mock

import pytest

import scripts.gpu_utilization_14d_report as report


FA = "psap-h200-fire-athena"
DC = "psap-h100-diadochos"
T0 = 1_700_000_000


def _series(host=None, gpu=None, values=(50.0, 60.0)):
    metric = {}
    if host is not None:
        metric["host"] = host
    if gpu is not None:
        metric["gpu"] = gpu
    return {
        "metric": metric,
        "values": [[T0 + i * report.STEP_SECONDS, v] for i, v in enumerate(values)],
    }


def _sample_data():
    return {
        FA: {
            "cluster": [_series()],
            "active": [_series(values=(8.0, 8.0))],
            "node": [_series(host="fa-node-abc")],
            "gpu": [
                _series(host="fa-node-abc", gpu="0"),
                _series(host="fa-node-abc", gpu="1"),
            ],
        },
        DC: {
            "cluster": [_series()],
            "active": [_series(values=(4.0, 4.0))],
            "node": [_series(host="dc-node-xyz")],
            "gpu": [
                _series(host="dc-node-xyz", gpu="0"),
                _series(host="dc-node-xyz", gpu="1"),
            ],
        },
        "_meta": {"range_days": report.RANGE_DAYS},
    }


class FakeResponse:
    def __init__(self, payload):
        self._stream = io.StringIO(json.dumps(payload))

    def __enter__(self):
        return self._stream

    def __exit__(self, *exc):
        return False


def _prom_payload():
    return {
        "status": "success",
        "data": {
            "result": [
                {
                    "metric": {"hostname": "node-abc-123"},
                    "values": [[T0, "50"], [T0 + 3600, "NaN"]],
                }
            ]
        },
    }


class TestQueriesFor:
    def test_fire_athena(self):
        assert report.queries_for(FA) == {
            "cluster": "avg(DCGM_FI_DEV_GPU_UTIL)",
            "active": "count(DCGM_FI_DEV_FB_USED > 1024)",
            "node": "avg by (hostname)(DCGM_FI_DEV_GPU_UTIL)",
            "gpu": "avg by (hostname, gpu)(DCGM_FI_DEV_GPU_UTIL)",
        }

    def test_diadochos_uses_capitalized_hostlabel(self):
        q = report.queries_for(DC)
        assert q["node"] == "avg by (Hostname)(DCGM_FI_DEV_GPU_UTIL)"
        assert q["gpu"] == "avg by (Hostname, gpu)(DCGM_FI_DEV_GPU_UTIL)"
        assert q["active"] == f"count(DCGM_FI_DEV_FB_USED > {report.FB_ACTIVE_THRESHOLD_MIB})"


class TestNodeShort:
    @pytest.mark.parametrize(
        ("hostname", "expected"),
        [
            ("diadochos-hqxzk-gpu-h100-gjfjh", "h100-gjfjh"),
            ("a-b-c", "b-c"),
            ("a-b", "a-b"),
            ("single", "single"),
        ],
    )
    def test_node_short(self, hostname, expected):
        assert report.node_short(hostname) == expected


class TestClusterNames:
    def test_excludes_meta(self):
        assert report.cluster_names({"a": {}, "_meta": {}, "b": {}}) == ["a", "b"]


class TestSummarize:
    def test_math_and_meta_exclusion(self):
        data = {
            FA: {
                "cluster": [
                    {"metric": {}, "values": [[1, 50.0], [2, None], [3, 100.0]]}
                ],
                "active": [{"metric": {}, "values": [[1, 8.0], [2, 8.0]]}],
            },
            "_meta": {},
        }
        rows = report.summarize(data)
        assert len(rows) == 1
        row = rows[0]
        assert row["cluster"] == FA
        assert row["gpus"] == 16
        assert row["avg_util_pct"] == 75.0
        assert row["peak_1h_avg_pct"] == 100.0
        assert row["active_gpu_hours"] == 16.0
        total_gpu_hours = report.RANGE_DAYS * 24 * 16
        assert row["pct_window_active"] == round(100 * 16 / total_gpu_hours, 1)


class TestFetchCluster:
    def _run(self, payload=None, forwards=None):
        if forwards is None:
            forwards = {FA: mock.Mock()}
        if payload is None:
            payload = _prom_payload()
        requests = []

        def fake_urlopen(req, timeout=None, context=None):
            requests.append(req)
            return FakeResponse(payload)

        with mock.patch.object(report.subprocess, "run") as run, mock.patch.object(
            report.urllib.request, "urlopen", side_effect=fake_urlopen
        ), mock.patch.object(report.json, "load", side_effect=lambda _r: payload):
            run.return_value = mock.Mock(stdout="token-123\n")
            result = report.fetch_cluster(FA, "/tmp/kc", forwards)
        return result, requests

    def test_fetches_all_queries_and_normalizes(self):
        result, requests = self._run()
        assert set(result) == {"cluster", "active", "node", "gpu"}
        assert len(requests) == 4
        assert all(req.headers["Authorization"] == "Bearer token-123" for req in requests)
        assert all("step=3600" in req.full_url for req in requests)
        series = result["cluster"][0]
        assert series["metric"]["host"] == "node-abc-123"
        assert "hostname" not in series["metric"]
        assert series["values"] == [[T0, 50.0], [T0 + 3600, None]]

    def test_reuses_existing_forward(self):
        forwards = {FA: mock.Mock()}
        with mock.patch.object(
            report, "start_forward"
        ) as start, mock.patch.object(report.subprocess, "run"), mock.patch.object(
            report.urllib.request, "urlopen",
            side_effect=lambda *a, **k: FakeResponse(_prom_payload()),
        ), mock.patch.object(report.json, "load", side_effect=lambda _r: _prom_payload()):
            report.fetch_cluster(FA, "/tmp/kc", forwards)
        start.assert_not_called()

    def test_starts_forward_when_port_unreachable(self):
        with mock.patch.object(
            report.socket, "create_connection", side_effect=OSError
        ) as conn, mock.patch.object(
            report, "start_forward"
        ) as start, mock.patch.object(
            report.subprocess, "run"
        ), mock.patch.object(
            report.urllib.request, "urlopen",
            side_effect=lambda *a, **k: FakeResponse(_prom_payload()),
        ), mock.patch.object(report.json, "load", side_effect=lambda _r: _prom_payload()):
            report.fetch_cluster(FA, "/tmp/kc", forwards={})
        conn.assert_called_once_with(("127.0.0.1", report.FA_PORT), timeout=1)
        start.assert_called_once_with("/tmp/kc", report.FA_PORT)

    def test_error_status_raises(self):
        payload = {"status": "error", "data": {}}
        with pytest.raises(RuntimeError, match="failed"):
            self._run(payload=payload)


class TestStartForward:
    def test_success(self):
        proc = mock.Mock()
        with mock.patch.object(report.subprocess, "Popen", return_value=proc) as popen, \
                mock.patch.object(report.socket, "create_connection") as conn:
            result = report.start_forward("/tmp/kc", 9090)
        assert result is proc
        popen.assert_called_once_with(
            ["kubectl", "--kubeconfig", "/tmp/kc", "-n", "openshift-monitoring",
             "port-forward", "svc/prometheus-k8s", "9090:9091"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        conn.assert_called_once_with(("127.0.0.1", 9090), timeout=2)

    def test_early_exit_raises(self):
        proc = mock.Mock()
        proc.poll.return_value = 0
        with mock.patch.object(report.subprocess, "Popen", return_value=proc), \
                mock.patch.object(report.socket, "create_connection",
                                  side_effect=OSError):
            with pytest.raises(RuntimeError, match="exited early"):
                report.start_forward("/tmp/kc", 9090)

    def test_timeout_terminates_and_raises(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        t0 = time.time()
        with mock.patch.object(report.subprocess, "Popen", return_value=proc), \
                mock.patch.object(report.socket, "create_connection",
                                  side_effect=OSError), \
                mock.patch.object(report.time, "time",
                                  side_effect=[t0, t0 + 46]), \
                mock.patch.object(report.time, "sleep"):
            with pytest.raises(RuntimeError, match="did not become ready"):
                report.start_forward("/tmp/kc", 9090)
        proc.terminate.assert_called_once_with()


class TestRender:
    def _render(self, tmp_path, monkeypatch, data=None):
        out = tmp_path / "report.html"
        monkeypatch.setattr(report, "OUTPUT", out)
        monkeypatch.setattr(report, "DATA_OUTPUT", tmp_path / "data.json")
        if data is None:
            data = _sample_data()
        with mock.patch.object(
            report.plotly.offline, "get_plotlyjs", return_value="/*plotlyjs*/"
        ):
            report.render(data)
        return out.read_text()

    def test_summary_table_and_figures(self, tmp_path, monkeypatch):
        html = self._render(tmp_path, monkeypatch)
        assert "<table" in html
        assert FA in html and DC in html
        for div in ("c1", "c2", "c3"):
            assert f'id="{div}"' in html
            assert f'Plotly.newPlot("{div}"' in html
        assert "/*plotlyjs*/" in html
        assert f"x {report.CLUSTERS[FA]['node']}" in html
        assert f"x {report.CLUSTERS[DC]['node']}" in html

    def test_single_cluster_skips_subplots(self, tmp_path, monkeypatch):
        data = {FA: _sample_data()[FA], "_meta": {}}
        html = self._render(tmp_path, monkeypatch, data)
        assert FA in html and DC not in html


class TestMain:
    def _isolate(self, tmp_path, monkeypatch):
        monkeypatch.setattr(report, "DATA_OUTPUT", tmp_path / "data.json")
        monkeypatch.setattr(report, "OUTPUT", tmp_path / "report.html")
        return tmp_path

    def test_fetch_path_writes_data_and_renders(self, tmp_path, monkeypatch, capsys):
        self._isolate(tmp_path, monkeypatch)
        monkeypatch.setattr(sys, "argv", ["prog", "/tmp/fa.kc", "/tmp/dc.kc"])
        fetched = []
        with mock.patch.object(
            report, "fetch_cluster",
            side_effect=lambda name, kc, fwd: fetched.append(name) or _sample_data()[name],
        ):
            report.main()
        assert fetched == [FA, DC]
        payload = json.loads((tmp_path / "data.json").read_text())
        assert payload["_meta"]["range_days"] == report.RANGE_DAYS
        assert payload["_meta"]["step_seconds"] == report.STEP_SECONDS
        assert (tmp_path / "report.html").exists()

    def test_only_fetches_selected_cluster(self, tmp_path, monkeypatch):
        self._isolate(tmp_path, monkeypatch)
        monkeypatch.setattr(sys, "argv",
                            ["prog", "/tmp/fa.kc", "/tmp/dc.kc", "--only", DC])
        fetched = []
        with mock.patch.object(
            report, "fetch_cluster",
            side_effect=lambda name, kc, fwd: fetched.append(name) or _sample_data()[name],
        ):
            report.main()
        assert fetched == [DC]

    def test_no_fetch_renders_saved_data(self, tmp_path, monkeypatch):
        self._isolate(tmp_path, monkeypatch)
        (tmp_path / "data.json").write_text(json.dumps(_sample_data()))
        monkeypatch.setattr(sys, "argv", ["prog", "--no-fetch"])
        report.main()
        assert (tmp_path / "report.html").exists()

    def test_no_fetch_with_only_filters(self, tmp_path, monkeypatch):
        self._isolate(tmp_path, monkeypatch)
        (tmp_path / "data.json").write_text(json.dumps(_sample_data()))
        monkeypatch.setattr(sys, "argv",
                            ["prog", "--no-fetch", "--only", FA])
        report.main()
        html = (tmp_path / "report.html").read_text()
        assert FA in html and DC not in html

    def test_missing_kubeconfig_errors(self, tmp_path, monkeypatch):
        self._isolate(tmp_path, monkeypatch)
        monkeypatch.setattr(sys, "argv", ["prog"])
        with pytest.raises(SystemExit):
            report.main()
