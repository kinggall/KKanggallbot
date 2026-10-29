# 주식 명령어와 검증

이 기록은 GitHub 대문이나 깡갤봇 일반 도움말에 추가하지 않습니다.
주식 도움말은 `!투자`만 사용합니다. 실제 자산 JSON·인증·검증 응답은 저장하지 않습니다.

## 명령어

- `!주가 두산에너빌리티`: 한투 국내 통합 시세. 화면에는 `통합` 표시.
- `!주가 DRAM` / `!주가 AAPL`: 미국 NAS/NYS/AMS만 조회. 영문 티커를 국내 부분검색보다 우선합니다.
- `!보유`: Domino 보유종목·수량.
- `!평단 삼성전자`: 계좌별 평균 매입가.
- `!수익률 삼성전자`: JSON의 보유 수익률·평가손익.
- `!실현`: 조회 가능한 실현 종목 목록.
- `!실현 삼성전자`: JSON의 계좌·기간별 실현 수익률·손익.

사용자 요청으로 모든 방에서 자산 명령어를 허용합니다. 명령어를 아는 다른 사용자도
조회할 수 있습니다. 계좌명은 표시하지만 내부 account_id는 출력하지 않습니다.
서로 다른 계좌·기간·통화 수익률을 합산하거나 재계산하지 않습니다.

## Drive와 시간

`portfolio.py`는 Domino JSON을 Drive에서 읽기만 합니다. UTF-8로 명시적으로 해석하며
메모리 캐시 30초 외에는 보관하지 않습니다. 캐시 만료 후 읽기에 실패하면 이전 값을
새 자료로 내보내지 않습니다. 생성 시각·보유 수집 시각과 수익률의 시세 기준을 표시합니다.

PC는 기존 `cloud/token.json`을 사용하며 `KAKAO_STOCK_DRIVE_TOKEN_FILE`로 변경 가능합니다.
클라우드는 기존 GOOGLE_DRIVE OAuth 환경변수를 사용합니다.
다른 JSON을 사용할 경우 `KAKAO_STOCK_PORTFOLIO_FILE_ID`를 설정합니다.

국내 시간대: 평일 08:00–08:50 NXT 프리, 09:00–15:30 정규장,
16:00–20:00 NXT 애프터. 미국 시간대는 뉴욕 기준 프리/정규/애프터이며 DST를 적용합니다.
시간대 표시는 실제 휴장 여부, 거래정지, NXT 대상 여부 또는 장외 시세의 수신을 보증하지
않으므로 응답에도 이를 명시합니다. 조회시각은 거래 체결시각이 아닙니다.

## 검증

```sh
python -m unittest discover -s stockbot -p 'test_*.py'
python -m unittest discover -s tests
```

자동 검증은 가상 데이터만 사용하며 실제 카카오 메시지를 전송하지 않습니다.
실제 Drive JSON의 모든 보유/실현 종목 렌더링도 확인했습니다(개인 수치는 출력·저장하지 않음).
기존 테스트 327개와 별도 stockbot 테스트를 실행합니다.

한투 PC 모듈과 인증은 클라우드에 없으므로 실제 통합·미국 시세 성공은 별도 PC 검증이
필요합니다. 첨부된 실제 모듈에서 DOMESTIC/OVERSEAS는 문자열 경로이고, query가
ALLOWED 표에서 TR ID를 선택하는 것을 확인했습니다. 해외 조회에는 설치된 OVERSEAS
`/uapi/overseas-price/v1/quotations/price-detail` 경로를 그대로 전달합니다.
DOMESTIC 구조를 추측해 경로/TR ID를 치환하던 초기 연결 방식은 제거했습니다.
실제 모듈의 Client.query를 가상 전송으로 검사하되, 실제 한투 실조회와 구분합니다.

PC에서 아래 명령은 자산 값이나 시세 값을 출력하지 않고 성공 여부만 검사합니다.
카카오 메시지를 보내거나 Domino DB를 수정하지 않습니다. 실패 시 종료코드는 1입니다.

```powershell
C:\KakaoBot\.venv\Scripts\python.exe -m stockbot.verify
```

저장소 루트에서 실행합니다. 미국 조회를 위한 시세 권한/계약·지연 여부는 한투 설정에
따릅니다. 외부 Domino 저장소는 수정하지 않습니다.

공식 API 참고:

- https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_price/inquire_price.py
- https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/overseas_stock/price_detail/price_detail.py
