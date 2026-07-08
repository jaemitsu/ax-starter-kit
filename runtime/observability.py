"""Langfuse 관측 통합 — 판단 루프의 각 단계를 스팬으로 기록한다 (graceful degradation).
원칙: 관측 실패는 절대 비즈니스 로직에 전파되지 않는다.
  · langfuse 미설치 → 전부 no-op (데코레이터는 원 함수 그대로 동작)
  · SDK 연속 오류 N회 → 서킷 오픈, 쿨다운 후 half-open 1회 재시도
  · 래핑된 함수의 예외는 그대로 전파하되 스팬에 ERROR(게이트웨이 거부는 WARNING)로 기록
SDK 호환: v3+ = start_as_current_span / get_client, v2 = Langfuse().trace(...) — 속성 존재로 감지.
"""
import functools, logging, random, time, types
from contextlib import contextmanager

from runtime.gateway import GatewayError
from runtime.observability_config import (
    ObservabilityConfig, load_config,
    TRACE_JUDGMENT_LOOP, SPAN_DECISION_ANSWER, SPAN_DECISION_ACT,
    SPAN_GATEWAY_EXECUTE, SPAN_QUERY_ROUTE, SPAN_KB_SEARCH)

try:
    import langfuse                     # 선택 의존성 — 없으면 전 기능 no-op
    LANGFUSE_AVAILABLE = True
except ImportError:
    langfuse = None
    LANGFUSE_AVAILABLE = False

log = logging.getLogger("ax.observability")

# ── 스팬 핸들 ──
class _NullHandle:
    """비활성/스킵 경로용 no-op 핸들."""
    handled = False
    def update(self, **kw): pass

_NULL = _NullHandle()
_SKIP = object()   # 스택 표식: 이 트레이스는 샘플링 제외/실패 — 자식도 전부 스킵

class _SpanHandle:
    """실 스팬 핸들 — 모든 update가 트레이서 보호막(_safe)을 경유한다."""
    def __init__(self, tracer, raw):
        self._tracer, self._raw, self.handled = tracer, raw, False
    def update(self, **kw):
        kw = {k: v for k, v in kw.items() if v is not None}
        if "level" in kw: self.handled = True     # 호출부가 레벨을 명시 → CM의 ERROR 덮어쓰기 방지
        if kw and self._raw is not None and hasattr(self._raw, "update"):
            self._tracer._safe(lambda: self._raw.update(**kw))

class LangfuseTracer:
    """Langfuse 클라이언트 래퍼 — 서킷브레이커·샘플링·v2/v3 호환을 책임진다."""

    def __init__(self, config=None, client=None, clock=None, rand=None):
        self.cfg = config or load_config()
        self._clock, self._rand = clock or time.monotonic, rand or random.random
        self._fails, self._open_until, self._warned = 0, 0.0, False
        self._stack = []                # 진행 중 스팬 스택 (v2 부모 추적 + 샘플링 전파)
        if client is not None:          # 주입 클라이언트 (테스트/커스텀)
            self.client = client
            self.mode = self._detect(client)
            self.enabled = self.cfg.enabled and self.mode is not None
        elif self.cfg.enabled and LANGFUSE_AVAILABLE:
            self.client = self._build_client()
            self.mode = self._detect(self.client)
            self.enabled = self.mode is not None
        else:
            self.client, self.mode, self.enabled = None, None, False

    # ── 클라이언트 구성·감지 ──
    def _build_client(self):
        try:
            if hasattr(langfuse, "Langfuse"):
                kw = {"public_key": self.cfg.public_key, "secret_key": self.cfg.secret_key,
                      "host": self.cfg.host}
                return langfuse.Langfuse(**{k: v for k, v in kw.items() if v})
            if hasattr(langfuse, "get_client"):     # v3+: 환경변수 기반 싱글턴
                return langfuse.get_client()
        except Exception as e:
            log.warning("Langfuse 클라이언트 초기화 실패 — 관측 비활성: %s", e)
        return None

    @staticmethod
    def _detect(client):
        """버전 문자열이 아니라 속성 존재로 SDK 세대를 감지한다."""
        if client is None: return None
        if hasattr(client, "start_as_current_span"): return "v3"   # v3/v4 OTel 기반
        if callable(getattr(client, "trace", None)): return "v2"   # v2 stateful 클라이언트
        return None

    # ── 서킷브레이커 ──
    def _allowed(self):
        if not self.enabled or self.client is None: return False
        if self._fails < self.cfg.cb_threshold: return True
        return self._clock() >= self._open_until    # 쿨다운 경과 → half-open 1회 허용

    def _on_failure(self, exc):
        self._fails += 1
        if self._fails >= self.cfg.cb_threshold:
            self._open_until = self._clock() + self.cfg.cb_cooldown_sec
            if not self._warned:
                log.warning("Langfuse 서킷브레이커 오픈 — 연속 오류 %d회, %.0f초간 관측 중단: %s",
                            self._fails, self.cfg.cb_cooldown_sec, exc)
                self._warned = True

    def _on_success(self):
        if self._fails: self._fails, self._open_until, self._warned = 0, 0.0, False

    def _safe(self, fn):
        """모든 SDK 호출의 보호막 — 예외를 삼키고 브레이커에 기록. 실패 시 None."""
        try:
            out = fn()
        except Exception as e:
            self._on_failure(e); return None
        self._on_success(); return out

    def _sample(self):
        return self.cfg.sample_rate >= 1.0 or self._rand() < self.cfg.sample_rate

    # ── 스팬 생성·종료 ──
    def _start(self, name, input=None, metadata=None):
        kw = {k: v for k, v in (("input", input), ("metadata", metadata)) if v is not None}
        if self.mode == "v3":
            def go():
                cm = self.client.start_as_current_span(name=name, **kw)
                return {"cm": cm, "span": cm.__enter__()}   # CM 진입 → 컨텍스트 전파
            return self._safe(go)
        def go():   # v2: 루트는 trace, 자식은 부모의 span
            parent = self._stack[-1]["span"] if self._stack else None
            raw = parent.span(name=name, **kw) if parent is not None \
                  else self.client.trace(name=name, **kw)
            return {"cm": None, "span": raw}
        return self._safe(go)

    def _end(self, entry):
        if entry.get("cm") is not None:
            self._safe(lambda: entry["cm"].__exit__(None, None, None))
        elif hasattr(entry["span"], "end"):
            self._safe(entry["span"].end)

    @contextmanager
    def span(self, name, input=None, output=None, metadata=None, level=None):
        """자식 스팬 CM. 실패·비활성·샘플링 제외 시 no-op 핸들을 준다 (본문 예외는 그대로 전파)."""
        skip = (not self._allowed()
                or (self._stack and self._stack[-1] is _SKIP)   # 부모가 스킵이면 자식도 스킵
                or (not self._stack and not self._sample()))    # 샘플링은 루트에서만 결정
        entry = None if skip else self._start(name, input=input, metadata=metadata)
        if entry is None:
            self._stack.append(_SKIP)
            try: yield _NULL
            finally: self._stack.pop()
            return
        handle = _SpanHandle(self, entry["span"])
        if level: handle.update(level=level)
        if output is not None: handle.update(output=output)
        self._stack.append(entry)
        try:
            yield handle
        except BaseException as e:
            if not handle.handled:      # 호출부가 WARNING 등으로 이미 기록했으면 존중
                handle.update(level="ERROR", status_message=str(e)[:300])
            raise
        finally:
            self._stack.pop()
            self._end(entry)

    @contextmanager
    def trace(self, name=TRACE_JUDGMENT_LOOP, metadata=None):
        """루트 트레이스 CM — 내부적으로 span과 동일, 이름 기본값만 다르다."""
        with self.span(name, metadata=metadata) as h:
            yield h

    def event(self, name, input=None, output=None, metadata=None, level=None):
        if not self._allowed() or (self._stack and self._stack[-1] is _SKIP): return
        kw = {k: v for k, v in (("input", input), ("output", output),
                                ("metadata", metadata), ("level", level)) if v is not None}
        def go():
            top = self._stack[-1]["span"] if self._stack else None
            if top is not None and hasattr(top, "event"):        return top.event(name=name, **kw)
            if hasattr(self.client, "create_event"):             return self.client.create_event(name=name, **kw)
            if hasattr(self.client, "event"):                    return self.client.event(name=name, **kw)
        self._safe(go)

    def score(self, name, value, comment=None):
        if not self._allowed(): return
        kw = {"name": name, "value": value}
        if comment is not None: kw["comment"] = comment
        def go():
            for target, meth in ((self.client, "score_current_trace"), (self.client, "create_score"),
                                 (self._stack[-1]["span"] if self._stack and self._stack[-1] is not _SKIP else None, "score"),
                                 (self.client, "score")):
                if target is not None and hasattr(target, meth):
                    return getattr(target, meth)(**kw)
        self._safe(go)

    def flush(self):
        if self.client is not None and hasattr(self.client, "flush"):
            self._safe(self.client.flush)

    def shutdown(self):
        if self.client is None: return
        if hasattr(self.client, "shutdown"): self._safe(self.client.shutdown)
        else: self.flush()

# ── 싱글턴 접근자 ──
_tracer = None

def get_tracer(refresh=False):
    global _tracer
    if _tracer is None or refresh: _tracer = LangfuseTracer()
    return _tracer

def set_tracer(tracer):
    """테스트/커스텀 트레이서 주입 (None이면 다음 get_tracer가 재생성)."""
    global _tracer
    _tracer = tracer

# ── 데코레이터 공통 ──
def _pick(args, kwargs, pos, name, default=None):
    """메서드 인자 추출 (args[0]=self 가정) — 실패해도 조용히 기본값."""
    if name in kwargs: return kwargs[name]
    return args[pos] if len(args) > pos else default

def _flex(builder):
    """@deco 와 @deco(name=..., tracer=...) 두 형태 모두 지원."""
    @functools.wraps(builder)
    def deco(func=None, *, name=None, tracer=None):
        if func is None:
            return lambda f: builder(f, name=name, tracer=tracer)
        return builder(func, name=name, tracer=tracer)
    return deco

def _finish_wrapper(wrapper):
    wrapper.__ax_traced__ = True    # instrument() 중복 계측 방지 표식
    return wrapper

@_flex
def trace_decision(func, name=None, tracer=None):
    """JudgmentLoop.answer/act 계측 — 질의/행동을 입력, 라우트·확신도·근거/효과를 출력으로 기록."""
    fname = func.__name__
    span_name = name or {"answer": SPAN_DECISION_ANSWER, "act": SPAN_DECISION_ACT}.get(fname, f"decision.{fname}")
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        tr = tracer or get_tracer()
        if fname == "act":
            inp = {"action": _pick(args, kwargs, 1, "action"), "target": _pick(args, kwargs, 2, "target"),
                   "actor": _pick(args, kwargs, 3, "actor"), "grounds": _pick(args, kwargs, 4, "grounds")}
        else:
            inp = {"query": _pick(args, kwargs, 1, "query")}
        with tr.span(span_name, input=inp) as h:
            result = func(*args, **kwargs)
            try:
                if isinstance(result, dict) and "route" in result:
                    h.update(output={k: result.get(k) for k in ("route", "confidence", "grounds", "answer") if k in result})
                else:
                    h.update(output={"effect": result})
            except Exception: pass
            return result
    return _finish_wrapper(wrapper)

def _audit_stages(gw):
    """감사 레코드에서 게이트웨이 단계(승인 요건·사전조건 평가·서킷브레이커)를 안전하게 추출."""
    try:
        rec = gw.audit.records[-1]
        return {k: rec[k] for k in ("approvalRequired", "preconditionEval", "circuitBreaker") if rec.get(k) is not None}
    except Exception:
        return {}

@_flex
def trace_gateway(func, name=None, tracer=None):
    """ActionGateway.execute 계측 — 거부(GatewayError)는 WARNING으로, 성공은 효과와 함께 기록."""
    span_name = name or SPAN_GATEWAY_EXECUTE
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        tr = tracer or get_tracer()
        gw = args[0] if args and hasattr(args[0], "audit") else None
        inp = {"action": _pick(args, kwargs, 1, "action"), "target": _pick(args, kwargs, 2, "target"),
               "actor": _pick(args, kwargs, 3, "actor")}
        with tr.span(span_name, input=inp) as h:
            try:
                effect = func(*args, **kwargs)
            except GatewayError as e:   # 거부는 오류가 아니라 안전장치 작동 — WARNING
                h.update(level="WARNING", status_message=str(e)[:300],
                         output={"result": "rejected", "reason": str(e), **_audit_stages(gw)})
                raise
            h.update(output={"result": "success", "effect": effect, **_audit_stages(gw)})
            return effect
    return _finish_wrapper(wrapper)

@_flex
def trace_query(func, name=None, tracer=None):
    """QueryRouter.route 계측 — 질의와 라우팅 결과(route/scores)를 기록."""
    span_name = name or SPAN_QUERY_ROUTE
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        tr = tracer or get_tracer()
        with tr.span(span_name, input={"query": _pick(args, kwargs, 1, "query")}) as h:
            result = func(*args, **kwargs)
            try: h.update(output=result if isinstance(result, dict) else {"result": result})
            except Exception: pass
            return result
    return _finish_wrapper(wrapper)

@_flex
def trace_search(func, name=None, tracer=None):
    """KnowledgeBase.search 계측 — 질의/종류/k를 입력, 인용·점수·만료 건수를 출력으로 기록."""
    span_name = name or SPAN_KB_SEARCH
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        tr = tracer or get_tracer()
        inp = {"query": _pick(args, kwargs, 1, "query"),
               "k": _pick(args, kwargs, 2, "k", 3), "kind": _pick(args, kwargs, 3, "kind")}
        with tr.span(span_name, input=inp) as h:
            hits = func(*args, **kwargs)
            try:
                h.update(output={"hits": [{"cite": x.get("cite"), "score": x.get("score")} for x in hits],
                                 "expiredCount": sum(1 for x in hits if x.get("expired"))})
            except Exception: pass
            return hits
    return _finish_wrapper(wrapper)

# ── 무수정 계측 헬퍼 ──
def instrument(store=None, gateway=None, loop=None, kb=None, router=None, tracer=None):
    """기존 인스턴스의 메서드를 데코레이터로 감싸 바인딩한다 — 코드 수정 없이 opt-in.
    store는 시그니처 호환용으로만 받는다 (읽기 grounding 호출은 스팬 노이즈가 커서 제외).
    반환: 계측된 메서드 이름 목록 (이미 계측된 것은 건너뜀).
    """
    done = []
    def patch(obj, attr, deco):
        if obj is None: return
        if getattr(getattr(obj, attr, None), "__ax_traced__", False): return  # 중복 계측 방지
        raw = getattr(type(obj), attr)
        setattr(obj, attr, types.MethodType(deco(raw, tracer=tracer), obj))
        done.append(f"{type(obj).__name__}.{attr}")
    patch(gateway, "execute", trace_gateway)
    patch(loop, "answer", trace_decision)
    patch(loop, "act", trace_decision)
    patch(kb, "search", trace_search)
    patch(router, "route", trace_query)
    return done
