"""Action Gateway — AI(와 사람)의 모든 쓰기 행동이 통과하는 단일 관문.
온톨로지 Action 정의를 그대로 집행한다: 대상 타입 → 권한 → 자율성 → 승인 → 사전조건 → 멱등성 → 효과 → 감사.
실패 누적 시 서킷 브레이커가 해당 액션을 human-approval로 강등한다.
"""
import json, re, time

class GatewayError(Exception): pass

class AuditLog:
    def __init__(self, path=None):
        self.records, self.path = [], path
    def append(self, rec):
        rec = dict(rec); rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.records.append(rec)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    def count(self, **flt):
        return sum(1 for r in self.records if all(r.get(k) == v for k, v in flt.items()))

class ActionGateway:
    CB_THRESHOLD = 3  # 액션별 연속 거부 임계치 → human-approval 강등

    def __init__(self, store, audit=None):
        self.store, self.audit = store, audit or AuditLog()
        self.idempotency, self.failures, self.forced_human = set(), {}, set()
        self.handlers = self._build_handlers()

    # ── 사전조건·효과 핸들러 (온톨로지 Action 정의의 기계 구현) ──
    def _build_handlers(self):
        s = self.store
        def pre_assign(t, kw):
            return (s.status(t) == "오픈", f"케이스 상태={s.status(t)} (오픈이어야 함)")
        def eff_assign(t, kw):
            s.set_status(t, "처리 중"); return {"case": t, "status": "처리 중", "assignee": kw.get("assignee")}

        def pre_correct(t, kw):
            if s.status(t) != "처리 중": return False, f"케이스 상태={s.status(t)} (처리 중이어야 함)"
            if not kw.get("reason"): return False, "보정 사유(reason) 필수 — 감사 요건"
            return True, ""
        def eff_correct(t, kw):
            if kw.get("campaign") and kw.get("correctedSpend") is not None:
                s.set_prop(kw["campaign"], "spend", kw["correctedSpend"], datatype="decimal")
            if kw.get("dataset"): s.set_status(kw["dataset"], "검증 대기")
            s.set_status(t, "해결")
            return {"case": t, "status": "해결", "reason": kw["reason"]}

        def pre_validate(t, kw):
            return (s.status(t) == "검증 대기", f"데이터셋 상태={s.status(t)} (검증 대기여야 함)")
        def eff_validate(t, kw):
            upstream = set(s.upstream_of(t)) | {t}
            relevant = [v for v in s.check_rules() if v["focus"] in upstream]
            if relevant:
                s.set_status(t, "실패"); s.set_prop(t, "failReason", relevant[0]["message"][:80])
            else:
                s.set_status(t, "정상")
            return {"dataset": t, "status": s.status(t), "violations": relevant}

        def pre_collect(t, kw):
            return (s.status(t) == "인증", f"계정 상태={s.status(t)} (인증이어야 함)")
        def eff_collect(t, kw):
            rid = f"raw_{t}_{kw.get('date','today')}"
            s.add_object(rid, "RawAdPerformance", status="수집 완료"); return {"raw": rid}

        def pre_reconnect(t, kw):
            return (s.status(t) == "만료", f"계정 상태={s.status(t)} (만료여야 함)")
        def eff_reconnect(t, kw):
            s.set_status(t, "인증"); return {"account": t, "status": "인증"}

        def pre_regen(t, kw):
            if s.status(t) not in ("실패", "완료"): return False, f"Run 상태={s.status(t)} (실패/완료여야 함)"
            blocked = s.blocking_cases(t)
            if blocked: return False, f"R-05: 미해결 ExceptionCase가 차단 중 — {blocked}"
            ds = [l["target"] for l in s.get_object(t)["linksOut"] if l["predicate"] == "consumes"]
            if not ds or s.status(ds[0]) != "정상":
                return False, f"R-02: CleanDataSet({ds[0] if ds else '없음'}) 상태={s.status(ds[0]) if ds else '-'} (정상이어야 함)"
            return True, ""
        def eff_regen(t, kw):
            n = 1
            while s.exists(f"{t}_r{n}"): n += 1
            new_id = f"{t}_r{n}"
            s.add_object(new_id, "ReportRun", status="생성 중", triggeredBy=kw.get("triggeredBy", "수동"))
            for l in s.get_object(t)["linksOut"]:
                if l["predicate"] in ("consumes", "hasTemplate", "forAdvertiser"):
                    s.add_link(new_id, l["predicate"], l["target"])
            s.add_link(t, "supersededBy", new_id)
            if s.status(t) == "실패": s.set_status(t, "재생성")
            return {"newRun": new_id, "supersedes": t}

        def pre_deliver(t, kw):
            if s.status(t) != "생성됨": return False, f"파일 상태={s.status(t)} (생성됨이어야 함)"
            runs = [l["source"] for l in s.get_object(t)["linksIn"] if l["predicate"] == "generates"]
            if not runs or s.status(runs[0]) != "완료": return False, "생성 Run이 완료 상태가 아님"
            if s.blocking_cases(runs[0]): return False, "R-05: 차단 예외 존재"
            return True, ""
        def eff_deliver(t, kw):
            s.set_status(t, "전달됨"); return {"file": t, "status": "전달됨"}

        return {
            "assignCase":        {"pre": pre_assign,    "effect": eff_assign},
            "correctAndApprove": {"pre": pre_correct,   "effect": eff_correct},
            "validate":          {"pre": pre_validate,  "effect": eff_validate},
            "collectData":       {"pre": pre_collect,   "effect": eff_collect},
            "reconnectAccount":  {"pre": pre_reconnect, "effect": eff_reconnect},
            "regenerateReport":  {"pre": pre_regen,     "effect": eff_regen},
            "deliverReport":     {"pre": pre_deliver,   "effect": eff_deliver},
        }

    # ── 조건부 승인 판정 (온톨로지 approval 필드의 기계 구현) ──
    def approval_needed(self, action, target):
        s = self.store
        if action == "regenerateReport":
            for l in s.get_object(target)["linksOut"]:
                if l["predicate"] == "generates" and s.status(l["target"]) == "전달됨":
                    return "전달 후 재생성 — 팀장 승인 필수"
        if action == "deliverReport":
            runs = [l["source"] for l in s.get_object(target)["linksIn"] if l["predicate"] == "generates"]
            if runs:
                adv = [l["target"] for l in s.get_object(runs[0])["linksOut"] if l["predicate"] == "forAdvertiser"]
                if adv and s.get_object(adv[0])["properties"].get("tier") == "VIP":
                    return "VIP 광고주 — 담당자 확인 필수"
        return None

    # ── 실행 관문 ──
    def execute(self, action, target, actor, approval=None, grounds=None, **kwargs):
        rec = {"action": action, "target": target, "actor": actor,
               "approval": approval, "grounds": grounds, "params": kwargs or None}
        try:
            spec = self.store.actions.get(action)
            if not spec: raise GatewayError(f"미정의 액션: {action} — 온톨로지에 없는 행동은 실행 불가")
            if self.store.type_of(target) != spec["target"]:
                raise GatewayError(f"대상 타입 불일치: {target}는 {self.store.type_of(target)} (요구: {spec['target']})")
            perms = [str(p) for p in spec["permission"]]
            if actor not in perms:
                raise GatewayError(f"권한 없음: '{actor}' ∉ {perms}")
            autonomy = str(spec["autonomy"]); base = autonomy.split("(")[0]
            if action in self.forced_human: base = "human-approval"
            if actor == "AI-Agent":
                if base == "human-approval":
                    raise GatewayError("자율성: 이 액션은 사람 승인 전용 — AI 직접 실행 불가")
                if base == "auto-then-escalate":
                    limit = int(re.findall(r"\((\d+)\)", autonomy)[0])
                    used = self.audit.count(action=action, target=target, actor="AI-Agent", result="success")
                    if used >= limit:
                        raise GatewayError(f"자율성: AI 자동 실행 {limit}회 소진 — 사람에게 에스컬레이션")
            need = self.approval_needed(action, target)
            rec["approvalRequired"] = need
            if need and not approval:
                raise GatewayError(f"승인 필요: {need}")
            ok, reason = self.handlers[action]["pre"](target, kwargs)
            rec["preconditionEval"] = "pass" if ok else f"fail: {reason}"
            if not ok: raise GatewayError(f"사전조건 실패: {reason}")
            key = (action, target, json.dumps(kwargs, sort_keys=True, ensure_ascii=False))
            if key in self.idempotency:
                raise GatewayError("멱등성: 동일 요청 중복 실행 차단")
            effect = self.handlers[action]["effect"](target, kwargs)
            self.idempotency.add(key); self.failures[action] = 0
            rec.update(result="success", effect=effect)
            self.audit.append(rec)
            return effect
        except GatewayError as e:
            self.failures[action] = self.failures.get(action, 0) + 1
            if self.failures[action] >= self.CB_THRESHOLD and action not in self.forced_human:
                self.forced_human.add(action)
                rec["circuitBreaker"] = f"연속 거부 {self.failures[action]}회 → human-approval 강등 + owner 통보"
            rec.update(result="rejected", reason=str(e))
            self.audit.append(rec)
            raise
