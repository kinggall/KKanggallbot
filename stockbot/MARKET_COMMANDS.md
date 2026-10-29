# 시장 지표 명령어

주식/계좌 명령과 분리된 읽기 전용 지표 조회입니다. `!주갤` 도움말에만 추가합니다.
표시: `🇺🇸 S&P500: 7,713.83 (▼30.20, ▼0.39%)`.
값과 증감의 자릿수는 지표 단위에 맞추며, 현재 값·증감 수치·증감률을 같은 원본/기준으로
계산합니다. 값이 누락되면 0으로 채우지 않습니다. API 오류/응답 본문/인증값은 전송하지 않습니다.

| 명령어 | 대상/기준 | 제공처 |
| --- | --- | --- |
| !국내지수 | 코스피/코스닥 현물 지수 | Yahoo Finance ^KS11/^KQ11 |
| !미국지수 | S&P500/나스닥종합/다우 | Yahoo Finance ^GSPC/^IXIC/^DJI |
| !나선 | 나스닥100 연속 선물 | Yahoo Finance NQ=F |
| !야선 | KOSPI200 근월물 중 확인된 야간 분봉 | 한투 읽기 전용 선물 시세 |
| !환율 | USD/KRW, 달러인덱스 | Yahoo Finance KRW=X/DX-Y.NYB |
| !상품 | 금/은/WTI/천연가스/구리 연속 선물 | Yahoo Finance GC/SI/CL/NG/HG=F |
| !미국채 | 2/5/10/30년 일별 공시 수익률 | 미국 재무부 |
| !국채 | 2/5/10/30년 국고채 일별 공시 수익률 | 한국은행 ECOS 817Y002 |
| !코인 | BTC/ETH/XRP 원화 시장, UTC 0시 대비 | 업비트 공개 ticker API |

금리 절대 증감은 `%p`이며 증감률(%)과 구분합니다. 금리는 채권 가격이나 투자 수익률이
아니며 실시간 체결 금리라고 주장하지 않습니다. 발표일을 표시합니다. 선물은 월물 교체에
따라 연속 선물 기준이 바뀔 수 있고 데이터 제공처의 지연이 있을 수 있습니다.
각 응답 하단에 실제 원본 기준 시각(한국시간) 또는 공시 날짜와 제공처를 표시합니다.

일반 조회 캐시는 15초, 공식 금리는 10분입니다. 실패 시 오래된 성공 값을 새 시세처럼
재전송하지 않습니다. 일부 항목 실패는 해당 줄의 `조회 불가`로 분리합니다.
공개 HTTP 요청은 최소 0.25초 간격으로 조절하며 같은 지표 요청은 짧게 캐시합니다.
공개 API가 인증/차단/요청 제한을 적용하면 별도 운영 설정이 필요할 수 있습니다.

## 야간 선물

기존 Domino `Client`의 인증과 호출 간격만 재사용하고 원본 모듈/ALLOWED 표는 수정하지
않습니다. 자체 어댑터는 고정된 한국투자 호스트의 두 quotations 경로만 GET으로 호출합니다.
계좌 조회/거래 주문 API를 호출하지 않습니다.

- 선물 전광판에서 `101` 계열 KOSPI200 근월물을 찾습니다. 고정된 만기 코드를 쓰지 않습니다.
- 분봉의 날짜/시간이 야간(18시 이후~06시 종가)임을 검증한 자료만 표시합니다.
- 주간 현재가를 야간 시세라고 바꾸지 않습니다. 확인된 야간 분봉이 없으면 실패합니다.
- 기본 시세가 야간 분봉과 같고 현재 야간 시간대일 때만 동일 원본 전일종가로 증감을 계산.
  아니면 야간 가격만 표시하고 증감을 미확인으로 남깁니다.
- 브로커가 야간 영업일을 다음 영업일로 기록하여 달력 체결일과 다르거나 이 REST 경로에서
  야간 자료를 제공하지 않으면 엄격한 검증에서 실패할 수 있습니다. PC 실응답 확인 전
  야간 실조회 지원 완료라고 보지 않습니다. 정규장 선물/ETF로 대체하지 않습니다.

공식 API 경로/필드는 아래 공개 예제에서 확인했습니다.

- https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_futureoption/display_board_futures
- https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_futureoption/inquire_time_fuopchartprice

## 국고채

ECOS 메타데이터에서 실제 `국고채(2년/5년/10년/30년)` 항목 코드와 최근 날짜를 조회합니다.
만기 코드를 추정해 하드코딩하지 않습니다. 메타데이터는 1시간 후 다시 확인합니다.
기본은 ECOS sample 키이며 제한으로 실패할 경우 PC 비밀 환경변수
`KAKAO_ECOS_API_KEY`에 발급된 키를 설정해야 합니다. 키를 Git/Drive/채팅에 올리지 않습니다.
발표일은 수신한 DATA_VALUE의 TIME을 사용합니다.

## PC 실조회 검증

클라우드 프록시에서 Yahoo/재무부/ECOS 등 금융 사이트 접속이 차단됐습니다.
자동 테스트는 가상 응답으로 포맷/종목 검증/지표 매핑/장애 격리/야간 시간 필터를 검사합니다.
실제 사이트 응답·권한·샘플키 제한·야간 제공 여부는 PC 검증이 필수입니다.
인증값·개인 계좌·자산 수치·카카오 메시지 전송 없이 각 항목의 성공 여부를 출력합니다.

```powershell
cd C:\KakaoBot\KKanggallbot
C:\KakaoBot\.venv\Scripts\python.exe -m stockbot.verify_markets
```

일부만 검사하려면 뒤에 명령 이름(느낌표 제외)을 붙입니다.
예: `python -m stockbot.verify_markets 미국지수 야선 국채`.

공식 데이터 출처:

- https://home.treasury.gov/resource-center-data-chart-center/interest-rates/pages/xml
- https://ecos.bok.or.kr/
- https://docs.upbit.com/kr/reference/list-tickers
- https://finance.yahoo.com/
