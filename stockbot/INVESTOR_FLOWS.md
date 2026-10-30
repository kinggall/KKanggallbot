# !수급

한투 시장별 투자자매매동향(시세) API의 개인·외국인·기관 순매수를 표시합니다.
총매수액이 아니라 매수−매도입니다. 계좌/개인 보유자료는 읽지 않습니다.

```text
[투자자 순매수 · 억원]

🇰🇷 코스피
   개인 +1,234 / 외국인 -3,456
   기관 +2,222
```

위 숫자는 레이아웃 예시입니다. 코스피·코스닥·선물·콜옵션·풋옵션 순으로 표시합니다.
순매수 대금 *_ntby_tr_pbmn을 사용하며 수량 *_ntby_qty를 금액으로 오인하지 않습니다.
시장별 거래대금 원자료 백만원을 100으로 나누어 억원으로 표시합니다. 선물/옵션의 거래대금은
현물의 매수 자금과 같은 의미가 아니며 옵션은 옵션 거래대금입니다. 다섯 시장을 합산하지 않습니다.
수신 단위와 HTS 0403의 실제 금액 대조는 PC 실조회 검증이 필요합니다.

공식 Postman v2.6에서 확인한 요청:
- GET /uapi/domestic-stock/v1/quotations/inquire-investor-time-by-market
- TR FHPTJ04030000
- 코스피 KSP/0001, 코스닥 KSQ/1001
- KOSPI200 선물 K2I/F001, 콜 K2I/OC01, 풋 K2I/OP01
- 미니·위클리·주식선물은 섞지 않습니다.

근거:
https://github.com/koreainvestment/open-trading-api/blob/main/legacy/postman/실전계좌_POSTMAN_샘플코드_v2.6.json
https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock/inquire_investor_time_by_market

상단 현재 집계표를 읽으며, 일별 자료로 대체하거나 여러 행을 임의 합산하지 않습니다.
원본 집계 시각을 명세에서 확인하지 못했으므로 footer는 요청한 한국시간입니다.
휴장/장외에 마지막 집계가 반환될 수 있으며 틱 실시간이라고 보장하지 않습니다.
15초 성공 캐시·5초 실패 캐시를 사용하고, 실패한 시장은 다른 시장과 분리합니다.
비어 있는 투자자 값은 0으로 채우지 않습니다. 실패 시 만료된 성공값을 재전송하지 않습니다.

사용자 도움말은 !주갤에만 추가하고 공용 사용방법·대문에는 넣지 않습니다.
PC 실조회는 python -m stockbot.verify_flows로 공개 수급 원자료와 성공 여부를 확인합니다.
클라우드의 가상 응답 테스트는 실제 API 응답/권한/집계 단위 검증을 대신하지 않습니다.
