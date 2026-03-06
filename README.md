# Daelim SmartHome Home Assistant Custom Integration

[e편한세상 스마트홈 2.0](https://apps.apple.com/cm/app/e%ED%8E%B8%ED%95%9C%EC%84%B8%EC%83%81-%EC%8A%A4%EB%A7%88%ED%8A%B8%ED%99%88-2-0/id1109202165)

## 지원 장치

- **조명 (Light)**: 전등 On/Off, 밝기 조절 (지원 시)
- **콘센트 (Switch)**: 벽면 콘센트 On/Off
- **에어컨/히터 (Climate)**: 냉방/난방 설정
- **가스 밸브 (Switch)**: 상태는 열림/닫힘, 제어는 닫기만 지원
- **환기 팬 (Fan)**: 환기 On/Off, 풍량 조절
- **엘리베이터 (Button)**: 엘리베이터 호출 버튼
- **현관 센서 (Binary Sensor)**: 세대현관/공동현관 모션
- **주차 센서 (Binary Sensor)**: 주차차단기 입차 감지
- **방문자 센서 (Binary Sensor)**: 세대현관/공동현관 방문자 감지
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
4. **월패드 인증** (필요한 경우): 최초 인증이 필요한 단지는 월패드에 표시된 인증번호 입력 단계가 나타납니다

옵션에서 현관/주차/방문자 센서의 감지 유지 시간(초)을 조정할 수 있습니다.
또한 기기 타입별 묶음 생성 옵션을 켜면 동일 타입의 장치가 하나의 기기로 묶여서 표시됩니다.

## 요구사항

- Home Assistant 2024.x 이상
- aiohttp, firebase-messaging
