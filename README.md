# 스마트팜 식물 에이전트: 센서 데이터 수집·전송 (Python)

스마트팜 창의설계(2026)에서 쓰는 파이썬 코드입니다.
라즈베리파이 5가 아두이노 센서값을 CSV로 저장하고, 웹 서버로 보내 DB에 쌓습니다.

```
아두이노 Uno ──USB 시리얼(CSV 한 줄)──▶ 라즈베리파이 5 ──HTTP POST──▶ API 서버(SQLite)
 토양수분×4, 조도, 온습도              1분 평균 CSV 저장                  웹/챗봇이 조회
```

시리얼 형식: `soil1,soil2,soil3,soil4,light,temp,hum` (1분마다 1줄)

## 파일 구성

| 파일 | 역할 |
|---|---|
| `261009_pi_collector.py` | 라즈베리파이: 시리얼 값을 받아 1분 평균을 날짜별 CSV로 저장 |
| `261021_pi_uploader.py` | 라즈베리파이: 아직 안 보낸 CSV 줄만 서버로 전송 |
| `261021_api_server.py` | 데이터 수신·조회 API 서버 (FastAPI + SQLite) |
| `261026_load_csv_to_db.py` | CSV 파일을 서버 DB에 한 번에 넣는 도구 |

## 참고

- API 키는 공개 저장소용으로 `CHANGE_ME`로 바꿔 두었습니다.
  실제로 쓸 때는 환경변수 `PLANT_API_KEY`로 지정하세요.
- 파일명 앞 6자리는 작성 날짜(YYMMDD)입니다.
