---
owner: 데이터플랫폼팀
lastReviewed: 2026-06-15
expires: 2026-12-15
accessLevel: internal
kind: policy
relatedObjects: [ExceptionCase, CleanDataSet, Campaign]
---
# 데이터 보정 정책

## 원칙
원천 데이터(RawAdPerformance)는 절대 수정하지 않는다. 보정은 리포트용 데이터에만 적용하며 원본은 보존한다.

## 절차
1. ExceptionCase가 '처리 중' 상태여야 한다.
2. 보정 사유(reason)를 반드시 기록한다 — 감사 요건.
3. 보정 후 해당 CleanDataSet은 재검증(validate)을 거쳐야 리포트에 사용할 수 있다.

## 음수 비용
매체 환불 조정으로 음수 비용이 수신될 수 있다. 이는 오류가 아니라 확인 대상이며,
확인 후 리포트 표기 방식(0 처리 또는 조정 표기)은 광고주 계약 조건을 따른다.
