# 공식 점검 공지

## 2026-11-24 수집

공식 X oEmbed(`publish.x.com/oembed`)와 공식 인용의 `t.co` 이동 주소로 01~48번을 모두 확보했습니다. 번호·작성 계정·게시 날짜를 검사하고, 번호가 없는 멘테 완료 안내 글에서 인용을 따라 실제 48번으로 진입했습니다. 원문과 요약의 해시를 연결합니다. 번호 48개 확보와 각 글의 생략 없는 전문 확보는 구분합니다.

말줄임 후보 01·06·07·08·09·10·11·19·20·21·23번은 `cdn.syndication.twimg.com/tweet-result`의 공식 임베드 데이터와 각각 대조했습니다. 11개 모두 마지막 `… + 인용 단축 링크` 및 공백을 제외하면 본문이 일치하여 빠진 공지 내용은 없었습니다. 08·19·21번 대사 안의 `……`는 원문 문장부호이며 그대로 보존했습니다. `data/maintenance_text_audit_20261124.json`에 개별 비교 전후 본문·응답 해시를 남기고, 공식 데이터 본문으로 저장 자료와 요약 바인딩 해시를 갱신했습니다. 현재 `possibly_truncated_numbers`는 빈 목록이고 잘림 주의 안내는 표시하지 않습니다. 향후 새 자료의 말줄임 후보는 확인 전까지 별도로 유지합니다.

다음 수집에도 같은 경로를 사용할 수 있습니다. 공개 임베드 응답만 캐시하며 쿠키·로그인 정보는 저장하지 않습니다. 다른 계정·이미지·외부 사이트로는 인용 수집을 이어가지 않습니다. 누락 번호가 있으면 기존 출력 파일을 유지합니다. 인용이 끊긴 글은 `--seed-url`로 공식 링크를 추가할 수 있습니다.

```powershell
C:\KakaoBot\.venv\Scripts\python.exe -m scripts.collect_maintenance_oembed --date 2026-11-24 --last-number 48 --seed-url https://x.com/KanColle_STAFF/status/2125228449531101644 --cache-dir C:\KakaoBot\.maintenance-oembed --output data\maintenance_posts.json
```

환경 허용 주소: `publish.x.com`, `t.co`. `publish.twitter.com`은 `publish.x.com`으로 이동합니다. 직접 X 페이지가 403이어도 공개 임베드는 별도로 HTTP 200일 수 있습니다. 상시 자동 수집·자동 한국어 요약 기능은 아니며, 새로운 멘테의 번호 범위와 내용은 검토해야 합니다.

## 기존 타임라인 수집

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
