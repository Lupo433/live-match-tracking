import pytest
from fastapi.testclient import TestClient

from livematch.api import create_app
from livematch.catalog import default_catalog

from .conftest import ROOT


@pytest.fixture(scope="module")
def client():
    app = create_app(default_catalog(ROOT / "data"))
    with TestClient(app) as c:
        yield c


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<canvas" in r.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_list_matches(client):
    r = client.get("/api/matches").json()
    ids = [m["match_id"] for m in r["matches"]]
    assert "sample_game_1" in ids and "synthetic" in ids


def test_match_metadata_and_events(client):
    r = client.get("/api/matches/sample_game_1").json()
    assert r["match"]["fps"] == 25
    assert len(r["players"]) == 28
    ev = client.get("/api/matches/sample_game_1/events").json()
    assert len(ev) == r["n_events"] > 0
    assert client.get("/api/matches/nope").status_code == 404


def _recv_until(ws, mtype, limit=200):
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == mtype:
            return m
    raise AssertionError(f"no {mtype} message")


def test_websocket_streams_moving_frames(client):
    with client.websocket_connect("/ws?match_id=sample_game_1") as ws:
        init = _recv_until(ws, "init")
        assert init["match"]["match_id"] == "sample_game_1"
        n = len(init["players"])
        ws.send_json({"cmd": "set_speed", "speed": 10})
        frames = [_recv_until(ws, "frame") for _ in range(8)]
        f0, f1 = frames[0], frames[-1]
        assert len(f0["pl"]) == 2 * n
        assert f1["f"] > f0["f"]  # time advances
        assert f1["pl"] != f0["pl"]  # players move
        assert f1["speed"] == 10


def test_websocket_commands(client):
    with client.websocket_connect("/ws?match_id=synthetic&autoplay=0") as ws:
        _recv_until(ws, "init")
        m = _recv_until(ws, "frame")
        assert m["playing"] is False and m["f"] == 0
        ws.send_json({"cmd": "seek", "minute": 2})
        for _ in range(50):
            m = _recv_until(ws, "frame")
            if m["f"] == 3000:
                break
        assert m["f"] == 3000
        ws.send_json({"cmd": "bogus"})
        assert _recv_until(ws, "error")["type"] == "error"
        ws.send_json({"cmd": "select_match", "match_id": "sample_game_1"})
        init = _recv_until(ws, "init")
        assert init["match"]["match_id"] == "sample_game_1"


def test_summary_endpoint(client):
    r = client.get("/api/matches/sample_game_1/summary")
    assert r.status_code == 200
    st = r.json()["stats"]
    assert st["frame"] == 2999
    assert st["poss"]["home"] + st["poss"]["away"] == pytest.approx(1.0)
    assert len(st["players"]) >= 22


def test_report_endpoint_and_cli(client, tmp_path, monkeypatch):
    r = client.get("/api/matches/sample_game_1/report")
    assert r.status_code == 200
    html = r.text
    assert html.startswith("<!doctype html>") and "</html>" in html
    assert "Modelli dimostrativi" in html and "<svg" in html
    assert "http://" not in html.split("<footer>")[0].replace('xmlns="http://www.w3.org', "")
    # CLI
    import sys

    from livematch import report

    out = tmp_path / "r.html"
    monkeypatch.setattr(sys, "argv", ["report", "sample_game_1", "-o", str(out)])
    report.main()
    assert out.read_text().count("<svg") >= 5


def test_pass_network_and_models_endpoints(client):
    net = client.get("/api/matches/sample_game_1/passnetwork").json()
    assert set(net) == {"home", "away"} and net["home"]["nodes"]
    early = client.get("/api/matches/sample_game_1/passnetwork?until_frame=100").json()
    assert sum(n["n"] for n in early["home"]["nodes"]) < sum(n["n"] for n in net["home"]["nodes"])
    m = client.get("/api/models").json()
    assert m["xg"]["label"] == "modello dimostrativo" and m["xg"]["n_shots"] > 0
    assert len(m["xt"]["grid"]) == m["xt"]["ny"]
