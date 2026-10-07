"""CRIT27 live-check fixes (D1..D16). H is enabled in-process by appending the journal trader to service.TRADERS."""
import pytest
from fastapi.testclient import TestClient

from app import service
from app.main import app

H_META = {"id": "H", "file": "journal:journal_verified.json", "role": "real_journal",
          "blurb": "Real Bitget futures positions from a public journal (53 verified trades, underpowered)"}


@pytest.fixture()
def hc(monkeypatch):
    monkeypatch.setattr(service, "TRADERS", list(service.TRADERS) + [H_META])
    service._load_static.cache_clear()
    yield TestClient(app)
    service._load_static.cache_clear()


def chat(c, tid, msg, lang=None):
    body = {"trader": tid, "message": msg, "history": []}
    if lang:
        body["lang"] = lang
    return c.post("/api/chat", json=body).json()


def test_d1_weekly_report_for_h_is_200_both_languages(hc):
    for lang in ("en", "zh"):
        r = hc.get(f"/api/report/H?lang={lang}")
        assert r.status_code == 200, r.text
        assert "150" in r.json()["markdown"]          # the label's threshold is quoted, and allowed as a label constant


def test_d1_chat_weekly_review_h(hc):
    r = chat(hc, "H", "Show my weekly review")
    assert r["kind"] == "report" and r["number_lock"] == "passed"


def test_d2_h_provenance_answer_not_refused(hc):
    for m in ("Where do these numbers come from?", "这些数字从哪来的？"):
        r = chat(hc, "H", m)
        assert r["number_lock"] == "passed", r
        assert "150" in r["text"]


def test_label_constants_are_only_the_documented_one():
    from engine.numberlock import LABEL_CONSTANTS, numerals
    allowed = set(LABEL_CONSTANTS) | {float(i) for i in range(0, 11)} | {53.0}
    for lab in (service.LABEL, service.LABEL_BITGET, service.LABEL_JOURNAL, service.LABEL_IMPORT, service.LABEL_PLANTED):
        for _raw, val, _d in numerals(lab):
            assert val in allowed or val in (2.0, 3.0), (lab, val)


def test_d8_validation_doc_ships():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    ignore = (root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "*.md" in ignore and "!VALIDATION.md" in ignore and ignore.index("!VALIDATION.md") > ignore.index("*.md")
    c = TestClient(app)
    r = c.get("/validation")
    assert r.status_code == 200 and "not in this build" not in r.text and "wrong acceptance" in r.text.lower()


def test_d8_losses_shows_after_fix_numbers_from_claims():
    import claims
    from pathlib import Path
    txt = (Path(__file__).resolve().parents[1] / "LOSSES.md").read_text(encoding="utf-8")
    v = claims.values()
    assert v["robustness.ac_court"] == "0.0%" and v["robustness.all_court"] == "0.3%"
    assert f"{v['robustness.ac_court']} (autocorrelated returns) and {v['robustness.all_court']} (all four stresses" in txt
    assert "5 of 7" not in txt and "wallet H" in txt


def test_d16_sources_split_real_groups(monkeypatch):
    from app import judge
    monkeypatch.setattr(service, "TRADERS", list(service.TRADERS) + [H_META])
    names = [d["name"] for d in judge.sources()["data"]]
    assert any("journal" in n for n in names) and any("export" in n for n in names)
    assert sum(d["expected"] for d in judge.sources()["data"]) == len(service.TRADERS)


# ---- D3 / D4 routing ------------------------------------------------------------------------------------------------
def test_d3_chinese_falsify_paraphrase_routes_to_falsify():
    c = TestClient(app)
    for m in ("什么会让这个结论出错？", "什么情况下会错？", "哪些情况会让这个发现不成立？"):
        assert chat(c, "B", m)["intent"] == "falsify", m


def test_d3_chinese_btc_funding_goes_to_market_path(monkeypatch):
    from app import market_data
    assert market_data.is_market_question("BTC现在的资金费率是多少？")
    assert market_data.is_market_question("what's the funding rate on BTC right now?")
    assert not market_data.is_market_question("我的资金费用是多少？")        # no coin, own record
    monkeypatch.setattr(market_data, "chat_answer", lambda m, lang: {"intent": "market", "lang": lang, "kind": "text", "text": "stub", "facts": [],
                                                                      "number_lock": "passed", "llm": "off"})
    assert chat(TestClient(app), "B", "BTC现在的资金费率是多少？")["intent"] == "market"


def test_d4_losing_streak_then_size_is_size_after_loss_not_streak():
    from app import chat as chat_mod
    for q in ("did my losing streaks make me bet bigger afterwards", "do I bet bigger after losses", "连亏之后我会不会加大仓位？"):
        assert chat_mod.SIZE_AFTER_LOSS(q), q
    for q in ("what is my longest losing streak?", "how many losses in a row did I have", "what is my win rate"):
        assert not chat_mod.SIZE_AFTER_LOSS(q), q
    c = TestClient(app)
    r = chat(c, "B", "did my losing streaks make me bet bigger afterwards")
    assert r["intent"] == "habit" and "size after a loss" in r["text"] and "Longest losing streak" not in r["text"]
    assert chat(c, "B", "what is my longest losing streak?")["text"].startswith("Longest losing streak")


# ---- D7 / thesis / strip -------------------------------------------------------------------------------------------
def test_d7_trade_note_says_real_journal_for_h(hc):
    j = hc.get("/api/trip/H/3").json()
    assert "simulated" not in j["fills_note"] and "real journal" in j["fills_note"]
    f = hc.get("/api/trip/F/10").json()
    assert "simulated round trips only" in f["fills_note"]


def test_thesis_h_never_says_at_least_zero(hc):
    for lang in ("en", "zh"):
        txt = " ".join(hc.get("/api/thesis/H").json()["text"][lang])
        assert "at least 0 " not in txt and "至少 0 " not in txt
        assert "10" in txt


def test_h_strip_uses_closed_positions_wording():
    js = open("app/static/home.js", encoding="utf-8").read()
    assert 'r.trader.provenance === "SIM_PLANTED" ? "simulated, " : "closed positions, "' in js


# ---- D6 Qwen visibility (no network: parse_intent is stubbed) ---------------------------------------------------------
def test_d6_trace_names_qwen_planner_when_used(monkeypatch):
    from app import llm
    monkeypatch.setenv("QWEN_API_KEY", "test-not-a-key")
    monkeypatch.setattr(llm, "parse_intent", lambda *a, **k: "habit")
    from app import qa_chat
    monkeypatch.setattr(qa_chat, "qwen_plan", lambda *a, **k: None)
    monkeypatch.setattr(qa_chat, "qwen_phrase", lambda *a, **k: None)
    r = chat(TestClient(app), "B", "blah blah qwxz")
    names = [s["name"] for s in r["steps"]]
    assert any(n.startswith("Qwen planner (") and "'habit'" in n for n in names), names
    assert r["intent"] == "habit"
    monkeypatch.delenv("QWEN_API_KEY")
    r2 = chat(TestClient(app), "B", "blah blah qwxz")
    assert not any("Qwen" in s["name"] for s in (r2.get("steps") or []))


def test_d6_home_strip_shows_qwen_on_text():
    js = open("app/static/strip.js", encoding="utf-8").read()
    assert '"Qwen"' in js and '"on"' in js


# ---- D11 chips -------------------------------------------------------------------------------------------------------
def test_d11_chips_have_visible_effect():
    plain = service.gate_check("t27", "B", "Buy $5k rNVDA", None, ["after_loss"])
    closed = service.gate_check("t27", "B", "Buy $5k rNVDA", None, ["closed_market"])
    fund = service.gate_check("t27", "B", "Buy $5k rNVDA", None, ["high_funding"])
    assert closed["similar"]["filters"]["closed_market"] is True
    assert any("outside the US cash session" in n["en"] for n in closed["similar"]["notes"])
    assert closed["similar"]["n"] <= service.gate_check("t27", "B", "Buy $5k rNVDA", None, [])["similar"]["n"]
    assert any("no funding rate per trade" in n["en"] for n in fund["similar"]["notes"]) and all(n["zh"] for n in fund["similar"]["notes"])
    assert plain["similar"]["notes"] == []


def test_closed_market_filter_keeps_only_off_hours_trips():
    from engine import detectors3
    from app import gate_plus
    out = service.gate_check("t27b", "B", "Buy $5k rNVDA", None, ["closed_market", "bigger"])
    ts = service._load("B")[3]
    assert all(detectors3.is_off_hours(ts_t) for ts_t in
               [r["t_open_ms"] for r in out["similar"]["rows"]])


# ---- Chinese leftovers ------------------------------------------------------------------------------------------------
def test_zh_labels_and_chat_have_no_english_label():
    import re
    for en, zh in service.LABEL_ZH.items():
        assert re.search(r"[一-鿿]", zh) and en != zh
    c = TestClient(app)
    src = chat(c, "B", "这个数据是哪来的？")["text"]
    assert "Hyperliquid" in src and "hand-picked" not in src
    rep = chat(c, "B", "给我看这周的复盘")["markdown"]
    assert "hand-picked" not in rep and rep.startswith("# 复盘报告：钱包 B")
    g = chat(c, "B", "检查一个下单想法：买 2万 rNVDA")["text"]
    assert "buy" not in g and "买" in g


def test_zh_i18n_covers_listed_strings():
    js = open("app/static/i18n.js", encoding="utf-8").read()
    for frag in ("WOULD_NOT_PASS", "_RB_STATE_ZH", "stationary (\d+)%", "Daily RSI\(14\)", "closed positions, (\d+) round trips",
                 "Planted traders from engine", "intact (hash-chained)", "No Bitget skill has been asked yet"):
        assert frag in js, frag


def test_d15_evidence_and_wf_table_scroll():
    ev = open("app/static/evidence.html", encoding="utf-8").read()
    assert "pre{overflow-x:auto" in ev and "#skills{overflow-x:auto}" in ev
    wf = open("app/static/wf_toggle.js", encoding="utf-8").read()
    assert '<div class="scroll"><table><caption class="vh">In-sample' in wf and "</tbody></table></div>" in wf
