# 주식봇 작업 마무리

- 이 패키지를 수정하면 검증 후 GitHub에 커밋·푸시하고, 이어서 프로젝트의 기존 Drive 동기화도 실행합니다: `python scripts/sync_drive_data.py push --root /workspace --include KKanggallbot/stockbot`.
- Drive 상태가 오래되었다면 먼저 `pull --root /workspace`로 갱신합니다. 충돌은 강제 덮어쓰지 않습니다.
- stockbot Python 코드는 Git 커밋 ID와 함께 Drive 원래 경로에 파일별로 게시됩니다. PC 감시가 검증 후 Git fast-forward로 적용하므로 별도 백업 폴더나 파일 수동 복사는 하지 않습니다.
- 인증·토큰·개인 투자 데이터·DB는 GitHub나 Drive 코드 동기화에 추가하지 않습니다. 외부 Domino 저장소·앱은 별도 요청 없이 수정하지 않습니다.
- PC에서 명령어가 실제로 응답했는지는 클라우드 테스트와 구분해서 보고합니다.
