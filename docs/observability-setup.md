# 관측(Observability) 설정 가이드 — Langfuse 연동

> 판단 루프의 각 단계(라우팅 → 검색 → 판단 → 행동)를 트레이스로 기록한다.
> 정의 정본: `runtime/observability_config.py` · 구현: `runtime/observability.py` · 테스트: `tests_runtime/test_observability.py`

---

## 1. 개요 — 왜 관측이 필요한가

이 킷의 안전장치(근거 필수, 게이트웨이 거부, 서킷브레이커, 자율성 예산)는 **작동했다는 사실 자체가 운영 신호**다. 감사 로그(`AuditLog`)는 "무엇이 실행/거부됐는가"를 남기지만, 다음 질문에는 트레이스가 필요하다:

- 이 질의는 **어느 레이어로 라우팅**됐고, 그 판단이 맞았는가? (라우팅 정확도)
- 검색이 **만료 문서만 건졌는가**? (문서 부채가 응답 품질을 갉아먹는 시점 포착)
- 게이트웨이 거부가 **어떤 사유로, 어떤 빈도로** 일어나는가? (규칙 과잉/미비 신호)
- 판단 루프의 **어느 단계가 느린가**? (p95 지연 분해)

`ax.judgment-loop` 트레이스 하나가 질의/행동 한 건의 전 단계를 담는다. 각 스팬의 입출력은 근거(citation)까지 포함하므로, Langfuse 화면에서 "왜 이렇게 답했는가"를 단계별로 재구성할 수 있다.

## 2. 설치 (선택 사항)

```bash
pip install langfuse
```

**langfuse는 선택 의존성이다.** 설치하지 않아도 킷의 모든 기능이 그대로 동작한다 — 데코레이터와 `instrument()`는 전부 no-op이 되고, 어떤 오버헤드·오류도 발생하지 않는다. 셀프호스팅(Langfuse OSS) 또는 Cloud(`cloud.langfuse.com`) 어느 쪽이든 무방하다.

## 3. 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `LANGFUSE_PUBLIC_KEY` | (없음) | 프로젝트 공개 키. **없으면 관측 비활성** |
| `LANGFUSE_SECRET_KEY` | (없음) | 프로젝트 비밀 키. **없으면 관측 비활성** |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | 셀프호스팅 시 자체 URL |
| `AX_OBSERVABILITY_ENABLED` | `true` | `false`/`0`/`no`/`off` → 키가 있어도 강제 비활성 |
| `AX_OBS_CB_THRESHOLD` | `5` | SDK 연속 오류 N회 → 서킷 오픈 |
| `AX_OBS_CB_COOLDOWN_SEC` | `300` | 서킷 오픈 유지 시간(초), 경과 후 half-open 재시도 |
| `AX_OBS_SAMPLE_RATE` | `1.0` | 루트 트레이스 샘플링 비율 (0..1, 범위 밖은 클램프) |

> 비밀 키는 코드·리포지토리에 넣지 말 것 — 배포 환경의 시크릿 매니저로 주입한다.

## 4. 통합 방법

### 방법 A — `instrument()` 헬퍼 (권장: 기존 코드 무수정)

```python
from runtime.store import OntologyStore
from runtime.gateway import ActionGateway
from runtime.decision import JudgmentLoop
from runtime.observability import instrument

s  = OntologyStore("domains/ad-reporting", "runtime/sample-instances.ttl")
gw = ActionGateway(s)
loop = JudgmentLoop(s, gw, "knowledge")

# 인스턴스 메서드를 감싸서 재바인딩 — 원본 파일은 건드리지 않는다
instrument(gateway=gw, loop=loop, kb=loop.kb, router=loop.router)

loop.answer("전달 후 재생성 승인이 필요한가?")   # → 스팬 자동 기록
```

- 이미 계측된 메서드는 건너뛴다(중복 호출 안전).
- `store`는 시그니처 호환용으로만 받는다 — 읽기 grounding 호출은 스팬 노이즈가 커서 제외.

### 방법 B — 데코레이터 직접 적용

```python
from runtime.observability import trace_decision, trace_gateway, trace_query, trace_search

class MyGateway(ActionGateway):
    @trace_gateway                      # 인자 없는 형태
    def execute(self, action, target, actor, **kw):
        return super().execute(action, target, actor, **kw)

@trace_search(name="kb.search.custom")  # 이름 지정 형태도 지원
def my_search(self, query, k=3, kind=None): ...
```

### 루트 트레이스로 한 세션 묶기

```python
from runtime.observability import get_tracer

tr = get_tracer()
with tr.trace(metadata={"session": "demo-001", "actor": "AI-Agent"}):
    loop.answer("run2가 왜 막혔어?")
    loop.act("assignCase", "case1", "AI-Agent", grounds=["graph:case1"], assignee="QA")
tr.flush()   # 종료 전 배출 (단명 프로세스라면 필수)
```

## 5. 스팬 구조

```
ax.judgment-loop                     ← 루트 트레이스 (세션/요청 단위)
├── decision.answer                  ← 질의 응답 (input: query / output: route·confidence·grounds)
│   ├── router.route                 ← 라우팅 (output: route + scores)
│   └── kb.search                    ← 지식 검색 (output: hits[cite,score] + expiredCount)
└── decision.act                     ← 행동 (input: action·target·actor·grounds)
    └── gateway.execute              ← 실행 관문 (output: result·effect·approvalRequired·preconditionEval)
                                        거부 시 level=WARNING + status_message=거부 사유
```

스팬 이름은 `runtime/observability_config.py`의 상수가 정본이다 — 대시보드 필터가 이 이름에 걸려 있으므로 임의 변경 금지.

## 6. 권장 대시보드 메트릭

`observability_config.DASHBOARD_METRICS`와 1:1 대응한다.

| 메트릭 | 설명 | 소스 스팬 | 집계 |
|---|---|---|---|
| `routing_accuracy` | 라우팅 정확도 — 질의가 올바른 레이어(graph/policy/experience)로 갔는가 | `router.route` | output.route를 evals/golden.yaml 기대값과 대조한 정답률(%) |
| `grounded_answer_rate` | 근거 있는 응답 비율 — confidence≠none인 응답의 비율 (근거 없는 확신 감시) | `decision.answer` | output.confidence != 'none' 비율(%) |
| `expired_evidence_rate` | 만료 근거 검색 비율 — 검색 결과에 검토 기한 초과 문서가 섞인 비율 (문서 부채 신호) | `kb.search` | output.expiredCount > 0 인 검색의 비율(%) |
| `gateway_rejection_rate` | 게이트웨이 거부율 — 사유별(권한/자율성/승인/사전조건/멱등성) 분류 필수 | `gateway.execute` | level=WARNING 스팬 비율(%), status_message 접두어로 사유 분류 |
| `circuit_breaker_trips` | 서킷브레이커 발동 횟수 — 액션이 human-approval로 강등된 사건 (운영 개입 신호) | `gateway.execute` | output.circuitBreaker 존재 스팬 count (일별) |
| `autonomy_escalations` | 자율성 소진 에스컬레이션 — AI 자동 실행 한도 도달로 사람에게 넘어간 횟수 | `gateway.execute` | status_message에 '에스컬레이션' 포함 스팬 count |
| `search_hit_rate` | 검색 적중률 — 유효 근거를 1건 이상 찾은 검색의 비율 (지식 공백 감시) | `kb.search` | output.hits 비어있지 않은 비율(%) |
| `p95_latency` | p95 지연시간 — 판단 루프 각 단계의 꼬리 지연 (스팬별 분리 집계) | `ax.judgment-loop` | 스팬 duration p95(ms), 스팬 이름별 그룹핑 |

운영 시작점 권장 알림: `gateway_rejection_rate` 급등(규칙 문제), `expired_evidence_rate` > 20%(문서 갱신 과제 발제), `circuit_breaker_trips` ≥ 1(즉시 통보).

## 7. 서킷브레이커 / Graceful Degradation

**관측 실패는 절대 비즈니스 로직에 전파되지 않는다.** 계층별 방어:

1. **미설치** — `import langfuse` 실패 시 `LANGFUSE_AVAILABLE=False`, 모든 API가 no-op.
2. **키 누락 / 강제 off** — `load_config().enabled=False`, 클라이언트를 만들지 않는다.
3. **호출 단위 보호막** — 모든 SDK 호출은 `_safe()`를 경유: 예외는 삼키고 실패 횟수만 센다. 래핑된 함수의 반환값·예외는 원본 그대로다.
4. **서킷브레이커** — 연속 오류가 `AX_OBS_CB_THRESHOLD`(기본 5회)에 도달하면 서킷 오픈: 쿨다운(`AX_OBS_CB_COOLDOWN_SEC`, 기본 300초) 동안 SDK 호출 자체를 생략한다. 오픈 시점에 WARNING 로그 1회(`ax.observability` 로거). 쿨다운 경과 후 half-open으로 1회 재시도 — 성공하면 서킷 닫힘(카운터 리셋), 실패하면 재오픈.
5. **샘플링** — `AX_OBS_SAMPLE_RATE < 1.0`이면 루트에서 트레이스 단위로 결정하고, 제외된 트레이스는 자식 스팬까지 통째로 생략한다(반쪽 트레이스 방지).

주의: 게이트웨이 자체의 서킷브레이커(`ActionGateway.forced_human`, 연속 거부 → human-approval 강등)와는 **별개**다. 이쪽은 관측 SDK 장애용이다.

## 8. SDK v3/v4 호환 노트

버전 문자열이 아니라 **클라이언트 속성 존재**로 세대를 감지한다 (`LangfuseTracer._detect`):

| 세대 | 감지 기준 | 사용 API |
|---|---|---|
| v3/v4 (OTel 기반) | `start_as_current_span` 존재 | `with client.start_as_current_span(name=...)` — 부모-자식은 OTel 컨텍스트로 자동 전파 |
| v2 (stateful) | `trace` 호출 가능 | 루트 `client.trace(...)`, 자식은 부모 객체의 `.span(...)`, 종료는 `.end()` — 부모는 내부 스택으로 추적 |

- v3+의 `from langfuse import observe` 데코레이터는 사용하지 않는다 — 이 킷의 데코레이터가 입출력 스키마(근거·거부 사유)를 직접 통제하기 위해서다.
- `Langfuse` 생성자가 없고 `get_client()`만 있는 배포(v3 싱글턴 방식)도 폴백으로 지원한다.
- 알 수 없는 클라이언트(두 속성 모두 없음)는 감지 실패 → 안전하게 비활성.

## 9. 트러블슈팅

| 증상 | 원인 | 조치 |
|---|---|---|
| Langfuse에 아무것도 안 보임 | 키 누락 → `enabled=False` | `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` 설정 확인, `get_tracer().enabled` 출력해 보기 |
| 스팬이 있다가 갑자기 끊김 | 서킷 오픈 (로그에 "서킷브레이커 오픈" WARNING 1회) | 네트워크/호스트 확인. 쿨다운 후 자동 복구. 임계·쿨다운은 `AX_OBS_CB_*`로 조정 |
| 프로세스 종료 직전 트레이스 유실 | 배치 전송 미배출 | 종료 경로에서 `get_tracer().flush()` 또는 `shutdown()` 호출 |
| 일부 트레이스만 기록됨 | 샘플링 | `AX_OBS_SAMPLE_RATE` 확인 (기본 1.0) |
| 켰는데 무조건 비활성 | `AX_OBSERVABILITY_ENABLED=false` 잔존 | 환경변수 제거 또는 `true`로 |
| `LANGFUSE_AVAILABLE=False`인데 설치했음 | 다른 가상환경에 설치됨 | 실행 인터프리터에서 `pip show langfuse` 확인 |
| 스팬 이름이 대시보드 필터와 안 맞음 | 이름 상수 임의 변경 | `observability_config.py`의 `SPAN_*` 상수만 사용 |
| 이중 스팬(같은 호출이 2번 기록) | `instrument()` 외에 데코레이터도 중복 적용 | 한 가지 방식만 사용. `instrument()` 자체는 중복 호출 안전 |
