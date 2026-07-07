"""판단 루프 v2 데모 — 세 지식 레이어를 모두 사용하는 완전한 Grounded Decision Loop.
python runtime/scenario_v2.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from runtime.store import OntologyStore
from runtime.gateway import ActionGateway
from runtime.decision import JudgmentLoop, NoGroundsError

def run(verbose=True):
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    s = OntologyStore(os.path.join(base, "domains/ad-reporting"),
                      os.path.join(base, "runtime/sample-instances.ttl"))
    gw = ActionGateway(s)
    loop = JudgmentLoop(s, gw, os.path.join(base, "knowledge"))
    log = []
    def p(m):
        log.append(m)
        if verbose: print(m)

    p("── Q1 (Graph 라우팅): 'run2가 왜 막혔어?'")
    a = loop.answer("run2가 왜 막혔어?")
    p(f"   [{a['route']}] {a['answer']}")
    p(f"   근거: {a['grounds']}")
    assert a["route"] == "graph" and "case1" in str(a["blockedBy"])

    p("\n── Q2 (정책 라우팅): '전달 후 재생성 승인이 필요한가?'")
    a = loop.answer("전달 후 재생성 승인이 필요한가?")
    p(f"   [{a['route']}] {a['answer'][:120]}")
    p(f"   인용: {a.get('citation')} (confidence={a['confidence']})")
    assert a["route"] == "policy" and a["confidence"] == "policy-grounded"
    policy_cite = a["citation"]

    p("\n── Q3 (경험 라우팅): '음수 비용 비슷한 사례 있었어?'")
    a = loop.answer("음수 비용 환불 비슷한 사례 있었어?")
    p(f"   [{a['route']}] {a.get('citation')} — {a['answer'][:100]}")
    p(f"   주의: {a.get('caveat')}")
    assert a["route"] == "experience" and a["confidence"] == "precedent-only"

    p("\n── Q4 (만료 문서 안전장치): '계정 만료 재연결 절차가 어떻게 되지?'")
    a = loop.answer("계정 인증 만료 시 재연결 절차 규정이 뭐야?")
    p(f"   [{a['route']}] confidence={a['confidence']} | {a['answer'][:90]}")
    p(f"   만료 근거 제외됨: {a.get('expiredEvidence')}")

    p("\n── 행동: 근거 없는 행동은 게이트웨이 이전에 차단")
    try:
        loop.act("assignCase", "case1", "AI-Agent", grounds=[])
    except NoGroundsError as e:
        p(f"   차단 OK: {str(e)[:70]}")

    p("\n── 행동: 근거를 첨부한 정상 처리 흐름 (감사 로그에 근거 ID 기록)")
    loop.act("assignCase", "case1", "AI-Agent",
             grounds=["graph:run2", "rule:R-01", "case:cases/2026-03-kakao-refund.md"], assignee="QA")
    loop.act("correctAndApprove", "case1", "데이터 QA 담당",
             grounds=["policies/data-correction.md#절차"],
             reason="카카오 환불 조정 확인 — 정책에 따라 원본 보존, 리포트용 0 처리",
             campaign="camp2", correctedSpend=0, dataset="ds2")
    loop.act("validate", "ds2", "AI-Agent", grounds=["rule:R-01", "policies/data-correction.md#절차"])
    r = loop.act("regenerateReport", "run2", "AI-Agent",
                 grounds=["graph:run2", policy_cite])
    s.system_complete_run(r["newRun"], "fileA")
    loop.act("deliverReport", "fileA", "AI-Agent", grounds=["graph:" + r["newRun"]])
    p(f"   완료 — 새 Run {r['newRun']}, 파일 전달됨")

    p("\n── 감사 로그의 근거 추적성")
    for rec in gw.audit.records:
        if rec["result"] == "success":
            p(f"   {rec['action']}({rec['target']}) ← 근거 {rec['grounds']}")
    assert all(rec.get("grounds") for rec in gw.audit.records if rec["result"] == "success")
    assert s.check_rules() == []
    p("\n✅ 판단 루프 v2 완주 — 전 성공 행동에 근거 ID 존재, 규칙 위반 0건")
    return s, gw, loop, log

if __name__ == "__main__":
    run()
