#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
라즈베리파이 -> 웹서비스 전송 프로그램 (초안 v0.1, 2026-10-21)

하는 일
  ~/plant-data/sensors_*.csv 를 읽어서, 아직 안 보낸 줄만 웹서비스로 보낸다.
  - 처음 실행하면 지금까지 쌓인 일주일치를 전부 올린다 (밀린 것 따라잡기)
  - 그 뒤로는 새로 생긴 줄만 보낸다
  - 인터넷이 끊기면 보내지 않고 기다렸다가 다음 번에 몰아서 보낸다
  - 어디까지 보냈는지 ~/plant-data/.upload_state.json 에 기록한다

CSV 원본은 손대지 않는다. 전송에 실패해도 데이터는 파이에 그대로 남는다.

필요한 것: 파이썬만 있으면 된다 (추가 설치 없음)

실행
  python3 261021_pi_uploader.py            # 5분마다 계속 전송
  python3 261021_pi_uploader.py --once     # 한 번만 보내고 종료 (cron 용)
  python3 261021_pi_uploader.py --dry-run  # 실제로 보내지 않고 몇 줄 보낼지만 확인
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


# ----------------------------------------------------------------------
# 설정
#   아래 값은 환경변수로 덮어쓸 수 있다. 코드를 고치지 않고 주소를 바꾸려면
#   설정 파일(예: ~/plant-uploader-remote.env)에 PLANT_API_URL 을 적고
#   서비스를 다시 시작하면 된다. (임시 주소가 자주 바뀔 때 편하다)
#
#     PLANT_API_URL     보낼 주소
#     PLANT_API_KEY     서버와 맞춘 키
#     PLANT_DEVICE_ID   라즈베리파이 이름
#     PLANT_STATE_FILE  어디까지 보냈는지 기록할 파일
#                       (서버를 두 곳으로 보낼 때는 반드시 서로 다른 파일로!)
#     PLANT_INTERVAL_SEC  몇 초마다 보낼지 (기본 60초)
#                       짧게 할수록 화면에 빨리 뜨지만 전송 횟수가 늘어난다
# ----------------------------------------------------------------------
API_URL = os.environ.get("PLANT_API_URL", "http://localhost:8000/api/readings")
API_KEY = os.environ.get("PLANT_API_KEY", "CHANGE_ME")
DEVICE_ID = os.environ.get("PLANT_DEVICE_ID", "pi-01")

CSV_DIR = Path.home() / "plant-data"
STATE_FILE = Path(os.environ.get("PLANT_STATE_FILE", CSV_DIR / ".upload_state.json"))

BATCH_SIZE = 200      # 한 번에 보낼 줄 수. 너무 크면 실패했을 때 손해가 크다
TIMEOUT_SEC = 15      # 서버 응답을 기다리는 시간

# 반복 모드에서 몇 초마다 보낼지. 센서가 1분마다 측정하므로 기본 60초로 맞춘다.
INTERVAL_SEC = max(10, int(os.environ.get("PLANT_INTERVAL_SEC", "60")))

# CSV 에서 숫자로 바꿀 칸 (나머지는 글자 그대로)
INT_FIELDS = ["soil1", "soil2", "soil3", "soil4", "n_samples"]
# light 는 조도센서 종류에 따라 정수(CdS 0~1023)일 수도, 소수(BH1750 lux)일 수도 있어
# 소수로 처리한다. 정수로 읽으면 "3421.7" 에서 오류가 난다.
FLOAT_FIELDS = ["light", "temp", "hum"]


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ----------------------------------------------------------------------
# 어디까지 보냈는지 기록 / 읽기
#   {"sensors_2026-10-12.csv": "2026-10-12T23:59:00", ...}
# ----------------------------------------------------------------------
def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log(f"기록 파일을 읽지 못해 처음부터 보냅니다: {e}")
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------
# CSV 한 줄 -> 보낼 딕셔너리
#   빈 칸은 None 으로 보낸다 (DHT 읽기 실패 등)
# ----------------------------------------------------------------------
def convert(row):
    out = {"time": row.get("time", "").strip()}
    if not out["time"]:
        return None

    for name in INT_FIELDS:
        text = (row.get(name) or "").strip()
        out[name] = int(text) if text else None
    for name in FLOAT_FIELDS:
        text = (row.get(name) or "").strip()
        out[name] = float(text) if text else None
    out["note"] = (row.get("note") or "").strip()
    return out


def read_new_rows(path, sent_until):
    """이 파일에서 아직 안 보낸 줄만 시간순으로 돌려준다."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            item = convert(raw)
            if item is None:
                continue
            if sent_until and item["time"] <= sent_until:
                continue          # 이미 보낸 줄 (시각 문자열은 사전순 = 시간순)
            rows.append(item)
    return rows


# ----------------------------------------------------------------------
# 서버로 보내기
# ----------------------------------------------------------------------
def send(readings):
    """성공하면 True. 실패하면 이유를 찍고 False."""
    payload = json.dumps({"device_id": DEVICE_ID, "readings": readings}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as res:
            body = res.read().decode("utf-8", errors="replace")[:200]
            log(f"전송 성공 {len(readings)}줄 → 서버 응답: {body}")
            return True
    except urllib.error.HTTPError as e:
        # 서버는 살아있는데 거절한 경우 (주소 오타, 키 불일치, 형식 오류 등)
        detail = e.read().decode("utf-8", errors="replace")[:200]
        log(f"서버가 거절했습니다 (HTTP {e.code}): {detail}")
    except urllib.error.URLError as e:
        # 서버에 닿지 못한 경우 (인터넷 끊김, 주소 틀림, 서버 꺼짐)
        log(f"서버에 연결하지 못했습니다: {e.reason}")
    except Exception as e:
        log(f"전송 중 오류: {e}")
    return False


def upload_once(dry_run=False):
    """보낼 수 있는 만큼 보낸다. 보낸 줄 수를 돌려준다."""
    if not CSV_DIR.exists():
        log(f"{CSV_DIR} 폴더가 없습니다. 수집 프로그램이 돌고 있는지 확인하세요.")
        return 0

    state = load_state()
    total = 0

    for path in sorted(CSV_DIR.glob("sensors_*.csv")):
        rows = read_new_rows(path, state.get(path.name))
        if not rows:
            continue
        log(f"{path.name}: 보낼 줄 {len(rows)}개")

        # 한 번에 다 보내지 않고 BATCH_SIZE 씩 나눠 보낸다
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            if dry_run:
                log(f"  (연습) {batch[0]['time']} ~ {batch[-1]['time']} {len(batch)}줄")
                total += len(batch)
                continue

            if not send(batch):
                log("여기서 멈춥니다. 다음 번에 이어서 보냅니다.")
                save_state(state)
                return total

            # 성공한 만큼만 기록해 둔다 (중간에 끊겨도 이어서 보낼 수 있게)
            state[path.name] = batch[-1]["time"]
            save_state(state)
            total += len(batch)

    if total == 0:
        log("새로 보낼 줄이 없습니다.")
    return total


def main():
    parser = argparse.ArgumentParser(description="센서 CSV를 웹서비스로 전송")
    parser.add_argument("--once", action="store_true", help="한 번만 보내고 종료")
    parser.add_argument("--dry-run", action="store_true", help="실제로 보내지 않고 확인만")
    args = parser.parse_args()

    log(f"전송 대상: {API_URL}")
    log(f"읽는 폴더: {CSV_DIR}")

    if args.once or args.dry_run:
        upload_once(dry_run=args.dry_run)
        return

    while True:
        upload_once()
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("사용자가 중지했습니다.")
        sys.exit(0)
