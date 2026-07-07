"""지식 레이어·판단 루프·학습 루프 회귀 테스트."""
import os, sys, pytest
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)
from runtime.store import OntologyStore
from runtime.gateway import ActionGateway, GatewayError
from runtime.decision import JudgmentLoop, NoGroundsError
from runtime.feedback import LearningLoop
from runtime.kb import KnowledgeBase

def loop():
    s = OntologyStore(os.path.join(BASE, "domains/ad-reporting"),
                      os.path.join(BASE, "runtime/sample-instances.ttl"))
    gw = ActionGateway(s)
    return s, gw, JudgmentLoop(s, gw, os.path.join(BASE, "knowledge"))

def test_expired_doc_never_grounds_answer():
    _, _, l = loop()
    a = l.answer("계정 인증 만료 시 재연결 절차 규정이 뭐야?")
    assert a["confidence"] == "none" and a["expiredEvidence"]

def test_policy_answer_carries_citation():
    _, _, l = loop()
    a = l.answer("전달 후 재생성 승인이 필요한가?")
    assert a["confidence"] == "policy-grounded"
    assert a["citation"].startswith("policies/report-regeneration.md")

def test_experience_answer_carries_caveat():
    _, _, l = loop()
    a = l.answer("음수 비용 환불 비슷한 사례 있었어?")
    assert a["confidence"] == "precedent-only" and "단정" in a["caveat"]

def test_graph_answer_includes_rule_grounds():
    _, _, l = loop()
    a = l.answer("run2가 왜 막혔어?")
    assert "rule:R-01" in a["grounds"] and a["blockedBy"] == ["case1"]

def test_act_without_grounds_blocked_before_gateway():
    _, gw, l = loop()
    with pytest.raises(NoGroundsError):
        l.act("assignCase", "case1", "AI-Agent", grounds=[])
    assert gw.audit.records == []          # 게이트웨이까지 도달 자체를 안 함

def test_expired_doc_as_sole_ground_blocked():
    _, _, l = loop()
    with pytest.raises(NoGroundsError, match="만료 문서"):
        l.act("assignCase", "case1", "AI-Agent", grounds=["policies/account-expiry.md#(구) 절차"])

def test_access_level_filter():
    kb = KnowledgeBase(os.path.join(BASE, "knowledge"))
    assert kb.search("재생성 승인", kind="policy", access=("public",)) == []

def test_learning_loop_detects_gap_and_rule_candidates():
    s, gw, l = loop()
    for _ in range(2):
        try: gw.execute("regenerateReport", "run2", "AI-Agent")
        except GatewayError: pass
    a = l.answer("신규 매체 추가 승인 기준은?")
    ll = LearningLoop(gw.audit, [{"query": "신규 매체 추가 승인 기준은?",
                                  "route": a["route"], "confidence": a["confidence"]}])
    kinds = {i["kind"] for i in (ll.rule_candidates() + ll.knowledge_gaps())}
    assert {"rule-candidate", "knowledge-gap"} <= kinds
