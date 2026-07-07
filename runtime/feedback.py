"""학습 루프 — 감사 로그와 질의 이력을 분석해 개선 후보를 환류한다.
산출: ①규칙·프로세스 개선 후보 ②자율성 재검토 후보 ③지식 갭(문서화 과제) ④검색 평가셋 보강 후보.
운영에서는 월간 배치로 돌려 온톨로지 유지보수 모드(Phase 7)의 입력으로 쓴다.
"""
import re
from collections import Counter, defaultdict

class LearningLoop:
    def __init__(self, audit, query_log=None):
        self.audit = audit
        self.query_log = query_log or []   # [{"query":..., "route":..., "grounds":[...], "confidence":...}]

    def rule_candidates(self, min_count=2):
        """같은 사유로 반복 거부되는 패턴 → 규칙/프로세스 개선 후보."""
        pat = Counter()
        samples = defaultdict(list)
        for r in self.audit.records:
            if r["result"] != "rejected": continue
            reason = re.sub(r"\[.*?\]|'[^']*'", "_", r.get("reason", ""))  # 개별 ID 일반화
            key = (r["action"], reason[:60])
            pat[key] += 1
            samples[key].append(r["target"])
        out = []
        for (action, reason), n in pat.items():
            if n < min_count: continue
            out.append({"kind": "rule-candidate", "action": action, "pattern": reason,
                        "count": n, "targets": samples[(action, reason)][:5],
                        "proposal": f"'{action}' 거부 패턴이 {n}회 반복 — 사전 차단 규칙 신설 또는 상류 프로세스 개선 검토"})
        return out

    def autonomy_review(self):
        """AI 거부 후 사람이 같은 행동을 수행한 패턴 → 자율성 상향 검토 / 반대는 하향 검토."""
        out = []
        ai_rejected = {(r["action"], r["target"]) for r in self.audit.records
                       if r["actor"] == "AI-Agent" and r["result"] == "rejected"
                       and "에스컬레이션" in r.get("reason", "")}
        for (action, target) in ai_rejected:
            human_ok = any(r["action"] == action and r["target"] != "" and r["actor"] != "AI-Agent"
                           and r["result"] == "success" for r in self.audit.records)
            if human_ok:
                out.append({"kind": "autonomy-review", "action": action,
                            "proposal": f"AI 에스컬레이션 후 사람이 동일 액션을 무수정 승인 — "
                                        f"'{action}' 자동 허용 횟수 상향(N+1) 검토 (무사고 이력 조건)"})
        return out

    def knowledge_gaps(self):
        """근거 없이 끝난 질의 → 문서화 과제."""
        out = []
        for q in self.query_log:
            if q.get("confidence") == "none":
                cause = "문서 만료" if q.get("expiredEvidence") else "문서 부재"
                out.append({"kind": "knowledge-gap", "query": q["query"], "cause": cause,
                            "proposal": f"[{cause}] '{q['query']}'에 답할 정본 문서 작성/갱신 과제 등록"})
        return out

    def eval_candidates(self):
        """경험 라우팅으로 흘러간 정책성 질의 등 라우팅 의심 건 → 평가셋 보강."""
        out = []
        for q in self.query_log:
            if q.get("route") == "experience" and any(w in q["query"] for w in ("정책", "규정", "승인", "기준")):
                out.append({"kind": "eval-candidate", "query": q["query"],
                            "proposal": "정책성 어휘 포함 질의가 experience로 라우팅 — 골든셋에 추가해 라우터 회귀 감시"})
        return out

    def report(self):
        items = self.rule_candidates() + self.autonomy_review() + self.knowledge_gaps() + self.eval_candidates()
        lines = ["# 학습 루프 리포트", "",
                 f"감사 레코드 {len(self.audit.records)}건 · 질의 {len(self.query_log)}건 분석", ""]
        if not items:
            lines.append("개선 후보 없음.")
        by_kind = defaultdict(list)
        for i in items: by_kind[i["kind"]].append(i)
        titles = {"rule-candidate": "## 규칙·프로세스 개선 후보 (→ 온톨로지 Phase 7)",
                  "autonomy-review": "## 자율성 재검토 후보 (→ 관리자 승인 필요)",
                  "knowledge-gap": "## 지식 갭 — 문서화 과제 (→ MD 정본)",
                  "eval-candidate": "## 평가셋 보강 후보 (→ evals/golden.yaml)"}
        for kind, title in titles.items():
            if not by_kind[kind]: continue
            lines += [title, ""]
            for i in by_kind[kind]:
                lines.append(f"- {i['proposal']}")
                if i.get("query"): lines.append(f"  - 질의: \"{i['query']}\"")
                if i.get("count"): lines.append(f"  - 발생 {i['count']}회, 대상 예: {i['targets']}")
            lines.append("")
        return "\n".join(lines), items
