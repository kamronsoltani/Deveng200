#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>

// ---------- Pins (GPIO numbers, Seeed XIAO ESP32-C3) ----------
#define PIN_SDA   20   // D7, OLED
#define PIN_SCL   8    // D8, OLED
#define PIN_BTN   6    // D4, other side to GND, changes OLED page
#define PIN_P1    3    // D1, pressure sensor 1 (100 psi)
#define PIN_P2    4    // D2, pressure sensor 2 (20 psi)
#define PIN_FLOW  21   // D6, flow sensor signal (yellow wire)

// ---------- Pressure sensor settings (NOT calibrated) ----------
// Ratiometric sensors: output = 10% to 90% of supply = 0 to full scale.
// Measure the real supply voltage and update SUPPLY_V.
#define P1_FULLSCALE_PSI 100.0f
#define P2_FULLSCALE_PSI 20.0f
#define SUPPLY_V         3.3f

// ---------- Flow calibration (from 13 gravimetric runs, 6.4 to 18.4 Hz) ----------
// pulses per liter = PPL_A * Hz + PPL_B
// L/min = Hz * 60 / pulses per liter
// Below HZ_MIN_VALID the calibration was not tested.
const float PPL_A = 0.31824f;
const float PPL_B = 28.929f;
const float HZ_MIN_VALID = 6.0f;

#define UPDATE_MS 500

U8G2_SSD1306_128X32_UNIVISION_F_HW_I2C u8g2(U8G2_R2, U8X8_PIN_NONE);

volatile uint32_t pulseCount = 0;
void IRAM_ATTR onPulse() { pulseCount++; }

volatile bool btnFlag = false;
volatile uint32_t btnIsrMs = 0;
void IRAM_ATTR onBtn() {
  uint32_t t = millis();
  if (t - btnIsrMs > 200) { btnIsrMs = t; btnFlag = true; }
}

uint32_t lastMs = 0, lastPulses = 0;
float totalL = 0;
int page = 0;
const int NUM_PAGES = 2;
String inbuf;

float readVolts(int pin) {
  uint32_t sum = 0;
  for (int i = 0; i < 16; i++) sum += analogReadMilliVolts(pin);
  return sum / 16.0f / 1000.0f;
}

float voltsToPsi(float v, float fullScale) {
  return (v / SUPPLY_V - 0.10f) / 0.80f * fullScale;
}

const char* pStatus(float v) {
  if (v < 0.15f) return "NO SIG";
  if (v > 3.05f) return "HIGH";
  return "OK";
}

float hzToLpm(float f) {
  if (f <= 0) return 0;
  return f * 60.0f / (PPL_A * f + PPL_B);
}

void drawLines(const char* l0, const char* l1, const char* l2, const char* l3) {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_5x7_tf);
  u8g2.drawStr(0, 7, l0);
  u8g2.drawStr(0, 15, l1);
  u8g2.drawStr(0, 23, l2);
  u8g2.drawStr(0, 31, l3);
  u8g2.sendBuffer();
}

void setup() {
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
  delay(1500);

  Wire.setPins(PIN_SDA, PIN_SCL);
  Wire.begin();
  Wire.setClock(400000);
  u8g2.begin();

  pinMode(PIN_BTN, INPUT_PULLUP);
  pinMode(PIN_FLOW, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_BTN), onBtn, FALLING);
  attachInterrupt(digitalPinToInterrupt(PIN_FLOW), onPulse, FALLING);

  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  Serial.println("Flow + pressure monitor. Button: change page. Serial 'r': reset total.");
  lastMs = millis();
  lastPulses = pulseCount;
}

void loop() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      inbuf.trim();
      if (inbuf == "r") { totalL = 0; Serial.println("Total reset."); }
      inbuf = "";
    } else {
      inbuf += ch;
    }
  }

  if (btnFlag) {
    btnFlag = false;
    page = (page + 1) % NUM_PAGES;
  }

  uint32_t now = millis();
  if (now - lastMs < UPDATE_MS) return;

  float dt = (now - lastMs) / 1000.0f;
  uint32_t p = pulseCount;
  float hz = (p - lastPulses) / dt;
  lastMs = now;
  lastPulses = p;

  float lpm = hzToLpm(hz);
  totalL += lpm * dt / 60.0f;

  float v1 = readVolts(PIN_P1);
  float v2 = readVolts(PIN_P2);
  float psi1 = voltsToPsi(v1, P1_FULLSCALE_PSI);
  float psi2 = voltsToPsi(v2, P2_FULLSCALE_PSI);

  Serial.printf("%.2f Hz  %.2f L/min  total %.3f L  P1 %.2f psi  P2 %.2f psi  (%.3fV %s, %.3fV %s)\n",
    hz, lpm, totalL, psi1, psi2, v1, pStatus(v1), v2, pStatus(v2));

  char a[32], b[32], c[32], d[32];
  if (page == 0) {
    snprintf(a, sizeof a, "Flow %.1f Hz", hz);
    snprintf(b, sizeof b, "%.2f L/min%s", lpm, (hz > 0 && hz < HZ_MIN_VALID) ? " ~" : "");
    snprintf(c, sizeof c, "Total %.2f L", totalL);
    snprintf(d, sizeof d, "P1 %.1f P2 %.1f", psi1, psi2);
  } else {
    snprintf(a, sizeof a, "P1 %.2fV %s", v1, pStatus(v1));
    snprintf(b, sizeof b, "   %.1f psi", psi1);
    snprintf(c, sizeof c, "P2 %.2fV %s", v2, pStatus(v2));
    snprintf(d, sizeof d, "   %.1f psi", psi2);
  }
  drawLines(a, b, c, d);
}