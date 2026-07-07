"""Action Gateway·판단 루프 회귀 테스트 — 안전장치가 실제로 작동하는지 고정한다."""
import os, sys, pytest
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)
from runtime.store import OntologyStore
from runtime.gateway import ActionGateway, GatewayError
from runtime.scenario_demo import run_scenario

def fresh():
    s = OntologyStore(os.path.join(BASE, "domains/ad-reporting"),
                      os.path.join(BASE, "runtime/sample-instances.ttl"))
    return s, ActionGateway(s)

def resolve_case(s, gw):
    gw.execute("assignCase", "case1", "AI-Agent", assignee="QA")
    gw.execute("correctAndApprove", "case1", "데이터 QA 담당",
               reason="환불 조정", campaign="camp2", correctedSpend=0, dataset="ds2")
    gw.execute("validate", "ds2", "AI-Agent")

# ── 온톨로지가 행동의 어휘를 제한한다 ──
def test_undefined_action_rejected():
    s, gw = fresh()
    with pytest.raises(GatewayError, match="미정의 액션"):
        gw.execute("deleteEverything", "run2", "AI-Agent")

def test_wrong_target_type_rejected():
    s, gw = fresh()
    with pytest.raises(GatewayError, match="대상 타입 불일치"):
        gw.execute("regenerateReport", "camp2", "AI-Agent")

# ── 권한·자율성 ──
def test_permission_denied_for_ai_on_human_action():
    s, gw = fresh()
    with pytest.raises(GatewayError, match="권한 없음"):
        gw.execute("correctAndApprove", "case1", "AI-Agent", reason="x")

def test_human_approval_action_blocks_ai_even_with_permission():
    s, gw = fresh()
    s.set_status("accK", "만료")
    with pytest.raises(GatewayError, match="권한 없음|사람 승인"):
        gw.execute("reconnectAccount", "accK", "AI-Agent")

def test_auto_then_escalate_budget_consumed():
    s, gw = fresh(); resolve_case(s, gw)
    r = gw.execute("regenerateReport", "run2", "AI-Agent")     # auto 1회
    s.system_complete_run(r["newRun"], "f1")
    with pytest.raises(GatewayError, match="에스컬레이션"):     # 같은 대상 2회째 → 차단
        gw.execute("regenerateReport", "run2", "AI-Agent")
    gw.execute("regenerateReport", r["newRun"], "리포트 담당")   # 사람은 가능 (완료된 새 Run 대상)

# ── R-05: 예외가 행동을 차단한다 ──
def test_open_case_blocks_regeneration():
    s, gw = fresh()
    with pytest.raises(GatewayError, match="R-05"):
        gw.execute("regenerateReport", "run2", "AI-Agent")

def test_failed_dataset_blocks_regeneration():
    s, gw = fresh()
    gw.execute("assignCase", "case1", "AI-Agent")
    gw.execute("correctAndApprove", "case1", "데이터 QA 담당", reason="r")  # 보정만, 재검증 안 함
    with pytest.raises(GatewayError, match="R-02"):
        gw.execute("regenerateReport", "run2", "AI-Agent")

# ── 조건부 승인 ──
def test_post_delivery_regeneration_requires_approval():
    s, gw = fresh(); resolve_case(s, gw)
    r = gw.execute("regenerateReport", "run2", "AI-Agent")
    new_run = r["newRun"]; s.system_complete_run(new_run, "fileX")
    gw.execute("deliverReport", "fileX", "AI-Agent")
    with pytest.raises(GatewayError, match="팀장 승인"):
        gw.execute("regenerateReport", new_run, "리포트 담당")
    gw.execute("regenerateReport", new_run, "리포트 담당", approval="팀장:김OO")  # 승인 첨부 시 통과

def test_vip_delivery_requires_confirmation():
    s, gw = fresh(); resolve_case(s, gw)
    # run을 VIP 광고주로 재배선
    from runtime.store import AX
    s.g.remove((s.uri("run2"), AX.forAdvertiser, None))
    s.add_link("run2", "forAdvertiser", "advV")
    r = gw.execute("regenerateReport", "run2", "AI-Agent")
    s.system_complete_run(r["newRun"], "fileV")
    with pytest.raises(GatewayError, match="VIP"):
        gw.execute("deliverReport", "fileV", "AI-Agent")
    gw.execute("deliverReport", "fileV", "AI-Agent", approval="담당자:박OO")

# ── 멱등성·서킷브레이커 ──
def test_idempotency_blocks_duplicate():
    s, gw = fresh()
    gw.execute("assignCase", "case1", "AI-Agent", assignee="QA")
    with pytest.raises(GatewayError, match="멱등성|오픈이어야"):
        gw.execute("assignCase", "case1", "AI-Agent", assignee="QA")

def test_circuit_breaker_degrades_to_human_approval():
    s, gw = fresh()
    for _ in range(3):
        with pytest.raises(GatewayError):
            gw.execute("regenerateReport", "run2", "AI-Agent")   # case1 오픈 → 3연속 거부
    assert "regenerateReport" in gw.forced_human
    resolve_case(s, gw)
    with pytest.raises(GatewayError, match="사람 승인"):          # 강등 후엔 조건 충족해도 AI 불가
        gw.execute("regenerateReport", "run2", "AI-Agent")

# ── 감사 가능성 ──
def test_every_execution_is_audited_with_grounds():
    s, gw = fresh()
    try: gw.execute("regenerateReport", "run2", "AI-Agent")
    except GatewayError: pass
    rec = gw.audit.records[-1]
    assert rec["result"] == "rejected" and "R-05" in rec["reason"]
    assert rec["action"] == "regenerateReport" and rec["actor"] == "AI-Agent"

# ── E2E ──
def test_full_scenario_passes():
    s, gw, log = run_scenario(verbose=False)
    assert s.check_rules() == []
    assert gw.audit.count(result="success") == 5 and gw.audit.count(result="rejected") == 1
