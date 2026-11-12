# 공식 점검 공지

`!멘테` / `!ㅁㅌ`는 `KanColle_STAFF`의 번호 공지를 검토한 한국어 요약을
반환한다. 기존 고정 커뮤니티 링크를 대체한다.
`!신규임무`의 EO·wikiwiki 기반 임무 데이터와 조건·보상은 변경하지 않는다.

기본 수집은 Playwright로 **계정 타임라인을 스크롤**하고 화면에 등장한
각 공식 게시물 URL의 원문을 읽는다. 인용 여부에 의존하지 않는다.
계정·게시일·번호를 확인하고 중복을 제거한다. 로그인 제한·로딩 정지로
누락이 남으면 기존 원문을 덮어쓰지 않고 실패한다. 번호가 빠진 내용을
만들어 채우거나 모든 공지를 확인했다고 표시하지 않는다.

비로그인 X 화면에서는 이전 글 로딩이 제한될 수 있다. 필요한 경우 PC에서
직접 로그인한다. 스크립트는 비밀번호를 입력받지 않으며, 로그인 세션은
저장소 밖 `%LOCALAPPDATA%\KKanggallbot\x-session`에 보관한다.
세션 폴더를 Git·Drive·채팅에 공유하지 않는다. 비공개 API나 인증 우회는 없다.

```powershell
C:\KakaoBot\.venv\Scripts\python.exe -m pip install playwright
C:\KakaoBot\.venv\Scripts\python.exe -m playwright install chromium
C:\KakaoBot\.venv\Scripts\python.exe scripts\collect_maintenance.py --login --date 2026-11-11
C:\KakaoBot\.venv\Scripts\python.exe scripts\collect_maintenance.py --date 2026-11-11
```

원문: `data/maintenance_posts.json` (게시물별 원문 URL 및 원문 해시 포함).
네트워크 실패·로그인 페이지·파싱 실패 시 기존 파일을 덮어쓰지 않는다.
2026-11-11의 **01~24번 원문을 모두 확보**했다. 13번은 14번의 인용 연결에서
빠져 있었으며, 제공된 공식 URL의 원문을 직접 확인해 보완했다.
기존 인용 연결 방식은 `--quote-only` 진단 옵션으로만 남긴다.
이 옵션의 `--post-url`로 추가한 공식 URL은 같은 날 재수집 시 보존된다.
이는 타임라인 스크롤 완료 검증과 구분하며, 향후 수집의 기본값이 아니다.

요약은 현재 에이전트가 원문을 읽고 한국어로 검토한 결과다.
상시 LLM 자동 번역이나 주기 갱신은 아직 연결하지 않았다.
새 원문 수집 후 검토한 섹션 JSON을 다음 명령으로 묶는다.

```powershell
C:\KakaoBot\.venv\Scripts\python.exe scripts\write_maintenance_summary.py data\maintenance_summary_sections.json
```

요약의 날짜·해시가 원문과 다르면 예전 요약을 새 점검 내용으로 표시하지 않고
검토 중이라고 안내한다. 함선·장비의 구체적 조건, 개발 배합·확률, 임무 보상은
공식 공지에 없는 값을 추정해서 데이터베이스에 반영하지 않는다.
