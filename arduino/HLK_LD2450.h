/*
 * HLK-LD2450 Radar Sensor Library
 * 
 * Handles serial communication with HLK-LD2450 24GHz radar sensor
 * Decodes target position data (x, y, speed, resolution)
 * Supports up to 3 simultaneous targets
 */

#ifndef HLK_LD2450_H
#define HLK_LD2450_H

#include <Arduino.h>
#include <HardwareSerial.h>

// Protocol constants
#define REPORT_HEADER_SIZE 4
#define REPORT_TAIL_SIZE 2
#define TARGET_DATA_SIZE 8
#define NUM_TARGETS 3
#define FRAME_SIZE 30

// Frame markers
const uint8_t REPORT_HEADER[4] = {0xAA, 0xFF, 0x03, 0x00};
const uint8_t REPORT_TAIL[2] = {0x55, 0xCC};

struct Target {
  bool valid;
  int16_t x_mm;        // X coordinate in mm
  int16_t y_mm;        // Y coordinate in mm
  float distance_m;    // Calculated distance in meters
  float angle_deg;     // Calculated angle in degrees
  int16_t speed_cm_s;  // Speed in cm/s
  uint16_t resolution; // Distance resolution
};

class HLK_LD2450 {
public:
  HLK_LD2450(HardwareSerial &serial) : _serial(serial) {
    clearTargets();
  }
  
  void update() {
    // Read available data from serial
    while (_serial.available()) {
      uint8_t byte = _serial.read();
      
      // Look for frame header
      if (!_receivingFrame) {
        _buffer[_bufferIndex++] = byte;
        
        // Keep only last 4 bytes to check for header
        if (_bufferIndex >= 4) {
          if (checkHeader()) {
            _receivingFrame = true;
            _bufferIndex = 4; // Keep header
          } else {
            // Shift buffer left
            for (int i = 0; i < 3; i++) {
              _buffer[i] = _buffer[i + 1];
            }
            _bufferIndex = 3;
          }
        }
      } else {
        // Receiving frame data
        _buffer[_bufferIndex++] = byte;
        
        // Check if we have a complete frame
        if (_bufferIndex >= FRAME_SIZE) {
          if (checkTail()) {
            parseFrame();
          }
          resetBuffer();
        }
        
        // Prevent buffer overflow
        if (_bufferIndex >= 50) {
          resetBuffer();
        }
      }
    }
  }
  
  Target targets[NUM_TARGETS];
  
private:
  HardwareSerial &_serial;
  uint8_t _buffer[50];
  int _bufferIndex = 0;
  bool _receivingFrame = false;
  
  void clearTargets() {
    for (int i = 0; i < NUM_TARGETS; i++) {
      targets[i].valid = false;
      targets[i].x_mm = 0;
      targets[i].y_mm = 0;
      targets[i].distance_m = 0.0;
      targets[i].angle_deg = 0.0;
      targets[i].speed_cm_s = 0;
      targets[i].resolution = 0;
    }
  }
  
  bool checkHeader() {
    for (int i = 0; i < REPORT_HEADER_SIZE; i++) {
      if (_buffer[i] != REPORT_HEADER[i]) {
        return false;
      }
    }
    return true;
  }
  
  bool checkTail() {
    int tailStart = FRAME_SIZE - REPORT_TAIL_SIZE;
    for (int i = 0; i < REPORT_TAIL_SIZE; i++) {
      if (_buffer[tailStart + i] != REPORT_TAIL[i]) {
        return false;
      }
    }
    return true;
  }
  
  void parseFrame() {
    // Parse 3 targets (each target is 8 bytes)
    int offset = REPORT_HEADER_SIZE; // Start after header
    
    for (int i = 0; i < NUM_TARGETS; i++) {
      int16_t x = (int16_t)(_buffer[offset + 1] << 8 | _buffer[offset]);
      int16_t y = (int16_t)(_buffer[offset + 3] << 8 | _buffer[offset + 2]);
      int16_t speed = (int16_t)(_buffer[offset + 5] << 8 | _buffer[offset + 4]);
      uint16_t resolution = (uint16_t)(_buffer[offset + 7] << 8 | _buffer[offset + 6]);
      
      // Check if target is valid (not zero)
      if (x == 0 && y == 0) {
        targets[i].valid = false;
      } else {
        targets[i].valid = true;
        targets[i].x_mm = x;
        targets[i].y_mm = y;
        targets[i].speed_cm_s = speed;
        targets[i].resolution = resolution;
        
        // Calculate distance and angle
        targets[i].distance_m = sqrt(x * x + y * y) / 1000.0; // Convert mm to m
        targets[i].angle_deg = atan2(x, y) * 180.0 / PI; // Angle from center
      }
      
      offset += TARGET_DATA_SIZE;
    }
  }
  
  void resetBuffer() {
    _bufferIndex = 0;
    _receivingFrame = false;
  }
};

#endif // HLK_LD2450_H
