#ifndef MOCK_HARDWARE_SERIAL_H
#define MOCK_HARDWARE_SERIAL_H

#include <cstdint>
#include <deque>

class HardwareSerial {
public:
  void push(uint8_t b) { _rx.push_back(b); }
  int available() const { return static_cast<int>(_rx.size()); }
  int read() {
    if (_rx.empty()) return -1;
    uint8_t b = _rx.front();
    _rx.pop_front();
    return b;
  }
private:
  std::deque<uint8_t> _rx;
};

#endif
