# 깡갤봇

카카오톡 메시지에 자동으로 답변하는 봇입니다.

`!개발 장비명`은 장비 별명과 `#번호`를 지원하며, 최적 레시피와 필요한 경우 범용 레시피를 보여줍니다. 자원 순서는 연료 / 탄약 / 강재 / 보크사이트입니다. 계산은 PC에 포함된 데이터로 수행합니다.

## 라이선스와 출처

봇 소프트웨어는 [GPL-3.0](LICENSE)으로 배포합니다. `!개발`의 계산 코드는 [SkywalkerJi/kc-development-tools](https://github.com/SkywalkerJi/kc-development-tools)의 GPL-3.0 코드를 Python으로 이식·수정했습니다. 원본 라이선스를 보존하며, 수정한 소스코드도 이 저장소에서 제공합니다. 게임 데이터와 기존 외부 자료의 권리는 각 권리자에게 있습니다. 구체적인 출처·변경 사항은 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), 데이터 기준과 검증 방법은 [DEVELOPMENT_DATA.md](DEVELOPMENT_DATA.md)에 기록했습니다.

## Windows에서 GitHub 자동 업데이트

Git for Windows가 설치되어 있고 봇 가상환경이 `C:\KakaoBot\.venv`에 있다고 가정합니다. 기존 `C:\KakaoBot` 파일은 그대로 둔 채 저장소를 별도 폴더에 한 번만 내려받습니다.

```powershell
git clone https://github.com/kinggall/KKanggallbot.git C:\KakaoBot\KKanggallbot
powershell -NoProfile -ExecutionPolicy Bypass -File C:\KakaoBot\KKanggallbot\watch_bot.ps1
```

감시 PowerShell 창은 켜 두어야 합니다. 봇의 Python 창은 숨겨지고, 30초마다 하는 GitHub 확인은 화면에 출력되지 않습니다. 새 커밋이 있으면 실행 중인 `bot.py`를 멈춘 뒤 업데이트하고 다시 실행합니다. 봇이 종료되면 같은 버전을 반복 실행하지 않고 로그를 확인하도록 알립니다. 감시를 종료하려면 PowerShell 창에서 `Ctrl+C`를 누르세요. Iris는 별도로 계속 실행 중이어야 합니다. 실행 로그는 `C:\KakaoBot\logs`에 저장됩니다.
