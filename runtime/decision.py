"""Grounded Decision Loop — 판단 레이어의 오케스트레이터.
① Ground(Graph) → ② Evidence(MD 정책 + 사례) → ③ Rule Check → ④ Act(Gateway) → ⑤ Record.
원칙: 근거(grounds) 없는 판단·행동은 기록 자체가 거부된다. 만료 문서는 확정 근거가 될 수 없다.
"""
from runtime.kb import KnowledgeBase, QueryRouter
from runtime.gateway import GatewayError

class NoGroundsError(Exception): pass

class JudgmentLoop:
    def __init__(self, store, gateway, kb_root):
        self.s, self.gw = store, gateway
        self.kb = KnowledgeBase(kb_root)
        self.router = QueryRouter(store)

    # ── 질의 응답 (읽기) ──
    def answer(self, query):
        """질의 라우팅 → 해당 레이어에서 근거와 함께 응답 구성."""
        r = self.router.route(query)
        route = r["route"]
        if route == "graph":
            return self._answer_graph(query, r)
        kind = "policy" if route == "policy" else "experience"
        hits = self.kb.search(query, k=3, kind=kind)
        # 관련성 임계치: 질의 토큰 최소 3개 일치해야 '근거'로 인정 (무관 문서의 저점수 매칭 → 거짓 확신 방지)
        valid = [h for h in hits if not h["expired"] and h["matches"] >= 3]
        expired = [h for h in hits if h["expired"]]
        ans = {"route": route, "grounds": [h["cite"] for h in valid], "evidence": valid,
               "expiredEvidence": [h["cite"] for h in expired]}
        if not valid:
            ans["answer"] = ("확정 근거 없음 — " +
                             ("관련 문서가 검토 기한을 초과했습니다. 문서 갱신 전 확정 답변 불가."
                              if expired else "관련 지식이 없습니다. 문서화 과제로 등록을 제안합니다."))
            ans["confidence"] = "none"
        else:
            top = valid[0]
            ans["answer"] = f"{top['title']} — {top['section']}: {top['text'][:200]}"
            ans["citation"] = top["cite"]
            ans["confidence"] = "policy-grounded" if kind == "policy" else "precedent-only"
            if kind == "experience":
                ans["caveat"] = "선례 기반 답변 — 규칙으로 단정하지 말 것"
        return ans

    def _answer_graph(self, query, routing):
        """그래프 질의: 질의에서 객체를 찾아 상태·차단·계보로 답한다."""
        import re
        target = None
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9_]*", query):  # 한글 조사 분리 (예: 'run2가' → 'run2')
            if self.s.exists(tok): target = tok; break
        if not target:
            return {"route": "graph", "answer": "질의에서 객체를 특정하지 못함 — 객체 ID나 등록 용어 필요",
                    "grounds": [], "confidence": "none"}
        obj = self.s.get_object(target)
        out = {"route": "graph", "object": obj, "grounds": [f"graph:{target}"], "confidence": "graph-grounded"}
        if obj["type"] == "ReportRun":
            out["lineage"] = self.s.trace_lineage(target)
            out["blockedBy"] = self.s.blocking_cases(target)
            out["violations"] = [v for v in self.s.check_rules()
                                 if v["focus"] in set(out["lineage"]["chain"]) | {target}]
            out["grounds"] += [f"rule:{v['rule']}" for v in out["violations"]]
            bits = [f"{target}는 {obj['properties'].get('status')} 상태"]
            if out["blockedBy"]: bits.append(f"미해결 예외 {out['blockedBy']}가 차단 중(R-05)")
            if out["violations"]: bits.append(f"발동 규칙 {[v['rule'] for v in out['violations']]}")
            out["answer"] = ", ".join(bits)
        else:
            out["answer"] = f"{target} ({obj['type']}): status={obj['properties'].get('status')}"
        return out

    # ── 행동 (쓰기) — 근거 필수 ──
    def act(self, action, target, actor, grounds, approval=None, **kwargs):
        """근거 ID 없는 행동은 게이트웨이 도달 전에 거부한다 (판단 레이어의 계약)."""
        if not grounds:
            raise NoGroundsError("근거(grounds) 없는 행동 요청 — 판단 레이어 계약 위반. "
                                 "graph:/rule:/문서 cite 중 최소 1개 필요")
        # 만료 문서를 유일한 근거로 쓰는 것 금지
        doc_grounds = [g for g in grounds if not g.startswith(("graph:", "rule:", "case:"))]
        for g in doc_grounds:
            doc = g.split("#")[0]
            if self.kb.docs.get(doc, {}).get("expired") and len(grounds) == 1:
                raise NoGroundsError(f"만료 문서({doc})가 유일한 근거 — 확정 행동 불가")
        return self.gw.execute(action, target, actor, approval=approval, grounds=grounds, **kwargs)
