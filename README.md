# 깡갤봇

카카오톡 메시지에 자동으로 답변하는 봇입니다.

## Windows에서 GitHub 자동 업데이트

Git for Windows가 설치되어 있고 봇 가상환경이 `C:\KakaoBot\.venv`에 있다고 가정합니다. 기존 `C:\KakaoBot` 파일은 그대로 둔 채 저장소를 별도 폴더에 한 번만 내려받습니다.

```powershell
git clone https://github.com/kinggall/KKanggallbot.git C:\KakaoBot\KKanggallbot
powershell -NoProfile -ExecutionPolicy Bypass -File C:\KakaoBot\KKanggallbot\watch_bot.ps1
```

감시 PowerShell 창은 켜 두어야 합니다. 봇의 Python 창은 숨겨지고, 30초마다 하는 GitHub 확인은 화면에 출력되지 않습니다. 새 커밋이 있으면 실행 중인 `bot.py`를 멈춘 뒤 업데이트하고 다시 실행합니다. 봇이 종료되면 같은 버전을 반복 실행하지 않고 로그를 확인하도록 알립니다. 감시를 종료하려면 PowerShell 창에서 `Ctrl+C`를 누르세요. Iris는 별도로 계속 실행 중이어야 합니다. 실행 로그는 `C:\KakaoBot\logs`에 저장됩니다.
