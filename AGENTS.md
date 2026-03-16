# CRYPTORADAR

한국 및 글로벌 암호화폐 뉴스를 수집하고 주요 코인, 거래소, 규제 동향을 분석합니다.

## STRUCTURE

```
CryptoRadar/
├── cryptoradar/
│   ├── collector.py              # collect_sources() — RSS 수집 (블록미디어, 코인텔레그래프, 코인리더스, 디센터)
│   ├── analyzer.py               # apply_entity_rules() — 암호화폐, 거래소, 규제, 기술, 시장 키워드 매칭
│   ├── reporter.py               # generate_report() — Jinja2 HTML
│   ├── storage.py                # RadarStorage — DuckDB upsert/query/retention
│   ├── models.py                 # radar-core 모델 재사용 (Source, Article, EntityDefinition, CategoryConfig)
│   ├── config_loader.py          # YAML 로딩
│   ├── logger.py                 # structlog 구조화 로깅
│   ├── resilience.py             # 서킷 브레이커 관리
│   └── exceptions.py             # NetworkError, ParseError, SourceError
├── config/
│   ├── config.yaml               # database_path, report_dir
│   └── categories/crypto.yaml    # 소스 + 엔티티 정의
├── data/                         # DuckDB, radar_data.duckdb
├── reports/                      # 생성된 HTML 리포트
├── tests/unit/                   # pytest 단위 테스트
├── main.py                       # CLI 엔트리포인트
└── .github/workflows/radar-crawler.yml
```

## SOURCES

| Source | URL | Type |
|--------|-----|------|
| 블록미디어 | https://www.blockmedia.co.kr/feed | RSS |
| 코인텔레그래프 | https://cointelegraph.com/rss | RSS |
| 코인리더스 | https://www.coinreaders.com/feed | RSS |
| 디센터 | https://www.decenter.kr/rss/S1N29.xml | RSS |

## ENTITIES

| Entity | Examples |
|--------|----------|
| 암호화폐 | 비트코인, 이더리움, 리플, 솔라나, 도지코인, 스테이블코인 |
| 거래소 | 업비트, 빗썸, 바이낸스, 코인베이스, 코빗 |
| 규제/정책 | 금융위, 특금법, 가상자산법, SEC, KYC/AML |
| 기술 | 블록체인, DeFi, NFT, 레이어2, 스마트컨트랙트, Web3 |
| 시장 | 시세, 급등/급락, 시가총액, 거래량, 고래, 강세/약세 |

## ARCHITECTURE

- **radar-core 의존성**: models.py는 radar-core 패키지에서 공유 모델을 재사용합니다.
- **적응형 스로틀링**: collector.py는 AdaptiveThrottler와 CrawlHealthStore를 사용해 소스별 요청 속도를 동적으로 조절합니다.
- **서킷 브레이커**: resilience.py는 pybreaker로 장애 소스를 자동 차단합니다.
- **EUC-KR 인코딩 지원**: 한국 .kr 사이트의 EUC-KR 인코딩을 자동 감지하고 처리합니다.

## DEVIATIONS FROM TEMPLATE

- radar-core 패키지 의존성으로 모델 재사용
- 적응형 스로틀링 및 크롤링 헬스 모니터링
- 서킷 브레이커 패턴으로 장애 격리
- EUC-KR 인코딩 자동 감지

## COMMANDS

```bash
python main.py --category crypto --recent-days 7
python main.py --category crypto --per-source-limit 50 --keep-days 90
pytest tests/
```

## DO NOT MODIFY

- `cryptoradar/models.py`: radar-core 재사용 모델, 수정 금지
- `config/categories/crypto.yaml`: 소스 URL 및 엔티티 정의, 신중히 수정

## TESTING

```bash
pytest tests/unit/
```

## NOTES

- 소스 추가 시 `config/categories/crypto.yaml`에 RSS URL 추가
- 엔티티 추가 시 동일 파일의 `entities` 섹션에 키워드 추가
- 수집 오류는 리포트 하단에 표시됨
- DuckDB는 `data/radar_data.duckdb`에 저장, GitHub Pages에 배포되지 않음
