---
owner: CX플랫폼팀
lastReviewed: 2026-07-07
expires: 2027-01-07
accessLevel: internal
kind: policy
relatedObjects: [Ticket, Resolution]
---
# 티켓 재오픈 판정 정책

## 판정 기준
종결된 티켓과 **동일 category + 동일 근본 원인(rootCause)**의 문의가 **종결 후 30일 내** 접수되면
신규 티켓이 아니라 기존 티켓을 재오픈한다. 다음 중 하나면 신규 티켓으로 접수한다:
- 종결 후 30일 초과
- category는 같으나 Diagnosis의 rootCause가 다름
- 다른 고객 계정에서 발생한 동일 증상 (고객별 티켓 분리 원칙)

## 왜 이 기준인가
재오픈률은 해결 품질 지표다. 판정이 상담원 재량에 맡겨지면 재오픈률과 신규 티켓 수가 모두 오염되어
반복 문의 분석(CQ-05)이 불가능해진다.

## 절차
1. 접수 시 동일 고객의 최근 30일 종결 티켓을 category로 조회
2. 후보가 있으면 Diagnosis 비교 — rootCause 동일 시 재오픈, 상이 시 신규 접수 후 관련 티켓 링크
3. 재오픈 시 기존 배정 상담원에게 우선 라우팅, 2회째 재오픈부터 에스컬레이션 검토

## 근거
CX 리드 합의 CF-11 (2026-07), 온톨로지 Ticket lifecycle 전이 조건과 동기화됨.
