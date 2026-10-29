# Git 동시 fetch / 동기화 감시 복구

증상: Drive watch가 Git `rev-parse FETCH_HEAD` 오류 128에서 종료됨.

확인된 종료 원인은 CalledProcessError가 기존 재시도 예외 목록에 없던 것입니다.
원래 watch_bot과 Drive sync 모두 공용 FETCH_HEAD를 사용했으므로 다른 fetch가 파일을
다시 쓰는 순간의 읽기 충돌이 가능했습니다. PC stderr가 제공되지 않아 실제 발생 원인이
동시성이라고 단정하지는 않습니다.

수정:

- Drive fetch는 매 호출마다 `refs/kakaobot/drive-sync/<uuid>`로 명시적으로 main을 받음.
- 봇 감시는 별도의 `refs/kakaobot/bot-watch/<uuid>`를 사용.
- 양쪽 모두 `--no-write-fetch-head`. FETCH_HEAD를 읽거나 쓰지 않음.
- 임시 ref의 commit을 읽고 Git 이력·해시 검증은 그대로 유지. 이후 자신이 만든 ref만 정리.
- Python Git 호출은 60초 timeout. Git 실패/timeout/OS 오류는 watch를 종료하지 않고
  기존 120초 주기로 재시도. 로컬 편집·검증 오류를 강제로 덮어쓰지 않음.
- 명령줄·stdout/stderr·인증 URL을 오류 로그에 출력하지 않음.

검증은 실제 임시 Git 저장소/로컬 origin으로 수행합니다. FETCH_HEAD를 잘못된 내용으로
만들고 tracking refspec이 비표준이어도 새 commit을 읽는지, 임시 ref가 남지 않는지,
Git 128/timeout/OS 오류 뒤 다음 watch 순회가 정상 실행되는지 테스트합니다.
PowerShell 실행 환경은 클라우드에 없어 PowerShell 코드는 구조 검사만 수행합니다.

PC 적용 시 현재 실행 중인 Python/PowerShell은 파일이 갱신되어도 기존 코드를 메모리에
가지고 있으므로 두 감시 창을 한 번 재시작합니다. Iris 창은 종료하지 않습니다.
`git pull --ff-only` 후 watch_bot.ps1과 sync_drive_data.py watch를 각각 기존 창에서 다시
실행합니다. bootstrap이나 인증 재발급, reset/강제 덮어쓰기는 필요하지 않습니다.
