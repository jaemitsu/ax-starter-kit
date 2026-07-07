---
owner: 데이터플랫폼팀
lastReviewed: 2026-03-20
expires: 2028-03-20
accessLevel: internal
kind: experience
relatedObjects: [Campaign, ExceptionCase]
---
# 사례: 카카오 환불 조정 음수 비용 (2026-03)

## 상황
B광고주 카카오 캠페인에서 spend -12,400원 수신. 검증 실패로 리포트 3일 지연.

## 원인
전월 과금 오류에 대한 카카오 측 환불 조정. 매체 API가 조정액을 음수로 내려보냄.

## 해결
ExceptionCase 오픈 → 매체 어드민에서 조정 내역 확인 → 리포트용 0 처리 + 비고 표기 → 재검증 → 재생성.

## 교훈
음수 비용의 대부분은 환불 조정이다. 매체 어드민 확인을 먼저 할 것.
