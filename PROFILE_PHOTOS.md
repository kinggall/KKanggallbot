# 방 프로필 사진

`!프사 [정확한 닉네임]` — 방 ID 18182686594126049에서만 허용한다.
메인 도움말·초성 명령어에는 추가하지 않는다.

- Iris `/room/{id}/members`의 nickname/profile_image_url로 조회한다.
- 사진은 original_profile_image_url → full_profile_image_url → profile_image_url 순으로 시도한다.
- members 응답에 큰 주소가 없으면 같은 방·같은 사용자 ID의 open_chat_member만 추가 조회한다.
- 구버전 DB에 큰 사진 컬럼이 없거나 다운로드 실패하면 기존 사진 전송을 유지한다. 단순 확대는 하지 않는다.
- 구버전에서 404면 `/query`로 이 방의 link_id에 연결된 open_chat_member만 조회한다.
- 일반 친구·개인 프로필(`/user`, friends)로 대체하지 않는다.
- 동명이인은 선택하지 않고 안내한다. 조회 목록에 없으면 정확한 닉네임 확인을 안내한다.
- 참가자 목록이 Iris에서 제한될 수 있으므로 조회 실패를 탈퇴 여부로 해석하지 않는다.
- HTTPS Kakao CDN/카카오 도메인만 허용하고 리다이렉트도 재검사한다.
- JPEG/PNG/GIF/WebP만 허용, MIME·파일 시그니처·8MiB 상한을 검사한다.
- 메모리에서 Base64 이미지로 전송한다. 사진 파일·URL·참가자 목록을 캐시/로그/Git/Drive에 저장하지 않는다.
- 5초 간격, 최대 2건 처리 제한. 지정 방 외에는 조회·응답하지 않는다.

모의 조회·다운로드·전송 테스트 완료. PC 설치 Iris 버전의 실제 복호화 응답,
카카오 이미지 서버 다운로드, 실제 채팅 전송은 PC에서 확인해야 한다.

PC 확인: `!프사 [자기 닉네임]`. 실패하면 Iris의 `/room/18182686594126049/members`
지원 여부와 profile_image_url 반환 여부를 확인한다. 인증정보·전체 참가자 목록은 공개하지 않는다.
