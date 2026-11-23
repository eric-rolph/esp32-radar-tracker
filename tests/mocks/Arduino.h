#ifndef MOCK_ARDUINO_H
#define MOCK_ARDUINO_H

#include <cmath>
#include <cstdint>

#ifndef PI
#define PI 3.14159265358979323846f
#endif

extern unsigned long g_mock_millis;
inline unsigned long millis() { return g_mock_millis; }

#endif
