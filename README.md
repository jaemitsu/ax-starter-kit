# AX Ontology Starter Kit

AX(AI Transformation)의 핵심인 온톨로지 저장소 스타터 킷.
`ax-adoption-roadmap.md`의 **Stage 0(기반 구축)** 을 그대로 구현한 실행 가능한 자산이다.

## 빠른 시작
```bash
pip install rdflib pyshacl pyyaml
python tools/validate.py domains/ad-reporting
```
검증 통과 시: 구조 검사(Definition of Done) → OWL/SHACL 자동 생성(exports/) → 테스트 인스턴스 규칙 검증까지 완료.

## 구조
```
kernel/kernel.yaml                    # 공유 커널 (Party, Document, ExceptionCase 원형)
domains/ad-reporting/
  ontology-state.yaml                 # ★ 정본 (빌더 에이전트가 읽고 쓰는 유일한 진실)
  tests/instances.ttl                 # 테스트 인스턴스 (실사례 기반)
  tests/expected.yaml                 # 기대 위반 목록 (오탐/미탐 검출)
  exports/                            # 자동 생성 파생물 (수정 금지)
packs/advertising.pack.yaml           # 도메인 지식 팩
tools/validate.py                     # 검증 CI 본체
.github/workflows/ontology-ci.yml     # PR마다 자동 검증
knowledge/                            # MD 지식 정본 골격 (llms.txt + 정책 예시)
governance/owners.yaml                # 승인 매트릭스
```

## 새 도메인 추가 방법
1. `domains/<이름>/` 생성, `ontology-state.yaml`을 복사해 초기화
2. 빌더 에이전트(`ontology-builder-agent.md` v3.0)로 Phase 0~6 진행하며 정본 갱신
3. 규칙 중 기계 검증 가능한 것에 `check:` 블록 추가 → 자동 SHACL 변환
4. `tests/`에 실사례 기반 인스턴스와 기대 위반 작성
5. PR → CI 통과 → 도메인 owner 승인 → 릴리스 태그

## 런타임 (Stage 2 — 검증 완료)
```
runtime/store.py           # OntologyStore: get_object / trace_lineage / check_rules / blocking_cases / resolve_term
runtime/gateway.py         # Action Gateway: 권한→자율성→승인→사전조건→멱등성→효과→감사 + 서킷브레이커
runtime/mcp_server.py      # MCP 서버 (stdio): 좁은 도구 6종 — 범용 질의 미노출
runtime/scenario_demo.py   # E2E 판단 루프 데모: python runtime/scenario_demo.py
tests_runtime/             # pytest 13종: python -m pytest tests_runtime/
```

### Claude에 MCP 서버 연결
```json
{"mcpServers": {"ax-ontology": {
  "command": "python3",
  "args": ["<킷 경로>/runtime/mcp_server.py",
           "<킷 경로>/domains/ad-reporting",
           "<킷 경로>/runtime/sample-instances.ttl"]}}}
```
연결 후 Claude에게 "run2가 왜 막혔는지 확인하고 처리해줘"라고 하면
get_object → trace_lineage → check_rules → execute_action 흐름이 그대로 동작한다.

### 프로덕션 전환 시 교체 지점
- `OntologyStore`의 rdflib 인메모리 그래프 → Neo4j/RDF 스토어 (인터페이스 유지)
- `system_complete_run` → 실제 스케줄러 이벤트 구독
- Gateway 승인 토큰 → 실제 결재/슬랙 승인 워크플로 연동
- 감사 로그 → 불변 스토리지

## 지식·판단 레이어 (Stage 2 확장 — 검증 완료)
```
runtime/kb.py           # 지식 레이어: MD 정본 로더, BM25 검색(만료 경고·권한 필터), 질의 라우터
runtime/decision.py     # Grounded Decision Loop: 라우팅→근거 수집→행동. 근거 없는 행동은 게이트웨이 이전 차단
runtime/feedback.py     # 학습 루프: 감사 로그→규칙 후보·자율성 재검토·지식 갭·평가셋 보강
runtime/scenario_v2.py  # 3레이어(Graph/정책/사례) 전부 쓰는 완전한 판단 루프 데모
evals/                  # 골든셋(라우팅 14·검색 10) + run_evals.py — 변경 시 회귀 필수
dashboard/              # gen_dashboard.py → ax-dashboard.html (객체·규칙·감사 로그 시각화)
docs/golden-session-example.md  # 빌더 에이전트 모범 세션 기록 (교육·품질 기준)
```
