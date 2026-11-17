# 시가총액 상위

`!시총`은 코스피·코스닥 시가총액 순위별 상위 8개 종목명과 전일 대비 등락률을
각각 표시한다. 우선주도 포함하며 기업 단위로 합산하지 않는다.
주갤봇 도움말에만 등록한다. 계좌·보유·Domino DB를 조회하지 않는다.

출처는 한국투자증권의 공개 순위 API 하나다.
`GET /uapi/domestic-stock/v1/ranking/market-cap`, TR ID `FHPST01740000`.
`fid_input_iscd=0001`(코스피), `1001`(코스닥), 시장 `J`(KRX),
화면 `20174`, 분류 `0`(보통주·우선주 전체), 가격·거래량 제한 없음.
기존 PC의 KIS 클라이언트 인증·호출 간격을 재사용한다.

공식 계약 확인:
- https://github.com/koreainvestment/open-trading-api/blob/main/examples_user/domestic_stock/domestic_stock_functions.py (`market_cap`)
- https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/market_cap/chk_market_cap.py (응답 컬럼)

`data_rank` 1~8을 사용하며 응답 배열 순서나 등락률로 재정렬하지 않는다.
누락·중복 순위는 다른 종목으로 채우지 않고 해당 시장을 조회 불가로 안내한다.
등락률 미수신은 0%로 표시하지 않는다. 일부 시장 실패 시 다른 시장의 순위는 표시한다.
성공 응답은 시장별 15초, 실패는 5초 캐시하며 만료된 성공 자료로 실패를 숨기지 않는다.
헤더 시각은 KST 조회 시각이며 거래소 체결 시각이라고 표시하지 않는다.

PC에서 실제 KIS 수신 검사(카카오톡 전송·개인 자산 조회 없음):

```powershell
cd C:\KakaoBot\KKanggallbot
C:\KakaoBot\.venv\Scripts\python.exe -m stockbot.verify_market_caps
```

클라우드 모의 API·라우팅 테스트와 PC 실수신은 구분한다. PC 전용 한투 모듈과
인증 설정이 없는 환경에서는 실시간 순위 수신 성공을 주장하지 않는다.
