---
owner: 리포트 운영팀
lastReviewed: 2026-07-07
expires: 2027-01-07
accessLevel: internal
kind: policy
relatedObjects: [ReportRun, ExceptionCase]
---
# 리포트 재생성 정책

## 전달 전 재생성
실패한 ReportRun은 연관 ExceptionCase가 모두 '해결' 상태이면 자동 재생성할 수 있다 (AI 자동 1회).

## 전달 후 재생성
광고주에게 이미 전달된 리포트의 재생성은 **팀장 승인 필수**. 사유와 승인 이력을 감사 로그에 남긴다.
근거: 과거 정정 사고에 따른 감사 대응 (합의 기록 CF-02).
