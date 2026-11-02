#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
센서 데이터 받는 서버 (초안 v0.1, 2026-10-21) — 소프트웨어 담당용

하는 일
  라즈베리파이가 보낸 센서 데이터를 받아서 SQLite 파일 하나에 저장하고,
  웹 화면과 챗봇이 읽어갈 수 있게 조회 주소를 열어 준다.

  POST /api/readings      데이터 받기 (라즈베리파이가 호출)
  GET  /api/readings      저장된 데이터 조회 (최근 것부터)
  GET  /api/latest        가장 최근 한 줄
  GET  /api/stats         며칠치가 쌓였는지 요약
  GET  /health            서버가 살아있는지 확인

설치
  pip install fastapi uvicorn

실행
  uvicorn 261021_api_server:app --host 0.0.0.0 --port 8000
  (파일 이름이 숫자로 시작해서 import 가 안 되면 파일명을 api_server.py 로 바꾸고
   uvicorn api_server:app --host 0.0.0.0 --port 8000)

확인
  브라우저에서 http://localhost:8000/docs 를 열면 테스트 화면이 나온다.

주의
  - 같은 device_id + time 은 한 줄로 취급한다. 라즈베리파이가 같은 데이터를
    다시 보내도 중복으로 쌓이지 않는다.
  - 값이 비어 있을 수 있다 (DHT11 읽기 실패 시 null).
  - 토양수분/조도는 0~1023 원래 값이다. %로 바꾸는 식은 실험설계 문서 6-3 참고.
"""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ----------------------------------------------------------------------
# 설정
# ----------------------------------------------------------------------
API_KEY = "CHANGE_ME"          # 라즈베리파이 쪽과 똑같이 맞출 것
DB_PATH = Path("plant_data.db")     # 이 파일 하나에 다 저장된다

app = FastAPI(title="식물 센서 수집 API")

# 웹 화면이 다른 주소에서 돌아가도 호출할 수 있게 열어 둔다 (개발용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------
# 받을 데이터의 모양
#   비어 있을 수 있는 칸은 Optional (= null 허용)
# ----------------------------------------------------------------------
class Reading(BaseModel):
    time: str                       # "2026-10-21T14:30:00"
    soil1: Optional[int] = None     # 화분1 토양수분 0~1023 (클수록 건조)
    soil2: Optional[int] = None
    soil3: Optional[int] = None
    soil4: Optional[int] = None
    light: Optional[float] = None   # 조도. CdS면 0~1023 상대값, BH1750이면 lux (소수 가능)
    temp: Optional[float] = None    # 온도 °C
    hum: Optional[float] = None     # 습도 %
    n_samples: Optional[int] = None # 그 1분에 받은 줄 수 (0이면 데이터 못 받음)
    note: Optional[str] = ""        # no_data / dht_fail 등 문제 표시


class ReadingBatch(BaseModel):
    device_id: str                  # "pi-01"
    readings: List[Reading]


# ----------------------------------------------------------------------
# DB 준비
# ----------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(get_db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                device_id  TEXT NOT NULL,
                time       TEXT NOT NULL,
                soil1      INTEGER,
                soil2      INTEGER,
                soil3      INTEGER,
                soil4      INTEGER,
                light      REAL,
                temp       REAL,
                hum        REAL,
                n_samples  INTEGER,
                note       TEXT,
                PRIMARY KEY (device_id, time)
            )
        """)
        conn.commit()


init_db()


def check_key(key: Optional[str]):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="API 키가 맞지 않습니다")


# ----------------------------------------------------------------------
# 데이터 받기 — 라즈베리파이가 호출하는 주소
# ----------------------------------------------------------------------
@app.post("/api/readings")
def receive(batch: ReadingBatch, x_api_key: Optional[str] = Header(default=None)):
    check_key(x_api_key)

    rows = [
        (batch.device_id, r.time, r.soil1, r.soil2, r.soil3, r.soil4,
         r.light, r.temp, r.hum, r.n_samples, r.note or "")
        for r in batch.readings
    ]

    with closing(get_db()) as conn:
        # 같은 (device_id, time) 이 이미 있으면 덮어쓴다 → 중복이 쌓이지 않는다
        conn.executemany(
            "INSERT OR REPLACE INTO readings VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]

    return {"saved": len(rows), "total": total}


# ----------------------------------------------------------------------
# 조회 — 웹 화면과 챗봇이 쓰는 주소
# ----------------------------------------------------------------------
@app.get("/api/readings")
def list_readings(limit: int = 100, since: Optional[str] = None, device_id: Optional[str] = None):
    """
    최근 데이터부터 돌려준다.
      limit     : 몇 줄 가져올지 (기본 100, 최대 5000)
      since     : 이 시각 이후만 (예: 2026-10-20T00:00:00)
      device_id : 라즈베리파이가 여러 대일 때 구분
    """
    limit = max(1, min(limit, 5000))

    sql = "SELECT * FROM readings WHERE 1=1"
    params = []
    if since:
        sql += " AND time >= ?"
        params.append(since)
    if device_id:
        sql += " AND device_id = ?"
        params.append(device_id)
    sql += " ORDER BY time DESC LIMIT ?"
    params.append(limit)

    with closing(get_db()) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


@app.get("/api/latest")
def latest():
    """가장 최근 한 줄. 화면 맨 위 '현재 상태'에 쓰면 된다."""
    with closing(get_db()) as conn:
        row = conn.execute("SELECT * FROM readings ORDER BY time DESC LIMIT 1").fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="아직 데이터가 없습니다")
    return dict(row)


@app.get("/api/stats")
def stats():
    """며칠치가 쌓였는지 요약. 발표 자료 만들 때 쓰기 좋다."""
    with closing(get_db()) as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS total,
                   MIN(time) AS first_time,
                   MAX(time) AS last_time,
                   COUNT(DISTINCT substr(time, 1, 10)) AS days
            FROM readings
        """).fetchone()
    return dict(row)


@app.get("/health")
def health():
    return {"status": "ok"}
