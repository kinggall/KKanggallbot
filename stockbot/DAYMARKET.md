# 미국 데이마켓

한투 공식 `price-detail` REST API의 BAQ(나스닥), BAY(뉴욕), BAA(아멕스)를 사용한다.
일반시장 last를 직전 정규장 종가로, 데이마켓 last를 현재가로 비교한다.
데이마켓 응답의 base는 정규장 종가와 다를 수 있어 비교 기준으로 쓰지 않는다.
유효한 USD/종목 응답을 받았을 때만 데이마켓으로 표시한다.
주간 미수신 시 기존 일반 시세를 유지하며 데이마켓이라고 표시하지 않는다.
현재가 수신 여부는 확인 가능하지만 API 체결시각/휴장 여부는 이 검사로 보증하지 않는다.

봇 PC의 저장소 디렉터리에서 실제 데이마켓 시간에 실행:

```powershell
C:\KakaoBot\.venv\Scripts\python.exe -m stockbot.verify_daymarket IREN
```

이 검사는 공개 시세만 출력하며 인증정보나 보유 데이터를 출력하지 않는다.
클라우드 모의 검증 195개 통과. 클라우드에는 PC 한투 모듈/인증이 없어 실수신은 미검증.

공식 근거: koreainvestment/open-trading-api의
examples_llm/overseas_stock/price_detail/chk_price_detail.py (BAQ/BAY/BAA).
