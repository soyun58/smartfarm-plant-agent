/*
  진단용 스케치 (2026-10-22)

  왜 쓰나
    센서 코드가 아무것도 출력하지 않을 때, 원인이
      (1) 시리얼 연결 자체인지
      (2) I2C 배선(BH1750)인지
    를 갈라서 확인하기 위한 것이다.

  하는 일
    1초마다 살아있다는 표시를 찍고, I2C 선에 어떤 장치가 붙어 있는지 찾아 준다.
    라이브러리가 필요 없다 (Wire 는 아두이노에 기본 포함).

  보는 법
    시리얼 모니터 속도를 9600 으로 맞출 것.

    - 아무것도 안 나온다          -> 시리얼/포트/속도 문제. 센서와 무관
    - "살아있음" 만 반복된다      -> 시리얼은 정상. I2C 선에 장치가 안 보임 = 배선 문제
    - "0x23 에서 장치 발견"       -> BH1750 정상 인식. 본 코드로 돌아가면 된다
    - "0x5C 에서 장치 발견"       -> BH1750 이 다른 주소로 잡힘 (ADDR 핀이 HIGH)
*/

#include <Wire.h>

unsigned long count = 0;

void setup() {
  Serial.begin(9600);
  delay(500);
  Serial.println();
  Serial.println(F("=== 진단 스케치 시작 ==="));
  Serial.println(F("이 글자가 보이면 시리얼 연결은 정상입니다."));
  Serial.println(F("BH1750 연결: SDA=A4, SCL=A5, VCC=5V, GND=GND"));
  Serial.println();

  Wire.begin();
}

void loop() {
  count++;
  Serial.print(F("[")); Serial.print(count); Serial.println(F("] 살아있음 - I2C 검색 중..."));

  uint8_t found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      found++;
      Serial.print(F("  -> 0x"));
      if (addr < 16) Serial.print('0');
      Serial.print(addr, HEX);
      Serial.print(F(" 에서 장치 발견"));
      if (addr == 0x23 || addr == 0x5C) Serial.print(F("  (BH1750 조도센서로 보임)"));
      Serial.println();
    }
  }

  if (found == 0) {
    Serial.println(F("  -> 아무 장치도 못 찾음"));
    Serial.println(F("     확인할 것: SDA가 A4인지 / SCL이 A5인지 / VCC,GND가 바뀌지 않았는지"));
    Serial.println(F("     (SDA와 SCL을 서로 바꿔 꽂는 실수가 가장 흔합니다)"));
  }

  Serial.println();
  delay(3000);
}
