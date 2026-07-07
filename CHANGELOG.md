# Changelog
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
