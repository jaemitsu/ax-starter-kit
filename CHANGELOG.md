# Changelog
## v3.1 (2026-07-08)
- 관측(Observability): Langfuse 통합 모듈 — 판단 루프 단계별 데코레이터(@trace_decision/@trace_gateway/@trace_query/@trace_search), 서킷브레이커, langfuse 미설치 시 graceful degradation, SDK v3/v4 호환 · 셋업 가이드(docs/observability-setup.md)
- 골든셋 24→100문항: routing 60 (graph/policy/experience 각 20) · hit@3 30 · top-1 10, 양 도메인 균등, 난이도(easy/medium/hard)·엣지케이스(ambiguous/multi-hop/negation) 태그 · run_evals.py 난이도별 게이트(easy/medium 전수, hard ≥ 90%)
- 온톨로지 개선: lifecycle transitions 미정의 타입 전건 보완(ad-reporting 4종 + ExceptionCase 보류 전이, customer-support 7종), properties 미정의 4종(ReportTemplate/Diagnosis/KBArticle/SLAPolicy) 정의
- customer-support v0.9.0→v1.0.0 승격: glossary 추가, 재오픈 판정 기준 확정(30일+동일 category+동일 rootCause), 미확정 항목 해소
- customer-support 지식팩(packs/customer-support.pack.yaml) · CS 정책 3종(escalation-sla, refund-policy, ticket-reopen) · CS 사례 2종(P1 에스컬레이션 지연, 중복 결제 이중 처리)
## v3.0 (2026-07-07)
- 지식 레이어: MD 정본 로더(frontmatter·구조 청킹·제목 색인), BM25 검색(만료 경고, 접근 필터, 관련성 임계치), 질의 라우터(graph/policy/experience, 동점 시 규범 우선)
- 판단 루프 v2: Grounded Decision Loop 완성 — 근거(grounds) 없는 행동 차단, 만료 문서 단독 근거 금지, 감사 로그에 근거 ID 기록
- 학습 루프: 반복 거부→규칙 후보, 에스컬레이션→자율성 재검토, 무근거 질의→지식 갭, 라우팅 의심→평가셋 보강
- 평가 하네스: 골든셋 24문항 (라우팅 14/14, hit@3 8/8, top-1 2/2 통과) — 개발 중 실결함 3건 검출·수정 (kind 메타 누락, 제목 미색인, 라우팅 동점 처리)
- 운영 대시보드 + 골든 세션 예제(정산 도메인) 추가 · pytest 13→21종
## v2.0 (2026-07-07)
- 런타임: OntologyStore, Action Gateway, MCP 서버, E2E 시나리오, pytest 13종 · customer-support 도메인 · SHACL 경계 리터럴 수정
## v1.0 (2026-07-07)
- 초기 킷: 정본 스키마, 검증 CI, ad-reporting, 커널, 도메인 팩
