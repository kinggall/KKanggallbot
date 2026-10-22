# 클라우드 작업 → PC 개별 파일 동기화

Drive의 `KaKaobot` 폴더 아래에서 폴더 구조와 개별 파일을 그대로 유지합니다. ZIP 생성·다운로드는 사용하지 않습니다. `kakaobot-data-head.json`은 동기화 대상 파일의 ID·해시를 기록한 작은 목록이므로 삭제하지 않습니다.

## 관리 대상

PC 루트의 `KakaoBot_사용방법.txt`도 개별 파일로 동기화합니다. 재부팅 후 실행 순서는 이 파일에 있습니다.

자료는 `KKanggallbot/guide_cache`, `pictures`, `KKanggallbot/data` 안의 Git 미추적 파일입니다. 코드는 기존 GitHub 감시 프로그램이 30초마다 갱신하며, 이중 덮어쓰기를 막기 위해 Git 추적 파일은 Drive 동기화에서 제외합니다. Drive에 사용자가 업로드한 코드 사본은 현재 실행 코드의 배포 경로가 아닙니다.

`/workspace`는 PC의 `C:\KakaoBot`에 대응합니다. 인증·가상환경·로그·Iris 빌드 폴더와 실행 상태는 동기화하지 않습니다. 현재 봇 운영은 계속 집 PC에서 합니다.

## 기존 업로드 폴더 전환

클라우드에서 실행합니다. 기존 개별 파일의 Drive MD5와 로컬 MD5를 모두 확인한 뒤 목록을 개별 파일 모드(schema 2)로 전환합니다. 자료를 다시 업로드하지 않습니다.

```bash
cd /workspace/KKanggallbot
/workspace/.venvs/kkanggallbot/bin/python scripts/sync_drive_data.py adopt-files --root /workspace
```

전환 성공 후 생성된 목록에는 ZIP 참조가 없습니다. 이전 `kakaobot-data-*.zip`은 동기화에 필요하지 않으며 사용자가 삭제할 수 있습니다. `kakaobot-data-head.json`은 남겨둡니다. 이전 목록은 클라우드 `/workspace/.drive-sync/before-individual-files.json`에도 보관합니다.

## PC 감시 프로그램 재시작

기존 자료 동기화 창에서 Ctrl+C를 누른 뒤 아래를 실행합니다. 봇 코드 감시 창은 유지합니다.

```powershell
git -C C:\KakaoBot\KKanggallbot pull --ff-only
C:\KakaoBot\.venv\Scripts\python.exe C:\KakaoBot\KKanggallbot\scripts\sync_drive_data.py watch --root C:\KakaoBot --token-file C:\KakaoBot\KKanggallbot\cloud\token.json
```

2분마다 목록을 확인하고, 실제 로컬 내용과 다른 파일만 내려받습니다. 기존 파일이 같으면 최초 전환에서도 자료를 다시 받지 않습니다. 다운로드 전부의 SHA-256을 검증한 뒤 파일별로 원자 교체합니다. 갱신 전 파일은 `C:\KakaoBot\.drive-sync\backups`에 남깁니다. PC가 재시작되면 감시 프로그램도 다시 실행해야 합니다.

## 클라우드 작업 순서

```bash
cd /workspace/KKanggallbot
/workspace/.venvs/kkanggallbot/bin/python scripts/sync_drive_data.py pull --root /workspace
# 자료 수정·검증
/workspace/.venvs/kkanggallbot/bin/python scripts/sync_drive_data.py push --root /workspace
```

수정된 자료만 Drive의 기존 파일 ID로 갱신하며, 새 파일은 대응 폴더에 생성합니다. 목록만 함께 갱신합니다. 진행 로그에 파일별 업로드·다운로드 수가 표시됩니다. 코드는 별도로 GitHub에 반영합니다. 여러 작업에서 동시에 push하지 않습니다.

5MiB 이하의 일반 파일은 하나의 multipart 요청으로 전송하고 Drive가 반환한 MD5가 있으면 대조합니다. 목록 갱신 전에 전송이 중단돼도 이미 올라간 파일의 이름·크기·해시가 모두 같으면 재전송하지 않고 이어갑니다. 다른 내용의 동명 파일은 자동 덮어쓰지 않습니다. 오류에는 HTTP 상태와 Google의 오류 분류만 표시하며 인증 응답 원문은 출력하지 않습니다.

## 충돌·직접 수정·삭제

- PC에서 별도로 바뀐 파일은 덮어쓰지 않고 충돌로 중단합니다.
- Drive 웹 화면에서 파일을 직접 수정·추가하면 동기화 목록을 자동 갱신하지 않습니다. 작업은 클라우드 작업 폴더에서 수행하고 push합니다. 직접 올린 자료를 반영하려면 먼저 대조·검토합니다.
- 삭제는 자동 전파하지 않습니다. 폴더·파일 삭제가 필요하면 따로 확인합니다.
- 파일별 교체이며 폴더 전체를 한꺼번에 교체하는 방식은 아닙니다. 갱신 중 봇 명령은 이전/새 자료를 함께 읽을 수 있으므로 완료 후 확인합니다.
- ZIP을 삭제하기 전 기존 ZIP 감시 프로세스를 종료하고 새 버전으로 재시작합니다.
- 인증값은 로컬 token.json 또는 환경의 Google OAuth 비밀 변수로만 제공합니다. 채팅·GitHub·Drive에 인증 파일을 올리지 않습니다.
