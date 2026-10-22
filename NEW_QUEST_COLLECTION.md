# 신규 임무 페이지 저장

점검 후 수동으로 한 번 실행한다. 주기 실행이나 제카마시 수집은 하지 않는다.
필요 패키지는 `requests`, `beautifulsoup4`이다.

```powershell
C:\KakaoBot\.venv\Scripts\python.exe -m pip install requests beautifulsoup4
C:\KakaoBot\.venv\Scripts\python.exe C:\KakaoBot\KKanggallbot\scripts\collect_new_quests.py
```

robots.txt 확인 후 최소 10초 기다리고 신규 임무 페이지를 한 번 요청한다.
리다이렉트·접근 거부·오류에 자동 재시도하거나 인증을 우회하지 않는다.
`#New` 영역이 없는 응답은 정상 자료로 저장하지 않는다.

저장 위치: `C:\KakaoBot\KKanggallbot\guide_cache\wikiwiki_new\수집시각\`

- `page.html`: 원본 페이지 전체(표 구조 보존)
- `page.txt`: 검토용 텍스트
- `manifest.json`: 출처·수집 시각·HTML 해시

새 폴더에 저장하여 기존 수집본을 덮어쓰지 않는다. Git에는 포함하지 않는다.
이미지·외부 링크·다른 페이지는 다운로드하지 않으며, 임무 DB나 봇 동작은 변경하지 않는다.
이 단계는 원문 확보용이다. 신규 임무 추출·번역·기존 조건과의 대조 및 반영은 별도 작업이다.

PC에서도 접속이 막히면 브라우저에서 HTML(UTF-8) 또는 응답 본문을 포함한 HAR를
저장하고, 네트워크 요청 없이 가져올 수 있다.

```powershell
C:\KakaoBot\.venv\Scripts\python.exe C:\KakaoBot\KKanggallbot\scripts\collect_new_quests.py --input "C:\KakaoBot\new_quests.html"
```

HAR도 동일하게 `--input "C:\KakaoBot\new_quests.har"`로 지정한다.
HAR 전체에는 민감한 헤더가 있을 수 있으므로 공개하지 않는다. 수집기는 대상 페이지의
정상 응답 HTML만 가져오며 쿠키·요청 헤더를 결과에 복사하지 않는다.
