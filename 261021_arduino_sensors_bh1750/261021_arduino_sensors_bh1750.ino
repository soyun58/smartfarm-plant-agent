/*
  아두이노 Uno 센서 수집 스케치 — 조도센서 BH1750 버전 (초안 v0.2, 2026-10-21)

  이전 버전(261009_arduino_sensors)과 달라진 점
    1. 조도센서를 CdS(아날로그) → BH1750(I2C 디지털) 로 교체
    2. 조도 단위가 0~1023 상대값 → lux(럭스) 실제 값으로 바뀜
    3. I2C 가 A4/A5 를 쓰기 때문에 토양수분4를 A4 → A0 으로 옮김

  보내는 형식은 그대로 (쉼표로 구분한 7개 값, 1분마다)
      soil1,soil2,soil3,soil4,light,temp,hum
      예 : 576,567,570,563,3421.7,24.00,55.00
                            ^^^^^^ 여기가 lux

  핀 배정 (바뀐 부분에 ★)
    토양수분 화분1~3 : A0, A1, A2
    토양수분 화분4   : A3  ★ (A4 는 I2C 가 가져감)
    BH1750 SDA       : A4  ★
    BH1750 SCL       : A5  ★
    BH1750 VCC       : 5V (모듈이 5V 를 받는지 확인할 것) / GND : GND
    온습도 DHT11     : D2 (그대로)

  필요한 라이브러리 (Arduino IDE > 라이브러리 매니저에서 설치)
    - "BH1750" (Christopher Laws)
    - "DHT sensor library" (Adafruit) + "Adafruit Unified Sensor"
    Wire 는 아두이노에 기본으로 들어 있어 설치할 필요 없음

  주의
    라즈베리파이 쪽 수집 프로그램도 같이 바꿔야 한다.
    예전 프로그램은 조도값이 0~1023 을 넘으면 깨진 줄로 보고 버린다.
*/

#include <Wire.h>
#include <BH1750.h>
#include <DHT.h>

// ---------------------------------------------------------------------
// 설정
// ---------------------------------------------------------------------
#define DEBUG 0            // 0 = 라즈베리파이로 보내는 평소 모드
                           // 1 = 시리얼 모니터로 보기 좋게 출력(보정·점검용)

// 화분 번호 = 센서 라벨 번호가 되도록 맞춰 둔 것 (2026-11-01 정정)
//   A0=1번, A1=2번, A2=3번, A3=4번 센서가 꽂혀 있다.
//   (10/22~10/31 에는 코드가 {A1,A2,A3,A0} 순서로 읽어서 한 칸씩 밀려 있었다)
const uint8_t SOIL_PINS[4] = {A0, A1, A2, A3};

// 지금 실제로 흙에 꽂혀 있는 화분만 true 로 둔다.
// false 인 화분은 값 대신 nan 을 보내고, 라즈베리파이는 빈 칸으로 저장한다.
//   (근거) 센서가 안 꽂힌 핀은 주변 잡음을 주워 200~700 사이를 널뛴다.
//          그 값이 그대로 쌓이면 그래프와 챗봇 답변이 엉망이 된다.
// 화분을 다시 늘리면 해당 자리를 true 로 바꾸고 업로드하면 된다.
//                             화분1  화분2  화분3  화분4
const bool POT_IN_USE[4] = { false, false, false, true };
const uint8_t DHT_PIN = 2;
#define DHT_TYPE DHT11

const unsigned long INTERVAL_MS = 60000UL;       // 1분마다 측정
const unsigned long DEBUG_INTERVAL_MS = 2000UL;  // 점검 모드는 2초마다

const uint8_t SAMPLE_COUNT = 10;   // 토양수분을 몇 번 읽어 평균 낼지
const uint8_t SAMPLE_GAP_MS = 20;

DHT dht(DHT_PIN, DHT_TYPE);
BH1750 lightMeter;

bool lightReady = false;      // BH1750 이 준비됐는지
unsigned long lastMeasure = 0;
bool measuredOnce = false;

// ---------------------------------------------------------------------
// 토양수분: 여러 번 읽어 평균
//   첫 읽기를 버리는 이유 — 핀을 바꾼 직후에는 값이 덜 안정적이다.
// ---------------------------------------------------------------------
int readAnalogAverage(uint8_t pin) {
  analogRead(pin);
  delay(5);

  long sum = 0;
  for (uint8_t i = 0; i < SAMPLE_COUNT; i++) {
    sum += analogRead(pin);
    delay(SAMPLE_GAP_MS);
  }
  return (int)(sum / SAMPLE_COUNT);
}

// ---------------------------------------------------------------------
// 조도(lux) 읽기
//   BH1750 은 스스로 측정 시간을 갖기 때문에 여러 번 평균 낼 필요가 없다.
//   읽기에 실패하면 음수가 나온다. 그때는 연결을 다시 시도해 본다.
//   끝까지 안 되면 NAN 을 돌려주고 출력에서는 nan 으로 찍힌다.
// ---------------------------------------------------------------------
float readLux() {
  if (!lightReady) {
    // 전원을 켤 때 센서가 늦게 준비되는 경우가 있어 여기서 다시 시도한다
    lightReady = lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);
    if (!lightReady) {
      return NAN;
    }
    delay(200);
  }

  for (uint8_t attempt = 0; attempt < 3; attempt++) {
    float lux = lightMeter.readLightLevel();
    if (lux >= 0) {
      return lux;
    }
    delay(200);
  }

  lightReady = false;   // 다음 번에 연결부터 다시 시도
  return NAN;
}

// ---------------------------------------------------------------------
// DHT11 읽기 (실패하면 2초 간격으로 3번까지)
// ---------------------------------------------------------------------
void readDHT(float &temperature, float &humidity) {
  for (uint8_t attempt = 0; attempt < 3; attempt++) {
    humidity    = dht.readHumidity();
    temperature = dht.readTemperature();
    if (!isnan(humidity) && !isnan(temperature)) {
      return;
    }
    delay(2000);
  }
  temperature = NAN;
  humidity    = NAN;
}

// ---------------------------------------------------------------------
// 라즈베리파이로 보내는 한 줄
//   soil1,soil2,soil3,soil4,light(lux),temp,hum
// ---------------------------------------------------------------------
void sendLine(const int soil[4], float lux, float temperature, float humidity) {
  for (uint8_t i = 0; i < 4; i++) {
    if (POT_IN_USE[i]) Serial.print(soil[i]);
    else               Serial.print("nan");   // 안 쓰는 화분은 빈 값으로
    Serial.print(',');
  }

  if (isnan(lux)) Serial.print("nan");
  else            Serial.print(lux, 1);     // 소수점 한 자리 (예: 3421.7)
  Serial.print(',');

  if (isnan(temperature)) Serial.print("nan");
  else                    Serial.print(temperature, 2);
  Serial.print(',');

  if (isnan(humidity)) Serial.print("nan");
  else                 Serial.print(humidity, 2);

  Serial.println();
}

// ---------------------------------------------------------------------
// 점검 모드 출력 (DEBUG 1 일 때만)
// ---------------------------------------------------------------------
void printForHuman(const int soil[4], float lux, float temperature, float humidity) {
  const char *pinName[4] = {"A0", "A1", "A2", "A3"};

  Serial.println(F("---------------------------------------"));
  for (uint8_t i = 0; i < 4; i++) {
    Serial.print(F("화분"));
    Serial.print(i + 1);
    Serial.print(F(" ("));
    Serial.print(pinName[i]);
    Serial.print(F(") 토양수분 = "));
    if (POT_IN_USE[i]) Serial.println(soil[i]);
    else               Serial.println(F("사용 안 함"));
  }

  Serial.print(F("조도 (BH1750) = "));
  if (isnan(lux)) Serial.println(F("읽기 실패 - 배선(SDA=A4, SCL=A5)과 전원을 확인"));
  else { Serial.print(lux, 1); Serial.println(F(" lux")); }

  Serial.print(F("온도          = "));
  if (isnan(temperature)) Serial.println(F("읽기 실패"));
  else { Serial.print(temperature, 2); Serial.println(F(" C")); }

  Serial.print(F("습도          = "));
  if (isnan(humidity)) Serial.println(F("읽기 실패"));
  else { Serial.print(humidity, 2); Serial.println(F(" %")); }
}

// ---------------------------------------------------------------------
void setup() {
  Serial.begin(9600);

  Wire.begin();                                               // I2C 시작 (A4/A5)
  lightReady = lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);

  dht.begin();
  delay(2000);          // DHT11 과 BH1750 이 깨어날 시간

#if DEBUG
  Serial.println(F("점검 모드입니다. 2초마다 값을 보여줍니다."));
  if (!lightReady) {
    Serial.println(F("BH1750 을 찾지 못했습니다. SDA=A4, SCL=A5, 전원을 확인하세요."));
  }
  Serial.println(F("라즈베리파이에 연결할 때는 DEBUG 를 0 으로 바꾸세요."));
#endif
}

void loop() {
#if DEBUG
  const unsigned long interval = DEBUG_INTERVAL_MS;
#else
  const unsigned long interval = INTERVAL_MS;
#endif

  unsigned long now = millis();
  if (measuredOnce && (now - lastMeasure) < interval) {
    return;
  }
  measuredOnce = true;
  lastMeasure  = now;

  int soil[4];
  for (uint8_t i = 0; i < 4; i++) {
    // 안 쓰는 화분은 읽지 않는다 (읽어 봐야 잡음이고, 측정 시간만 늘어난다)
    soil[i] = POT_IN_USE[i] ? readAnalogAverage(SOIL_PINS[i]) : 0;
  }

  float lux = readLux();

  float temperature, humidity;
  readDHT(temperature, humidity);

#if DEBUG
  printForHuman(soil, lux, temperature, humidity);
#else
  sendLine(soil, lux, temperature, humidity);
#endif
}
