"""관측(Observability) 설정 정본 — Langfuse 환경변수·스팬 명명·대시보드 메트릭 정의.
observability.py와 docs/observability-setup.md가 모두 이 파일을 참조한다 (정의는 한 곳에만).
"""
import os
from dataclasses import dataclass
from typing import Optional

# ── 환경변수 이름 ──
ENV_PUBLIC_KEY   = "LANGFUSE_PUBLIC_KEY"
ENV_SECRET_KEY   = "LANGFUSE_SECRET_KEY"
ENV_HOST         = "LANGFUSE_HOST"
ENV_ENABLED      = "AX_OBSERVABILITY_ENABLED"    # false/0/no/off → 강제 비활성
ENV_CB_THRESHOLD = "AX_OBS_CB_THRESHOLD"         # 연속 SDK 오류 임계치
ENV_CB_COOLDOWN  = "AX_OBS_CB_COOLDOWN_SEC"      # 서킷 오픈 유지 시간(초)
ENV_SAMPLE_RATE  = "AX_OBS_SAMPLE_RATE"          # 루트 트레이스 샘플링 비율 0..1

# ── 기본값 ──
DEFAULT_HOST         = "https://cloud.langfuse.com"
DEFAULT_CB_THRESHOLD = 5       # N회 연속 오류 → 서킷 오픈
DEFAULT_CB_COOLDOWN  = 300.0   # 오픈 후 쿨다운 — 경과 시 half-open 1회 재시도
DEFAULT_SAMPLE_RATE  = 1.0

# ── 트레이스/스팬 명명 (대시보드 필터의 기준 — 임의 변경 금지) ──
TRACE_JUDGMENT_LOOP  = "ax.judgment-loop"
SPAN_DECISION_ANSWER = "decision.answer"
SPAN_DECISION_ACT    = "decision.act"
SPAN_GATEWAY_EXECUTE = "gateway.execute"
SPAN_QUERY_ROUTE     = "router.route"
SPAN_KB_SEARCH       = "kb.search"

_FALSY = ("false", "0", "no", "off")

@dataclass
class ObservabilityConfig:
    enabled: bool
    public_key: Optional[str] = None
    secret_key: Optional[str] = None
    host: str = DEFAULT_HOST
    cb_threshold: int = DEFAULT_CB_THRESHOLD
    cb_cooldown_sec: float = DEFAULT_CB_COOLDOWN
    sample_rate: float = DEFAULT_SAMPLE_RATE

def _num(env, name, default, cast):
    try: return cast(env.get(name, default))
    except (TypeError, ValueError): return default

def load_config(env=None):
    """환경변수 → ObservabilityConfig. 키 누락 또는 AX_OBSERVABILITY_ENABLED=false면 비활성."""
    env = os.environ if env is None else env
    pk, sk = env.get(ENV_PUBLIC_KEY), env.get(ENV_SECRET_KEY)
    flag = str(env.get(ENV_ENABLED, "true")).strip().lower() not in _FALSY
    return ObservabilityConfig(
        enabled=bool(flag and pk and sk),
        public_key=pk, secret_key=sk,
        host=env.get(ENV_HOST) or DEFAULT_HOST,
        cb_threshold=max(1, _num(env, ENV_CB_THRESHOLD, DEFAULT_CB_THRESHOLD, int)),
        cb_cooldown_sec=max(0.0, _num(env, ENV_CB_COOLDOWN, DEFAULT_CB_COOLDOWN, float)),
        sample_rate=min(1.0, max(0.0, _num(env, ENV_SAMPLE_RATE, DEFAULT_SAMPLE_RATE, float))))

# ── 권장 대시보드 메트릭 (Langfuse 대시보드/알림 구성의 기준) ──
DASHBOARD_METRICS = [
    {"name": "routing_accuracy",      "description": "라우팅 정확도 — 질의가 올바른 레이어(graph/policy/experience)로 갔는가",
     "source": SPAN_QUERY_ROUTE,      "aggregation": "output.route를 evals/golden.yaml 기대값과 대조한 정답률(%)"},
    {"name": "grounded_answer_rate",  "description": "근거 있는 응답 비율 — confidence≠none인 응답의 비율 (근거 없는 확신 감시)",
     "source": SPAN_DECISION_ANSWER,  "aggregation": "output.confidence != 'none' 비율(%)"},
    {"name": "expired_evidence_rate", "description": "만료 근거 검색 비율 — 검색 결과에 검토 기한 초과 문서가 섞인 비율 (문서 부채 신호)",
     "source": SPAN_KB_SEARCH,        "aggregation": "output.expiredCount > 0 인 검색의 비율(%)"},
    {"name": "gateway_rejection_rate","description": "게이트웨이 거부율 — 사유별(권한/자율성/승인/사전조건/멱등성) 분류 필수",
     "source": SPAN_GATEWAY_EXECUTE,  "aggregation": "level=WARNING 스팬 비율(%), status_message 접두어로 사유 분류"},
    {"name": "circuit_breaker_trips", "description": "서킷브레이커 발동 횟수 — 액션이 human-approval로 강등된 사건 (운영 개입 신호)",
     "source": SPAN_GATEWAY_EXECUTE,  "aggregation": "output.circuitBreaker 존재 스팬 count (일별)"},
    {"name": "autonomy_escalations",  "description": "자율성 소진 에스컬레이션 — AI 자동 실행 한도 도달로 사람에게 넘어간 횟수",
     "source": SPAN_GATEWAY_EXECUTE,  "aggregation": "status_message에 '에스컬레이션' 포함 스팬 count"},
    {"name": "search_hit_rate",       "description": "검색 적중률 — 유효 근거를 1건 이상 찾은 검색의 비율 (지식 공백 감시)",
     "source": SPAN_KB_SEARCH,        "aggregation": "output.hits 비어있지 않은 비율(%)"},
    {"name": "p95_latency",           "description": "p95 지연시간 — 판단 루프 각 단계의 꼬리 지연 (스팬별 분리 집계)",
     "source": TRACE_JUDGMENT_LOOP,   "aggregation": "스팬 duration p95(ms), 스팬 이름별 그룹핑"},
]
