#include <cassert>
#include <cmath>
#include <iostream>
#include "Arduino.h"
#include "HardwareSerial.h"
#include "HLK_LD2450.h"

unsigned long g_mock_millis = 1000;

static void push_sm16(HardwareSerial &s, int16_t v) {
  uint16_t raw = (v >= 0) ? (0x8000U | static_cast<uint16_t>(v)) : static_cast<uint16_t>(-v);
  s.push(static_cast<uint8_t>(raw & 0xFF));
  s.push(static_cast<uint8_t>((raw >> 8) & 0xFF));
}

static void push_frame(HardwareSerial &s, int16_t x1, int16_t y1, int16_t spd1) {
  const uint8_t hdr[4] = {0xAA, 0xFF, 0x03, 0x00};
  for (uint8_t b : hdr) s.push(b);
  push_sm16(s, x1);
  push_sm16(s, y1);
  push_sm16(s, spd1);
  s.push(0x68); s.push(0x01); // 360 mm resolution
  for (int i = 0; i < 16; ++i) s.push(0x00); // targets 2 & 3 empty
  s.push(0x55); s.push(0xCC);
}

int main() {
  HardwareSerial ser;
  HLK_LD2450 radar(ser);

  // Leading garbage bytes + valid negative-X, positive-Y target (-1500mm, +2000mm -> 2.50m)
  ser.push(0xFF);
  ser.push(0x00);
  push_frame(ser, -1500, 2000, -40);
  radar.update();

  assert(radar.targets[0].valid);
  assert(radar.targets[0].x_mm == -1500);
  assert(radar.targets[0].y_mm == 2000);
  assert(radar.targets[0].speed_cm_s == -40);
  assert(std::fabs(radar.targets[0].distance_m - 2.5f) < 0.01f);
  assert(radar.targets[0].angle_deg < 0.0f);
  assert(!radar.targets[1].valid);

  // Advance clock past STALE_TIMEOUT_MS -> targets cleared automatically
  g_mock_millis += STALE_TIMEOUT_MS + 50;
  radar.update();
  assert(!radar.targets[0].valid);

  std::cout << "C++ HLK_LD2450 tests passed!\n";
  return 0;
}
