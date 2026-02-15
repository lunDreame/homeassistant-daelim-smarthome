# Daelim SmartHome - Home Assistant 커스텀 컴포넌트

대림 E&C 스마트홈 연동 Home Assistant 커스텀 컴포넌트입니다.

## 지원 장치

- **조명 (Light)**: 전등 On/Off, 밝기 조절 (지원 시)
- **콘센트 (Switch)**: 벽면 콘센트 On/Off
- **에어컨/히터 (Climate)**: 냉방/난방 설정
- **가스 밸브 (Lock)**: Lock=가스 차단 (API로 차단만 가능)
- **환기 팬 (Fan)**: 환기 On/Off, 풍량 조절 (지원 단지 한정)
- **엘리베이터 (Button)**: 엘리베이터 호출 버튼
- **현관 센서 (Binary Sensor)**: 세대현관/공동현관 모션 — **실시간 FCM 푸시**
- **주차 센서 (Binary Sensor)**: 주차차단기 입차 감지 — **실시간 FCM 푸시**
- **방문자 센서 (Binary Sensor)**: 세대현관/공동현관 방문자 감지 — **실시간 FCM 푸시**
- **인터폰 카메라 (Camera)**: 세대현관/공동현관 방문자 스냅샷

## 설치

1. `custom_components` 폴더를 Home Assistant의 config 디렉터리에 복사합니다.
2. `config/custom_components/daelim_smarthome/` 경로에 모든 파일이 있어야 합니다.
3. Home Assistant를 재시작합니다.
4. 설정 → 연동 → 통합 구성요소 추가 → "Daelim SmartHome" 검색 후 추가

## 설정

1. **지역 선택**: 거주 지역 선택
2. **단지 선택**: 아파트 단지 선택
3. **로그인 정보**: 스마트홈 앱 아이디, 비밀번호 입력
   - UUID는 아이디에서 자동 생성됩니다
4. **월패드 인증** (필요한 경우): 최초 인증이 필요한 단지는 월패드에 표시된 인증번호 입력 단계가 나타납니다

옵션에서 엘리베이터/현관/주차/방문자 센서의 감지 유지 시간(초)을 조정할 수 있습니다.

## 요구사항

- Home Assistant 2024.x 이상
- aiohttp, firebase-messaging

## 실시간 업데이트

| 장치 | 방식 |
|------|------|
| 현관, 주차, 방문자 | FCM 푸시 (즉시 반영) |
| 조명, 콘센트, 에어컨, 환기 팬 | 쿼리/호출 응답 (명령 시 또는 주기적 갱신) |

FCM 푸시를 통해 현관문이 열리거나 주차/방문자 이벤트가 발생하면 Home Assistant에서 즉시 반영됩니다.
