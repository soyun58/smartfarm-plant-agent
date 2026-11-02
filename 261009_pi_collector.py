#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
아두이노 Uno -> 라즈베리파이 5 센서값 수집 프로그램 (초안 v0.1, 2026-10-09)

하는 일
  1. USB 시리얼(기본 9600bps)로 아두이노가 보내는 한 줄을 계속 읽는다.
     기대 형식: soil1,soil2,soil3,soil4,light,temp,hum
     예:        612,598,705,690,820,24.00,55.00
  2. 1분마다 그 사이에 받은 값들의 평균을 CSV 한 줄로 저장한다.
     (아두이노가 1분에 한 번만 보내면 평균 대상이 1개이므로 그 값이 그대로 저장된다)
  3. 측정 시각은 라즈베리파이 시계로 붙인다. (아두이노에는 시계가 없음)

저장 위치: ~/plant-data/sensors_YYYY-MM-DD.csv  (하루에 파일 하나)

주의
  - 센서값은 0~1023 원래 값 그대로 저장한다. %로 바꾸는 일은 화면 쪽에서 한다.
    (근거) 나중에 보정을 다시 해도 예전 데이터를 살릴 수 있다.
  - DHT11 읽기에 실패하면 아두이노가 nan을 보낸다. 이때는 온습도 칸을 비워 두고
    note 칸에 dht_fail 을 적는다. 줄 자체를 버리지는 않는다.
  - 1분 동안 한 줄도 못 받으면 값이 빈 줄을 저장하고 note 에 no_data 를 적는다.
    (근거) 기록이 비어 있는 구간을 나중에 알아볼 수 있어야 한다.

실행:  python3 261009_pi_collector.py
멈춤:  Ctrl + C
"""

import csv
import glob
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import serial  # 설치: sudo apt install -y python3-serial
except ImportError:
    sys.exit("pyserial 이 없습니다.  sudo apt install -y python3-serial  로 설치하세요.")


# ----------------------------------------------------------------------
# 설정 — 이 부분만 환경에 맞게 고치면 된다
# ----------------------------------------------------------------------
# "auto" 로 두면 /dev/ttyUSB* 와 /dev/ttyACM* 를 뒤져서 먼저 찾은 포트를 쓴다.
#   - CH340 칩을 쓴 호환 보드 : /dev/ttyUSB0
#   - 아두이노 정품 Uno        : /dev/ttyACM0
# 아두이노 말고 다른 시리얼 장치도 꽂혀 있다면 "auto" 대신 직접 적는다.
#   PORT = "/dev/ttyUSB0"
# USB 를 다시 꽂으면 번호가 바뀔 수 있는데, 아래 by-id 경로를 쓰면 항상 같은 이름이 된다.
#   ls -l /dev/serial/by-id/
PORT = "auto"

BAUD = 9600          # 아두이노 코드의 Serial.begin() 값과 반드시 같아야 한다
PERIOD_SEC = 60      # 저장 간격(초). 1분 = 60
DATA_DIR = Path.home() / "plant-data"

# 아두이노가 보내는 값의 개수와 순서
FIELDS = ["soil1", "soil2", "soil3", "soil4", "light", "temp", "hum"]
INT_FIELDS = ["soil1", "soil2", "soil3", "soil4"]   # 0~1023 정수 (아날로그 입력)
CSV_HEADER = ["time"] + FIELDS + ["n_samples", "note"]

# 값의 허용 범위. 범위를 벗어나면 깨진 줄로 보고 버린다.
#   light 는 조도센서 종류에 따라 단위가 다르다.
#     - CdS(아날로그)  : 0~1023 상대값
#     - BH1750(I2C)    : lux. 맑은 날 실외는 수만까지 올라간다
#   둘 다 받아들이도록 넉넉하게 잡아 두었다.
VALUE_RANGE = {
    "soil1": (0, 1023), "soil2": (0, 1023), "soil3": (0, 1023), "soil4": (0, 1023),
    "light": (0, 200000),
    "temp": (-40, 100),
    "hum": (0, 100),
}


def log(msg):
    """화면에 시각과 함께 메시지를 찍는다."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def find_port():
    """
    쓸 시리얼 포트를 정한다.
    PORT 가 "auto" 면 /dev/ttyUSB* → /dev/ttyACM* 순서로 찾아 첫 번째를 쓴다.
    못 찾으면 SerialException 을 내고, 바깥에서 5초 뒤 다시 시도한다.
    """
    if PORT != "auto":
        return PORT

    candidates = sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))
    if not candidates:
        raise serial.SerialException(
            "시리얼 포트를 찾지 못했습니다. 아두이노 USB 연결을 확인하세요 "
            "(ls /dev/ttyUSB* /dev/ttyACM* 로 확인 가능)"
        )
    if len(candidates) > 1:
        log(f"포트 후보가 여러 개입니다 {candidates} → 첫 번째를 씁니다")
    return candidates[0]


def parse_line(line):
    """
    아두이노가 보낸 한 줄을 숫자 딕셔너리로 바꾼다.
    형식이 깨졌으면 None 을 돌려준다.
    """
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != len(FIELDS):
        return None

    row = {}
    for name, text in zip(FIELDS, parts):
        if text.lower() in ("nan", "", "-"):      # DHT 읽기 실패 등
            row[name] = None
            continue
        try:
            value = float(text)
        except ValueError:
            return None                            # 숫자가 아니면 줄 전체를 버린다
        if math.isnan(value):
            row[name] = None
            continue
        low, high = VALUE_RANGE[name]
        if not (low <= value <= high):
            return None                            # 범위를 벗어나면 깨진 줄로 본다
        row[name] = int(value) if name in INT_FIELDS else value
    return row


def average(samples):
    """
    1분 동안 모은 줄들의 평균을 낸다.
    값이 하나도 없는 항목(예: DHT 가 계속 실패)은 None 으로 남긴다.
    """
    result = {}
    for name in FIELDS:
        values = [s[name] for s in samples if s[name] is not None]
        if not values:
            result[name] = None
        elif name in INT_FIELDS:
            result[name] = round(sum(values) / len(values))
        elif name == "light":
            # 조도는 CdS면 정수처럼, BH1750이면 lux 소수로 들어온다. 한 자리까지만 남긴다.
            result[name] = round(sum(values) / len(values), 1)
        else:
            result[name] = round(sum(values) / len(values), 2)
    return result


def write_row(values, n_samples, note):
    """CSV 에 한 줄 추가한다. 날짜가 바뀌면 그날짜 파일에 쓴다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    path = DATA_DIR / f"sensors_{now:%Y-%m-%d}.csv"
    is_new = not path.exists()

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(CSV_HEADER)
        writer.writerow(
            [now.isoformat(timespec="seconds")]
            + ["" if values[name] is None else values[name] for name in FIELDS]
            + [n_samples, note]
        )
        f.flush()
        os.fsync(f.fileno())   # 갑자기 전원이 꺼져도 방금 쓴 줄이 남도록 디스크에 확정

    log(f"저장: {path.name}  n={n_samples}  note={note or '-'}")


def next_minute_mark():
    """다음 '분' 경계 시각(초 단위)을 돌려준다. 00초에 맞춰 저장하기 위한 것."""
    return (int(time.time()) // PERIOD_SEC + 1) * PERIOD_SEC


def collect_forever():
    while True:  # 포트가 끊기면 다시 연결을 시도한다
        try:
            port = find_port()
            log(f"{port} 포트를 여는 중 (속도 {BAUD})")
            with serial.Serial(port, BAUD, timeout=2) as ser:
                # 아두이노 Uno 는 시리얼 포트가 열리는 순간 리셋된다.
                # 부팅하면서 깨진 글자가 나올 수 있으므로 2초 기다렸다가 버퍼를 비운다.
                time.sleep(2)
                ser.reset_input_buffer()
                log("연결됨. 수집을 시작합니다. (멈추려면 Ctrl+C)")

                samples = []
                bad_lines = 0
                deadline = next_minute_mark()

                while True:
                    raw = ser.readline()           # timeout=2 이므로 값이 없어도 2초 뒤 돌아온다
                    if raw:
                        line = raw.decode("utf-8", errors="replace").strip()
                        if line:
                            parsed = parse_line(line)
                            if parsed is None:
                                bad_lines += 1
                                log(f"형식이 맞지 않는 줄 무시: {line[:60]}")
                            else:
                                samples.append(parsed)

                    if time.time() >= deadline:
                        notes = []
                        if samples:
                            values = average(samples)
                            if values["temp"] is None or values["hum"] is None:
                                notes.append("dht_fail")
                        else:
                            values = {name: None for name in FIELDS}
                            notes.append("no_data")
                        if bad_lines:
                            notes.append(f"bad_lines={bad_lines}")

                        write_row(values, len(samples), ";".join(notes))
                        samples = []
                        bad_lines = 0
                        deadline = next_minute_mark()

        except serial.SerialException as e:
            # USB 가 빠졌거나 포트 이름이 틀린 경우
            log(f"시리얼 오류: {e}  → 5초 뒤 다시 시도합니다")
            time.sleep(5)
        except PermissionError as e:
            log(f"권한 오류: {e}")
            log("sudo usermod -aG dialout $USER  실행 후 다시 로그인하세요.")
            time.sleep(10)


if __name__ == "__main__":
    log(f"수집 시작 — 저장 폴더: {DATA_DIR}")
    try:
        collect_forever()
    except KeyboardInterrupt:
        log("사용자가 중지했습니다.")
