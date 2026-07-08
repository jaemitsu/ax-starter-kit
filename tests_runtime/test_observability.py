"""관측 통합 회귀 테스트 — langfuse 유무와 무관하게 비즈니스 로직이 불변임을 고정한다.
· 미설치 경로: 이 환경 그대로 실행 (데코레이터 no-op)
· 설치 경로: 가짜 langfuse 모듈 주입 + reload, 또는 가짜 클라이언트 주입으로 시뮬레이션
"""
import importlib, os, sys, types, pytest
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)
from runtime.store import OntologyStore
from runtime.gateway import ActionGateway, GatewayError
from runtime.decision import JudgmentLoop
import runtime.observability as obs
import runtime.observability_config as ocfg
from runtime.observability import (LangfuseTracer, instrument,
                                   trace_decision, trace_gateway, trace_query, trace_search)

def fresh():
    s = OntologyStore(os.path.join(BASE, "domains/ad-reporting"),
                      os.path.join(BASE, "runtime/sample-instances.ttl"))
    gw = ActionGateway(s)
    return s, gw, JudgmentLoop(s, gw, os.path.join(BASE, "knowledge"))

@pytest.fixture(autouse=True)
def _reset_global_tracer():
    yield
    obs.set_tracer(None)   # 테스트 간 싱글턴 격리

# ── 가짜 langfuse v3 클라이언트 (기록형) ──
class FakeSpan:
    def __init__(self, client, name, kw):
        self.client, self.name, self.kw, self.updates, self.ended = client, name, kw, [], False
    def update(self, **kw): self.updates.append(kw)
    def merged(self):
        out = {}
        for u in self.updates: out.update(u)
        return out
    def __enter__(self): return self
    def __exit__(self, *exc): self.ended = True; return False

class FakeClient:
    def __init__(self, fail=False):
        self.spans, self.fail, self.starts, self.flushed = [], fail, 0, 0
    def start_as_current_span(self, name=None, **kw):
        self.starts += 1
        if self.fail: raise RuntimeError("SDK boom")
        sp = FakeSpan(self, name, kw); self.spans.append(sp); return sp
    def flush(self): self.flushed += 1
    def by_name(self, name):
        return [s for s in self.spans if s.name == name]

def live_tracer(client, threshold=3, cooldown=100.0, clock=None, sample_rate=1.0):
    cfg = ocfg.ObservabilityConfig(enabled=True, public_key="pk", secret_key="sk",
                                   cb_threshold=threshold, cb_cooldown_sec=cooldown,
                                   sample_rate=sample_rate)
    return LangfuseTracer(config=cfg, client=client, clock=clock)

# ── ① langfuse 미설치: 완전 no-op ──
@pytest.mark.skipif(obs.LANGFUSE_AVAILABLE, reason="langfuse 설치 환경에서는 미설치 경로 검증 불가")
def test_import_without_langfuse_disabled_tracer():
    tr = obs.get_tracer(refresh=True)
    assert tr.enabled is False and tr.client is None
    with tr.trace() as h:               # 전부 no-op이어도 CM 프로토콜은 성립
        h.update(output={"x": 1})
        with tr.span("kb.search") as h2: h2.update(level="ERROR")
    tr.event("e"); tr.score("s", 1.0); tr.flush(); tr.shutdown()

def test_noop_decorators_preserve_return_and_exception():
    @trace_decision
    def answer(self, query): return {"route": "graph", "confidence": "graph-grounded", "grounds": ["graph:x"]}
    @trace_search
    def search(self, query, k=3, kind=None): return [{"cite": "a#b", "score": 1.0, "expired": False}]
    @trace_query(name="custom.route")
    def route(self, query): raise ValueError("원본 예외 그대로")
    assert answer(None, "q")["route"] == "graph"
    assert search(None, "q", kind="policy")[0]["cite"] == "a#b"
    with pytest.raises(ValueError, match="원본 예외 그대로"):
        route(None, "q")

def test_gateway_error_propagates_through_decorator():
    s, gw, _ = fresh()
    instrument(gateway=gw)
    with pytest.raises(GatewayError, match="R-05"):        # 예외 타입·메시지 불변
        gw.execute("regenerateReport", "run2", "AI-Agent")
    assert gw.audit.records[-1]["result"] == "rejected"    # 감사 기록도 그대로

# ── ② instrument(): 실 객체 무수정 계측 — 행동 동일성 ──
def test_instrument_does_not_change_behavior():
    # 비계측 기준선
    s0, gw0, l0 = fresh()
    eff0 = l0.act("assignCase", "case1", "AI-Agent", grounds=["graph:case1"], assignee="QA")
    with pytest.raises(GatewayError) as e0:
        gw0.execute("regenerateReport", "run2", "AI-Agent")
    # 계측본
    s1, gw1, l1 = fresh()
    done = instrument(store=s1, gateway=gw1, loop=l1, kb=l1.kb, router=l1.router)
    assert "ActionGateway.execute" in done and "JudgmentLoop.act" in done
    eff1 = l1.act("assignCase", "case1", "AI-Agent", grounds=["graph:case1"], assignee="QA")
    with pytest.raises(GatewayError) as e1:
        gw1.execute("regenerateReport", "run2", "AI-Agent")
    assert eff0 == eff1 and str(e0.value) == str(e1.value)
    assert gw0.audit.count(result="success") == gw1.audit.count(result="success") == 1
    a0, a1 = l0.answer("전달 후 재생성 승인이 필요한가?"), l1.answer("전달 후 재생성 승인이 필요한가?")
    assert a0 == a1

def test_instrument_is_idempotent():
    _, gw, l = fresh()
    first = instrument(gateway=gw, loop=l)
    second = instrument(gateway=gw, loop=l)   # 이미 계측됨 → 건너뜀 (이중 스팬 방지)
    assert first and second == []
    gw.execute("assignCase", "case1", "AI-Agent", assignee="QA")   # 여전히 정상 동작

# ── ③ 서킷브레이커: SDK 오류가 비즈니스를 못 건드린다 ──
def test_circuit_breaker_opens_halfopens_and_recovers(caplog):
    now = [0.0]
    client = FakeClient(fail=True)
    tr = live_tracer(client, threshold=3, cooldown=100.0, clock=lambda: now[0])
    wrapped = trace_query(lambda self, query: {"route": "graph"}, tracer=tr)
    import logging
    with caplog.at_level(logging.WARNING, logger="ax.observability"):
        for _ in range(5):
            assert wrapped(None, "q")["route"] == "graph"   # SDK가 죽어도 결과 불변
    assert client.starts == 3                # 임계 도달 후 SDK 호출 중단 (서킷 오픈)
    assert sum("서킷브레이커" in r.message for r in caplog.records) == 1   # 경고는 1회만
    now[0] = 101.0                           # 쿨다운 경과 → half-open 재시도 1회
    wrapped(None, "q"); assert client.starts == 4
    wrapped(None, "q"); assert client.starts == 4    # 재실패 → 다시 오픈
    client.fail = False
    now[0] = 250.0                           # (101+100) 재쿨다운 경과 → 성공 → 서킷 닫힘
    wrapped(None, "q"); assert client.starts == 5 and tr._fails == 0
    wrapped(None, "q"); assert client.starts == 6    # 정상 관측 재개

def test_sampling_zero_records_nothing():
    client = FakeClient()
    tr = live_tracer(client, sample_rate=0.0)
    wrapped = trace_search(lambda self, query, k=3, kind=None: [], tracer=tr)
    assert wrapped(None, "q") == []
    assert client.starts == 0

# ── ④ 설정 파싱 ──
def test_config_env_parsing(monkeypatch):
    for k in (ocfg.ENV_PUBLIC_KEY, ocfg.ENV_SECRET_KEY, ocfg.ENV_HOST, ocfg.ENV_ENABLED,
              ocfg.ENV_CB_THRESHOLD, ocfg.ENV_CB_COOLDOWN, ocfg.ENV_SAMPLE_RATE):
        monkeypatch.delenv(k, raising=False)
    c = ocfg.load_config()
    assert c.enabled is False and c.host == ocfg.DEFAULT_HOST     # 키 없음 → 비활성
    monkeypatch.setenv(ocfg.ENV_PUBLIC_KEY, "pk"); monkeypatch.setenv(ocfg.ENV_SECRET_KEY, "sk")
    assert ocfg.load_config().enabled is True
    monkeypatch.setenv(ocfg.ENV_ENABLED, "false")
    assert ocfg.load_config().enabled is False                    # 명시적 off 우선
    monkeypatch.setenv(ocfg.ENV_ENABLED, "true")
    monkeypatch.setenv(ocfg.ENV_SAMPLE_RATE, "1.7")
    assert ocfg.load_config().sample_rate == 1.0                  # 상한 클램프
    monkeypatch.setenv(ocfg.ENV_SAMPLE_RATE, "-0.3")
    assert ocfg.load_config().sample_rate == 0.0                  # 하한 클램프
    monkeypatch.setenv(ocfg.ENV_SAMPLE_RATE, "abc")
    assert ocfg.load_config().sample_rate == ocfg.DEFAULT_SAMPLE_RATE
    monkeypatch.setenv(ocfg.ENV_CB_THRESHOLD, "2"); monkeypatch.setenv(ocfg.ENV_CB_COOLDOWN, "42")
    c = ocfg.load_config()
    assert c.cb_threshold == 2 and c.cb_cooldown_sec == 42.0

# ── ⑤ 가짜 클라이언트: 스팬 이름·입출력이 규약대로 기록되는가 ──
def test_spans_carry_expected_names_and_io():
    client = FakeClient()
    tr = live_tracer(client)
    s, gw, l = fresh()
    instrument(gateway=gw, loop=l, kb=l.kb, router=l.router, tracer=tr)

    a = l.answer("전달 후 재생성 승인이 필요한가?")
    names = [sp.name for sp in client.spans]
    assert ocfg.SPAN_DECISION_ANSWER in names and ocfg.SPAN_QUERY_ROUTE in names and ocfg.SPAN_KB_SEARCH in names
    ans = client.by_name(ocfg.SPAN_DECISION_ANSWER)[0]
    assert ans.kw["input"]["query"].startswith("전달 후")
    assert ans.merged()["output"]["confidence"] == a["confidence"] == "policy-grounded"
    kb_sp = client.by_name(ocfg.SPAN_KB_SEARCH)[0]
    assert kb_sp.merged()["output"]["hits"][0]["cite"].startswith("policies/report-regeneration.md")

    eff = l.act("assignCase", "case1", "AI-Agent", grounds=["graph:case1"], assignee="QA")
    gw_sp = client.by_name(ocfg.SPAN_GATEWAY_EXECUTE)[0]
    assert gw_sp.kw["input"] == {"action": "assignCase", "target": "case1", "actor": "AI-Agent"}
    m = gw_sp.merged()
    assert m["output"]["result"] == "success" and m["output"]["effect"] == eff
    assert m["output"]["preconditionEval"] == "pass"              # 감사 레코드에서 단계 캡처
    assert client.by_name(ocfg.SPAN_DECISION_ACT)[0].kw["input"]["grounds"] == ["graph:case1"]

def test_gateway_rejection_recorded_as_warning():
    client = FakeClient()
    tr = live_tracer(client)
    s, gw, _ = fresh()
    instrument(gateway=gw, tracer=tr)
    with pytest.raises(GatewayError, match="R-05"):
        gw.execute("regenerateReport", "run2", "AI-Agent")
    m = client.by_name(ocfg.SPAN_GATEWAY_EXECUTE)[0].merged()
    assert m["level"] == "WARNING" and "R-05" in m["output"]["reason"]
    assert m["output"]["result"] == "rejected"
    assert "preconditionEval" in m["output"]                      # fail: 사유도 감사에서 캡처
    assert client.by_name(ocfg.SPAN_GATEWAY_EXECUTE)[0].ended     # 예외에도 스팬은 닫힌다

def test_root_trace_and_nesting():
    client = FakeClient()
    tr = live_tracer(client)
    with tr.trace(metadata={"session": "t1"}) as root:
        root.update(output={"done": True})
        with tr.span(ocfg.SPAN_KB_SEARCH, input={"query": "q"}) as h:
            h.update(output={"hits": []})
    assert client.spans[0].name == ocfg.TRACE_JUDGMENT_LOOP
    assert client.spans[0].kw["metadata"] == {"session": "t1"}
    assert all(sp.ended for sp in client.spans)
    tr.flush(); assert client.flushed == 1

# ── ⑥ 가짜 langfuse 모듈 주입 + reload: '설치됨' 경로의 감지·초기화 ──
def test_fake_langfuse_module_detection_v3(monkeypatch):
    created = {}
    fake = types.ModuleType("langfuse")
    class FakeLangfuse:
        def __init__(self, **kw): created.update(kw)
        def start_as_current_span(self, name=None, **kw): return FakeSpan(self, name, kw)
        def flush(self): pass
    fake.Langfuse = FakeLangfuse
    fake.observe = lambda *a, **k: (lambda f: f)
    monkeypatch.setenv(ocfg.ENV_PUBLIC_KEY, "pk-test")
    monkeypatch.setenv(ocfg.ENV_SECRET_KEY, "sk-test")
    monkeypatch.delenv(ocfg.ENV_ENABLED, raising=False)
    monkeypatch.delenv(ocfg.ENV_HOST, raising=False)
    sys.modules["langfuse"] = fake
    try:
        importlib.reload(obs)
        assert obs.LANGFUSE_AVAILABLE is True
        tr = obs.LangfuseTracer()
        assert tr.enabled and tr.mode == "v3"
        assert created["public_key"] == "pk-test" and created["host"] == ocfg.DEFAULT_HOST
        with tr.span("kb.search", input={"q": 1}) as h:
            h.update(output={"n": 0})
    finally:
        sys.modules.pop("langfuse", None)
        importlib.reload(obs)                 # 미설치 상태 복원
    assert obs.LANGFUSE_AVAILABLE is False

def test_fake_v2_client_uses_trace_and_child_spans():
    calls = []
    class V2Span:
        def __init__(self, name): self.name = name
        def span(self, name=None, **kw): calls.append(("span", name)); return V2Span(name)
        def update(self, **kw): calls.append(("update", self.name, kw))
        def end(self, **kw): calls.append(("end", self.name))
    class V2Client:   # v2: start_as_current_span 없음 → trace() 감지
        def trace(self, name=None, **kw): calls.append(("trace", name)); return V2Span(name)
    tr = live_tracer(V2Client())
    assert tr.mode == "v2"
    with tr.span("root") as h:
        with tr.span("child") as h2:
            h2.update(output={"x": 1})
    assert ("trace", "root") in calls and ("span", "child") in calls   # 자식은 부모 경유
    assert ("end", "child") in calls
