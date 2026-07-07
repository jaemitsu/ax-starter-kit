"""E2E 시나리오: Grounded Decision Loop 5단계.
질문: "어제 A광고주 리포트 왜 안 나갔어?" → 진단 → 예외 해결 → 재생성 → 전달.
python runtime/scenario_demo.py 로 실행."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from runtime.store import OntologyStore
from runtime.gateway import ActionGateway, GatewayError

def run_scenario(verbose=True):
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    s = OntologyStore(os.path.join(base, "domains/ad-reporting"),
                      os.path.join(base, "runtime/sample-instances.ttl"))
    gw = ActionGateway(s)
    log = []
    def p(msg):
        log.append(msg)
        if verbose: print(msg)

    p("❓ 질문: 어제 A광고주 리포트 왜 안 나갔어?\n")

    # ① Ground — 대상 객체와 상태 확정 (Graph)
    run = s.get_object("run2")
    p(f"① Ground: ReportRun 'run2' status={run['properties']['status']}, "
      f"failureReason={run['properties']['failureReason']}")

    # ② Evidence — 계보 추적 + 차단 예외 (Graph) [+ 실전에서는 MD 정책·Vector 사례 검색 병행]
    lin = s.trace_lineage("run2")
    p(f"② Evidence: 계보 {' → '.join(lin['chain'])}")
    camp = s.get_object("camp2")
    p(f"   원인 후보: camp2.spend={camp['properties']['spend']} (음수 — 환불 조정 추정)")
    blocked = s.blocking_cases("run2")
    p(f"   차단 예외: {blocked} (status={s.status(blocked[0])})")

    # ③ Rule Check — 발동 중인 규칙 (Rule Engine)
    viols = s.check_rules()
    p(f"③ Rule Check: {[(v['rule'], v['focus']) for v in viols]}")

    # ④ Decide & Act — Gateway를 통한 행동 (자율성·권한·승인 집행)
    p("\n④ Decide & Act:")
    try:
        gw.execute("regenerateReport", "run2", "AI-Agent")
    except GatewayError as e:
        p(f"   AI 재생성 시도 → 거부: {e}")
    gw.execute("assignCase", "case1", "AI-Agent", assignee="데이터 QA 담당")
    p("   AI: case1을 데이터 QA 담당에게 배정 (권한 내 행동)")
    gw.execute("correctAndApprove", "case1", "데이터 QA 담당",
               reason="카카오 환불 조정 확인 — 원본 보존, 리포트용 보정", campaign="camp2",
               correctedSpend=0, dataset="ds2")
    p("   사람(QA): 보정 승인 — camp2.spend→0, ds2→검증 대기, case1→해결")
    r = gw.execute("validate", "ds2", "AI-Agent")
    p(f"   AI: ds2 재검증 → {r['status']} (위반 {len(r['violations'])}건)")
    r = gw.execute("regenerateReport", "run2", "AI-Agent", triggeredBy="AI-Agent")
    new_run = r["newRun"]
    p(f"   AI: 재생성 실행 (auto 1회 이내) → 새 Run '{new_run}'")
    s.system_complete_run(new_run, "file_A_0707")          # 스케줄러 완료 이벤트 (시스템)
    p(f"   [시스템] {new_run} 완료, ReportFile 'file_A_0707' 생성")
    gw.execute("deliverReport", "file_A_0707", "AI-Agent")
    p("   AI: 표준 광고주 → 자동 전달 완료")

    # ⑤ Record — 감사 로그
    p(f"\n⑤ Record: 감사 로그 {len(gw.audit.records)}건")
    for rec in gw.audit.records:
        p(f"   [{rec['result']}] {rec['actor']} → {rec['action']}({rec['target']})"
          + (f" | {rec.get('reason','')}" if rec["result"] == "rejected" else ""))

    # 사후 불변식 확인
    assert s.status("run2") == "재생성" and s.status(new_run) == "완료"
    assert s.status("case1") == "해결" and s.status("ds2") == "정상"
    assert s.status("file_A_0707") == "전달됨"
    assert [v for v in s.check_rules()] == []          # 위반 전건 해소
    p("\n✅ 시나리오 완료 — 최종 상태 불변식 및 규칙 위반 0건 확인")
    return s, gw, log

if __name__ == "__main__":
    run_scenario()
