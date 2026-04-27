# Data Quality Plan

- 생성 시각: `2026-04-11T16:05:37.910248+00:00`
- 우선순위: `P2`
- 데이터 품질 점수: `83`
- 가장 약한 축: `교차 검증`
- Governance: `medium`
- Primary Motion: `intelligence`

## 현재 이슈

- 현재 설정상 즉시 차단 이슈 없음. 운영 지표와 freshness SLA만 명시하면 됨

## 필수 신호

- 거래소 상장·상폐 공지
- 규제기관 발표와 enforcement action
- 온체인 지표와 거래량·유동성 신호

## 품질 게이트

- 뉴스/소셜 심리와 거래소 공식 공지를 분리
- ticker collision을 chain/project canonical key로 정리
- 가격 시각·거래소·통화 기준을 명시

## 다음 구현 순서

- 상장/상폐 공지와 규제기관 source를 공식/운영 레이어로 추가
- on-chain metric source를 별도 검증 레이어로 연결
- ticker/project canonicalization rule과 exchange coverage 리포트를 추가

## 운영 규칙

- 원문 URL, 수집일, 이벤트 발생일은 별도 필드로 유지한다.
- 공식 source와 커뮤니티/시장 source를 같은 신뢰 등급으로 병합하지 않는다.
- collector가 인증키나 네트워크 제한으로 skip되면 실패를 숨기지 말고 skip 사유를 기록한다.
- 이 문서는 `scripts/build_data_quality_review.py --write-repo-plans`로 재생성한다.
