/*
  아두이노 Uno 센서 수집 스케치 (초안 v0.1, 2026-10-09)

  하는 일
    1분마다 센서를 읽어서, 쉼표로 구분한 한 줄을 USB 시리얼(9600bps)로 보낸다.
      보내는 형식 : soil1,soil2,soil3,soil4,light,temp,hum
      예          : 612,598,705,690,820,24.00,55.00

  중요
    CSV 파일로 저장하는 일은 라즈베리파이가 한다(261009_pi_collector.py).
    아두이노에는 시계도 저장장치도 없어서 파일을 만들 수 없다.
    아두이노는 'CSV 한 줄 형식으로 보내기'까지만 담당한다.

  핀 배정
    토양수분(정전용량식) 화분1~4 : A1, A2, A3, A4
    조도 CdS GL12537 + 10kR 분압 : A5   (밝을수록 값이 커짐)
    온습도 DHT11                  : D2

  필요한 라이브러리
    Arduino IDE > 라이브러리 매니저에서 아래 두 개 설치
      - "DHT sensor library" (Adafruit)
      - "Adafruit Unified Sensor"
    이미 다른 DHT 라이브러리로 만든 코드가 있다면, 그 부분은 기존 것을 쓰고
    맨 아래 sendLine() 의 출력 형식만 가져다 쓰면 된다.

  주의
    라즈베리파이 쪽 프로그램은 '쉼표로 나뉜 값 7개'인 줄만 데이터로 받아들인다.
    그래서 평소에는 안내 문구를 출력하지 않는다.
    보정할 때처럼 사람이 눈으로 볼 때만 DEBUG 를 1 로 바꾼다.
*/

#include <DHT.h>

// ---------------------------------------------------------------------
// 설정
// ---------------------------------------------------------------------
#define DEBUG 0            // 0 = 라즈베리파이로 보내는 평소 모드
                           // 1 = 시리얼 모니터로 보기 좋게 출력(보정용)

const uint8_t SOIL_PINS[4] = {A1, A2, A3, A4};   // 화분 1,2,3,4 순서
const uint8_t LIGHT_PIN    = A5;
const uint8_t DHT_PIN      = 2;
#define DHT_TYPE DHT11

const unsigned long INTERVAL_MS = 60000UL;  // 1분마다 측정
const unsigned long DEBUG_INTERVAL_MS = 2000UL;  // 보정 모드에서는 2초마다

const uint8_t  SAMPLE_COUNT  = 10;   // 한 번 측정할 때 몇 번 읽어 평균 낼지
const uint8_t  SAMPLE_GAP_MS = 20;   // 읽기 사이 간격

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long lastMeasure = 0;
bool measuredOnce = false;

// ---------------------------------------------------------------------
// 아날로그 핀을 여러 번 읽어 평균을 낸다
//   - 첫 읽기를 버리는 이유: 아두이노 ADC 는 핀을 바꾼 직후 값이 덜 안정적이다.
//     특히 조도 분압처럼 임피던스가 높은 회로에서 차이가 난다.
//   - 평균을 내는 이유: 긴 선에서 들어오는 잡음을 줄이기 위해서다.
// ---------------------------------------------------------------------
int readAnalogAverage(uint8_t pin) {
  analogRead(pin);        // 버리는 읽기
  delay(5);

  long sum = 0;
  for (uint8_t i = 0; i < SAMPLE_COUNT; i++) {
    sum += analogRead(pin);
    delay(SAMPLE_GAP_MS);
  }
  return (int)(sum / SAMPLE_COUNT);
}

// ---------------------------------------------------------------------
// DHT11 읽기. 실패하면 두 번까지 다시 시도한다.
//   DHT11 은 연속으로 너무 빨리 읽으면 실패하므로 재시도 사이에 2초를 둔다.
//   끝까지 실패하면 NAN 을 돌려주고, 출력에서는 nan 으로 찍힌다.
// ---------------------------------------------------------------------
void readDHT(float &temperature, float &humidity) {
  for (uint8_t attempt = 0; attempt < 3; attempt++) {
    humidity    = dht.readHumidity();
    temperature = dht.readTemperature();   // 섭씨
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
//   soil1,soil2,soil3,soil4,light,temp,hum
// ---------------------------------------------------------------------
void sendLine(const int soil[4], int light, float temperature, float humidity) {
  for (uint8_t i = 0; i < 4; i++) {
    Serial.print(soil[i]);
    Serial.print(',');
  }
  Serial.print(light);
  Serial.print(',');

  if (isnan(temperature)) Serial.print("nan");
  else                    Serial.print(temperature, 2);
  Serial.print(',');

  if (isnan(humidity)) Serial.print("nan");
  else                 Serial.print(humidity, 2);

  Serial.println();   // 줄바꿈까지 보내야 라즈베리파이가 한 줄로 인식한다
}

// ---------------------------------------------------------------------
// 보정할 때 사람이 보기 좋은 출력 (DEBUG 1 일 때만)
//   토양수분 센서를 공기 중 / 물속 / 마른 흙 / 물 준 직후 흙에 두고
//   값을 적어서 보정표를 채운다.
// ---------------------------------------------------------------------
void printForHuman(const int soil[4], int light, float temperature, float humidity) {
  Serial.println(F("---------------------------------------"));
  for (uint8_t i = 0; i < 4; i++) {
    Serial.print(F("화분"));
    Serial.print(i + 1);
    Serial.print(F(" (A"));
    Serial.print(i + 1);
    Serial.print(F(") 토양수분 = "));
    Serial.println(soil[i]);
  }
  Serial.print(F("조도 (A5)      = "));
  Serial.println(light);

  Serial.print(F("온도           = "));
  if (isnan(temperature)) Serial.println(F("읽기 실패"));
  else { Serial.print(temperature, 2); Serial.println(F(" C")); }

  Serial.print(F("습도           = "));
  if (isnan(humidity)) Serial.println(F("읽기 실패"));
  else { Serial.print(humidity, 2); Serial.println(F(" %")); }
}

// ---------------------------------------------------------------------
void setup() {
  Serial.begin(9600);
  dht.begin();
  delay(2000);          // DHT11 이 깨어날 시간

#if DEBUG
  Serial.println(F("보정 모드입니다. 2초마다 값을 보여줍니다."));
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

  // 전원을 켜거나 포트를 열면 곧바로 한 번 측정하고,
  // 그다음부터는 정해진 간격마다 측정한다.
  // (unsigned 로 빼기 때문에 millis() 가 약 49일 만에 0으로 돌아가도 문제없다)
  if (measuredOnce && (now - lastMeasure) < interval) {
    return;
  }
  measuredOnce = true;
  lastMeasure  = now;

  int soil[4];
  for (uint8_t i = 0; i < 4; i++) {
    soil[i] = readAnalogAverage(SOIL_PINS[i]);
  }
  int light = readAnalogAverage(LIGHT_PIN);

  float temperature, humidity;
  readDHT(temperature, humidity);

#if DEBUG
  printForHuman(soil, light, temperature, humidity);
#else
  sendLine(soil, light, temperature, humidity);
#endif
}
