---
owner: CX플랫폼팀
lastReviewed: 2026-07-07
expires: 2027-01-07
accessLevel: internal
kind: policy
relatedObjects: [Resolution, Contract, Ticket]
---
# 고객 환불 처리 정책

## 원칙
환불 Resolution(kind=환불)은 계약(Contract)의 refundPolicy를 확인하기 전에는 확정할 수 없다 (규칙 R-05).
상담원 단독 환불 처리는 불가하며, 환불 액션의 실행 권한은 CSM에게만 있다.

## 승인 기준
- 30만원 이하: CSM 단독 처리
- 30만원 초과 ~ 300만원: CX 리드 승인
- 300만원 초과 또는 계약 조항 해석이 필요한 건: CX 리드 + 재무 승인

## 절차
1. 티켓에서 환불 요구 확인 → Diagnosis로 원인 기록 (당사 귀책 여부 포함)
2. 고객의 유효한 Contract와 refundPolicy 조회 — 만료·해지 계약은 CSM이 별도 판단
3. 금액 기준 승인 획득 후 환불 Resolution 확정
4. 환불 근거(계약 조항·승인자)를 감사 로그에 기록

## 금지 사항
- 계약 확인 전 고객에게 환불 금액·시점 확정 안내
- 동일 티켓에 대한 중복 환불 (티켓당 환불 1회 — 멱등성)

## 근거
재무 규정 §7(환불), 전자상거래법 청약철회 조항.
