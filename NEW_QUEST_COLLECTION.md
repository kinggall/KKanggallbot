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

## 2026년 10월 14일 임무 반영

2026-10-22에 제공된 HTML의 12개 행을 검토해 `data/quest_wiki_updates.json`에
번역·조건·보상·명시된 선행조건과 원문 행을 보존했다.
대상: `2610 B1~B8`, `2610 C1`, `2610 F1~F2`, `B218`.
`data/quests.json`의 기존 652개는 수정하지 않고, 명령어와 공략 수집기가 같은
`quest_updates.apply_updates`를 통해 12개를 추가해 총 664개를 사용한다.
기존 데이터 재생성 후에도 추가 자료가 유지된다.

내부 게임 ID는 추정하지 않는다. 원본 DB에 없는 번호에는 `wiki:2610B1`처럼
로컬 키를 사용한다. 위키에서 비어 있는 선행조건 `()`는 추가하지 않는다.
명시된 선행 연결만 역산하므로 후속 목록도 현재 확인된 범위이며 완전성을 보장하지 않는다.
현재 12개 모두 위키의 선행조건 검증중 표기를 보존한다.
기간한정/단발·주간·월간을 별도로 표시한다. B218은 일반 단발 임무다.

원문 재검증 및 재생성:

```powershell
C:\KakaoBot\.venv\Scripts\python.exe C:\KakaoBot\KKanggallbot\scripts\import_new_quests.py "C:\KakaoBot\KKanggallbot\guide_cache\wikiwiki_new\수집시각\page.html"
```

`data/new_quest_review.json`의 검토한 행 해시와 다르면 중단한다. 다음 점검의 새 임무나
수정된 행은 별도 검토·번역 후 허용해야 하며, 이 도구는 미검토 조건을 자동 번역해 확정하지 않는다.

신규 12개만 제카마시 검색·수집:

```powershell
C:\KakaoBot\.venv\Scripts\python.exe C:\KakaoBot\KKanggallbot\scripts\collect_zekamashi.py --new
```

네트워크 접속 없이 대상만 확인하려면 `--new --dry-run`을 사용한다.
한 개 시험은 `--new --codes B218` 또는 `--new --codes 2610B1`이다.
일본어 임무명과 본문 H1 일치를 확인하고, 후보가 없거나 여러 개면 자동 연결하지 않는다.
출격 9개는 기존 `編成例`·사진 수집을 사용한다. 연습·공창 3개는 본문 텍스트를 저장하고
편성 사진을 가정하지 않는다. 해당 `!공략`은 조건 조회 명령과 원문 링크를 안내한다.
자동 재시도/접속 우회는 하지 않으며 10초 이상 간격, 기존 완료 자료 건너뛰기를 유지한다.

`!임무 2610B1`, `!임무 2610 B1` 모두 지원한다. 공략도 `!공략 2610B1`,
`!공략 2610 B1`, `!공략 2610 B1 13`으로 조회한다.
실제 이미지 다운로드와 전송은 PC의 수집 완료 후 확인해야 한다.

검증: 12개 번호·한국어 조건·기함 포함 여부·S승 횟수·선택보상·개수치,
선행/후속 역산·순환 없음·함선 별명 검색·전체 기존 임무 회귀 테스트를 수행한다.
실제 웹훅의 12개 임무 텍스트 응답과 저장 사진을 사용하는 공략 전송 경로는 모의 전송으로 검증한다.
이 환경의 실제 제카마시 접속은 robots.txt 요청 단계에서 프록시 403으로 중단되어
신규 공략 12개를 실제 다운로드했다고 간주하지 않는다.

PC에서도 접속이 막히면 브라우저에서 HTML(UTF-8) 또는 응답 본문을 포함한 HAR를
저장하고, 네트워크 요청 없이 가져올 수 있다.

```powershell
C:\KakaoBot\.venv\Scripts\python.exe C:\KakaoBot\KKanggallbot\scripts\collect_new_quests.py --input "C:\KakaoBot\new_quests.html"
```

HAR도 동일하게 `--input "C:\KakaoBot\new_quests.har"`로 지정한다.
HAR 전체에는 민감한 헤더가 있을 수 있으므로 공개하지 않는다. 수집기는 대상 페이지의
정상 응답 HTML만 가져오며 쿠키·요청 헤더를 결과에 복사하지 않는다.
