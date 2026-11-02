#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV 파일을 서버 DB(plant_data.db)에 한 번에 넣는 도구 (초안 v0.1, 2026-10-26)
소프트웨어 담당용

왜 쓰나
  라즈베리파이가 학교에 있어서 밖에서는 접속할 수 없다.
  그래서 CSV 파일을 받아 자기 PC의 서버 DB 에 직접 넣고,
  파이에 연결된 것과 똑같은 환경에서 개발하기 위한 도구다.

필요한 것
  파이썬만 있으면 된다 (추가 설치 없음)

쓰는 법
  1) CSV 파일들이 들어 있는 폴더를 준비한다 (예: sensors data)
  2) 아래 명령을 실행한다

     python 261026_load_csv_to_db.py "sensors data"

  3) 같은 폴더에 plant_data.db 가 만들어진다
  4) 서버를 띄우면 그 데이터가 그대로 조회된다

     python -m uvicorn api_server:app --port 8000
     http://localhost:8000/docs

옵션
  --db 경로        DB 파일 위치 지정 (기본 plant_data.db)
  --device 이름    device_id 지정 (기본 pi-01)
  --dry-run        실제로 넣지 않고 몇 줄인지만 확인

주의
  - 같은 (device_id, time) 은 덮어쓴다. 같은 파일을 여러 번 넣어도 중복되지 않는다.
  - soil1~4, light 는 0~1023 또는 lux 원래 값 그대로 들어간다.
    % 로 바꾸는 식은 261021_API_규격_조원공유용.txt 6번 참고.
  - 2026-10-22 이전 데이터의 light 는 CdS 상대값(0~1023),
    그 이후는 BH1750 의 lux 다. 단위가 다르니 그래프를 그릴 때 주의.
"""

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

INT_FIELDS = ["soil1", "soil2", "soil3", "soil4", "n_samples"]
FLOAT_FIELDS = ["light", "temp", "hum"]
COLUMNS = ["device_id", "time", "soil1", "soil2", "soil3", "soil4",
           "light", "temp", "hum", "n_samples", "note"]

CREATE_SQL = """
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
"""


def to_number(text, as_int):
    """빈 칸은 None 으로. 숫자가 아니면 None."""
    text = (text or "").strip()
    if not text or text.lower() == "nan":
        return None
    try:
        return int(float(text)) if as_int else float(text)
    except ValueError:
        return None


def read_csv(path, device_id):
    """CSV 한 파일을 읽어 DB 에 넣을 줄들로 바꾼다."""
    rows, skipped = [], 0
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            when = (r.get("time") or "").strip()
            if not when:
                skipped += 1
                continue
            rows.append((
                device_id, when,
                *[to_number(r.get(k), True) for k in INT_FIELDS[:4]],
                *[to_number(r.get(k), False) for k in FLOAT_FIELDS],
                to_number(r.get("n_samples"), True),
                (r.get("note") or "").strip(),
            ))
    return rows, skipped


def main():
    parser = argparse.ArgumentParser(description="CSV 를 서버 DB 에 넣기")
    parser.add_argument("csv_dir", help="CSV 파일이 있는 폴더 (또는 CSV 파일 하나)")
    parser.add_argument("--db", default="plant_data.db", help="DB 파일 경로")
    parser.add_argument("--device", default="pi-01", help="device_id (기본 pi-01)")
    parser.add_argument("--dry-run", action="store_true", help="넣지 않고 확인만")
    args = parser.parse_args()

    src = Path(args.csv_dir)
    if src.is_dir():
        files = sorted(src.glob("sensors_*.csv")) or sorted(src.glob("*.csv"))
    elif src.is_file():
        files = [src]
    else:
        sys.exit(f"폴더나 파일을 찾을 수 없습니다: {src}")

    if not files:
        sys.exit(f"{src} 안에 CSV 파일이 없습니다")

    all_rows, total_skipped = [], 0
    for path in files:
        rows, skipped = read_csv(path, args.device)
        total_skipped += skipped
        all_rows += rows
        print(f"  {path.name}: {len(rows)}줄" + (f" (건너뜀 {skipped})" if skipped else ""))

    print(f"\n읽은 줄 합계: {len(all_rows)}")
    if total_skipped:
        print(f"시각이 비어 건너뛴 줄: {total_skipped}")

    if args.dry_run:
        print("(연습 모드라 실제로 넣지 않았습니다)")
        return

    conn = sqlite3.connect(args.db)
    try:
        conn.execute(CREATE_SQL)
        conn.executemany(
            f"INSERT OR REPLACE INTO readings VALUES ({','.join('?' * len(COLUMNS))})",
            all_rows,
        )
        conn.commit()

        total = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        first, last, days = conn.execute(
            "SELECT MIN(time), MAX(time), COUNT(DISTINCT substr(time,1,10)) FROM readings"
        ).fetchone()
    finally:
        conn.close()

    print(f"\nDB 저장 완료: {Path(args.db).resolve()}")
    print(f"  전체 {total}줄 / {days}일치")
    print(f"  기간 {first} ~ {last}")
    print("\n이제 서버를 띄우면 이 데이터가 조회됩니다:")
    print("  python -m uvicorn api_server:app --port 8000")
    print("  http://localhost:8000/docs")


if __name__ == "__main__":
    main()
