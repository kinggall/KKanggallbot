# 클라우드 작업 → PC 반영

코드는 GitHub의 기존 `watch_bot.ps1` 경로로 반영합니다. PC에만 있던 공략 HTML·사진과 별도 데이터는 비공개 Google Drive `bot` 폴더를 통해 반영합니다. 클라우드의 `/workspace`를 PC의 `C:\KakaoBot`에 대응시킵니다. 이 설정은 24시간 클라우드 서버를 만들지 않으며, 현재 봇은 PC에서 계속 실행합니다.

## 최초 이전 (PC에서 한 번)

수집기가 파일을 수정하고 있다면 먼저 종료합니다. 기존 봇은 계속 실행해도 됩니다.

```powershell
git -C C:\KakaoBot\KKanggallbot pull --ff-only
C:\KakaoBot\.venv\Scripts\python.exe C:\KakaoBot\KKanggallbot\scripts\sync_drive_data.py plan --root C:\KakaoBot
```

기본 이전 대상은 `KKanggallbot\guide_cache`, `pictures`, `KKanggallbot\data`입니다. Git 추적 파일은 GitHub로 관리하므로 업로드 대상에서 제외합니다. 인증 파일, HAR, `.env`, `.git`, 가상환경, 실행파일, 로그는 제외합니다. 안드로이드·카카오톡 설치 폴더와 실행 상태를 파일 동기화로 이전하지 않습니다. 다른 자료 폴더는 `--include 상대경로`를 반복하여 지정할 수 있으며, 지정 시 기본 대상도 함께 나열해야 합니다. 임의 폴더에는 별도 이름의 인증 파일이 없는지 확인합니다.

목록을 확인한 뒤 실제 `token.json` 경로를 넣어 실행합니다. 인증 파일을 GitHub 또는 Drive로 업로드하지 않습니다.

```powershell
C:\KakaoBot\.venv\Scripts\python.exe C:\KakaoBot\KKanggallbot\scripts\sync_drive_data.py bootstrap --root C:\KakaoBot --token-file "실제 token.json 전체경로"
```

`Published ... files`가 표시되면 최초 업로드가 완료됩니다. 대량 자료는 ZIP을 만드는 시간과 업로드 시간이 필요합니다. 기존 동기화본이 있으면 bootstrap은 덮어쓰지 않습니다.

## 클라우드 작업

클라우드에는 이미 등록한 OAuth 비밀 변수 세 개와 폴더 ID가 필요합니다.

```bash
cd /workspace/KKanggallbot
/workspace/.venvs/kkanggallbot/bin/python scripts/sync_drive_data.py pull --root /workspace
# 자료를 수정하고 검증한 후
/workspace/.venvs/kkanggallbot/bin/python scripts/sync_drive_data.py push --root /workspace
```

시작 전에 pull, 작업이 끝나면 push를 실행합니다. 코드 변경은 별도로 GitHub에 반영합니다. 클라우드 작업이 끝나기 전에 push하지 않은 자료는 Drive에 보관되지 않습니다. 여러 클라우드 작업에서 동시에 push하지 않습니다.

## PC에서 자동 내려받기

별도 PowerShell 창에서 실행합니다. 120초마다 최신 자료를 확인하며 변경이 없으면 ZIP을 내려받지 않습니다.

```powershell
C:\KakaoBot\.venv\Scripts\python.exe C:\KakaoBot\KKanggallbot\scripts\sync_drive_data.py watch --root C:\KakaoBot --token-file "실제 token.json 전체경로"
```

PC를 재부팅했다면 다시 실행해야 합니다. 현재 버전은 Windows 자동 시작을 등록하지 않습니다. 코드 자동 갱신 창과 자료 내려받기 창을 각각 유지합니다. PC에서 자료를 수정하거나 수집하려면 동기화 창을 먼저 중지하고 작업 내용을 조정합니다. 기존 PC 자료와 클라우드 자료가 다르면 자동 덮어쓰기 대신 충돌로 중단합니다.

## 백업과 제한

- 갱신 전 파일은 `C:\KakaoBot\.drive-sync\backups`에 보관합니다.
- Drive에는 이전 ZIP도 보관합니다. 파일 수와 용량이 누적되므로 자동 정리는 하지 않습니다.
- ZIP 전체를 검증한 뒤 파일별로 교체합니다. 파일별 교체는 원자적이지만 전체 폴더의 동시 교체는 아닙니다. 교체 중 실행한 명령은 이전/새 자료를 함께 읽을 수 있으므로 갱신 완료 후 검증합니다.
- 클라우드에서 파일을 삭제해도 PC 파일을 자동 삭제하지 않습니다. 삭제 반영은 별도로 확인합니다.
- 파일 수/용량이 커지면 수정 때마다 전체 ZIP을 업로드·다운로드하므로, 실측 후 증분 동기화로 개선할 수 있습니다.
- 프로그램은 Google 인증 응답이나 토큰을 로그에 출력하지 않습니다. Google OAuth 앱의 테스트 모드·토큰 만료 등으로 재인증이 필요할 수 있습니다.
