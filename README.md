# 스마트팜 식물 에이전트: 센서 수집·전송 코드

스마트팜 창의설계(2026) 하드웨어 파트 코드입니다.
아두이노 Uno로 센서를 읽고, 라즈베리파이 5가 이를 CSV로 저장한 뒤 웹 서버로 전송합니다.

```
아두이노 Uno ──USB 시리얼(CSV 한 줄)──▶ 라즈베리파이 5 ──HTTP POST──▶ API 서버(SQLite)
 토양수분×4, 조도, 온습도              1분 평균 CSV 저장                  웹/챗봇이 조회
```

시리얼 형식: `soil1,soil2,soil3,soil4,light,temp,hum` (1분마다 1줄)

## 파일 구성

| 파일 | 역할 |
|---|---|
| `261009_arduino_sensors/` | 아두이노 센서 스케치 v0.1 (조도: CdS 아날로그) |
| `261021_arduino_sensors_bh1750/` | 아두이노 센서 스케치 v0.2 (조도: BH1750, lux 단위) |
| `261022_i2c_scan/` | 진단용 스케치 (시리얼 연결과 I2C 배선 확인) |
| `261009_pi_collector.py` | 라즈베리파이: 시리얼 값을 받아 1분 평균을 날짜별 CSV로 저장 |
| `261012_plant-collector.service` | 라즈베리파이 부팅 시 수집 프로그램 자동 실행 (systemd) |
| `261021_pi_uploader.py` | 라즈베리파이: 아직 안 보낸 CSV 줄만 서버로 전송 |
| `261021_api_server.py` | 데이터 수신·조회 API 서버 (FastAPI + SQLite) |
| `261026_load_csv_to_db.py` | CSV 파일을 서버 DB에 한 번에 넣는 도구 |
| `*.txt` | 설정 방법과 조원 공유용 안내 문서 |

## 참고

- API 키는 공개 저장소용으로 `CHANGE_ME`로 바꿔 두었습니다.
  실제로 쓸 때는 환경변수 `PLANT_API_KEY`로 지정하세요.
- 파일명 앞 6자리는 작성 날짜(YYMMDD)입니다.
