# 미국 종목 검색 사전 수집·검증

수집일: 2026-10-29 (한국시간). 가격·보유량·계좌 데이터는 포함하지 않습니다.
이 문서는 stockbot 내부 기록이며 GitHub 대문이나 웹 깡갤봇으로 내보내지 않습니다.

## 범위

- NASDAQ/NYSE/AMEX 공개 목록과 S&P 목록을 합친 원본 레코드 6,638개.
- BRK.B/BRK/B, BF.B/BF/B 같은 클래스 표기를 병합한 미국 티커 6,636개.
- 한글 검색명 보유 종목 559개. 나머지는 영문 정식명·티커 검색 지원.
- 수집한 S&P 500 목록의 503개 증권 항목 모두 한글 검색명 보유.
- 대신증권 첨부 PDF의 미국 종목 490행을 전부 추출. 뒤의 일본 222종목은 제외.
- PDF는 2020년 상반기 자료. 같은 심볼이 공개 목록에 없는 68개는
  `us_catalog_data.HISTORICAL_ONLY`로 보관하고 현재 티커 별명으로 자동 사용하지 않음.
  이는 모두 상장폐지라는 뜻이 아니라 수집 목록에서 현행 연결을 확인하지 못했다는 뜻.

한글명은 PDF 표기에 더해 신규/영문-only 항목의 검색 표기를 수동 보완했습니다.
공식 한국어 법인명 전체를 수집했다고 주장하지 않습니다. 최신 영어 법인/증권명은 공개
거래소 목록에서 가져왔습니다. 수집 당시 스냅샷이며 향후 사명·구성 변경을 자동 보증하지
않습니다. 데이터셋 출처는 거래소 공식 API 자체가 아니라 공개 미러입니다.

## 요청한 연결

- 스페이스X / 스페이스엑스 / 스엑 / SpaceX → SPCX.
  공개 목록: Space Exploration Technologies Corp. Class A Common Stock.
- 하닉ADR / 하이닉스 ADR / 하이닉스(ADR) → SKHY.
  공개 목록: SK hynix Inc. American Depositary Shares.
- 오라클 → ORCL. 코어위브 → CRWV.
- 마이크론 → MU를 첫 번째, 하나마이크론을 두 번째 선택지로 표시.
  자동 조회하지 않으며 MU 또는 하나마이크론 정식명/티커로 구분.
- 구글/버크셔 등 기존 명시적 별명 우선순위는 유지.

## 출처와 재수집

`us_catalog_data.py`에 수집 시각, 원본별 SHA-256과 URL을 기록합니다.

- https://github.com/rreichel3/US-Stock-Symbols
  - nasdaq/nasdaq_full_tickers.json
  - nyse/nyse_full_tickers.json
  - amex/amex_full_tickers.json
- https://github.com/datasets/s-and-p-500-companies/blob/main/data/constituents.csv
- 사용자 첨부: 대신증권 「2020년 상반기 해외주식담보대출 가능종목 현황」 미국 490종목.

클라우드에서 `pdftotext`와 requests가 설치된 환경을 사용합니다.

```sh
python stockbot/collect_us_catalog.py --pdf /path/to/490종목.pdf
python -m unittest discover -s stockbot -p 'test_*.py'
```

재수집 시 PDF 행 수와 S&P 한글명 누락을 검사하며, 신규 S&P 종목의 한글명이 없으면
데이터 파일을 교체하기 전에 실패합니다. `KOREAN`에 검색 표기를 보완한 후 재검증합니다.
가격 필드는 수집 원본에 있어도 저장하지 않으며 거래소·종목명·심볼만 사용합니다.

## 검증 범위

사전의 모든 S&P 한글 검색명이 미국 시세 조회 또는 명시적인 복수 후보 선택으로
이어지는지 가상 한투 응답으로 전수 검사했습니다. PDF 490행과 출처 해시도 검사합니다.
기존 국내 별명, ETF 브랜드, 보유/실현 검색 회귀 테스트를 함께 실행합니다.
클라우드에는 PC의 한투 인증이 없으므로 6,636종목 전체의 실제 API 성공·시세 권한·상장
상태를 확인했다는 의미는 아닙니다. 실제 조회 시 기존 한투 응답의 심볼/통화/가격 검증을
통과한 경우에만 시세를 표시합니다.
