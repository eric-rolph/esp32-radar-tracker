/*
 * Radar Display Library
 * 
 * Renders a circular radar display on monochrome OLED
 * Inspired by the Alien Motion Tracker aesthetic
 * Features range rings, angle markers, and target plotting
 */

#ifndef RADAR_DISPLAY_H
#define RADAR_DISPLAY_H

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "HLK_LD2450.h"

#define MAX_RANGE_M 6.0  // Maximum range to display (meters)

class RadarDisplay {
public:
  RadarDisplay(Adafruit_SSD1306 *display) : _display(display) {
    // Center of radar is in upper portion of screen
    _centerX = 64;  // Middle of 128px width
    _centerY = 35;  // Slightly offset for text area at bottom
    _maxRadius = 28; // Maximum radius for 6m range
  }
  
  void begin() {
    // Any initialization needed
  }
  
  void drawRadarScreen() {
    // Draw range rings (circles) - 2m, 4m, 6m
    for (int i = 1; i <= 3; i++) {
      int radius = (_maxRadius * i) / 3;
      drawDottedCircle(_centerX, _centerY, radius);
    }
    
    // Draw cross-hairs (angle markers every 45 degrees)
    drawAngleMarkers();
    
    // Draw center dot
    _display->fillCircle(_centerX, _centerY, 1, SSD1306_WHITE);
  }
  
  void plotTarget(float distance_m, float angle_deg, int targetIndex) {
    // Convert distance and angle to screen coordinates
    if (distance_m > MAX_RANGE_M) {
      distance_m = MAX_RANGE_M; // Clip to max range
    }
    
    // Calculate radius based on distance
    float radius = (distance_m / MAX_RANGE_M) * _maxRadius;
    
    // Convert angle to radians (0° is up, clockwise positive)
    float angle_rad = (angle_deg - 90.0) * PI / 180.0;
    
    // Calculate screen position
    int x = _centerX + (int)(radius * cos(angle_rad));
    int y = _centerY + (int)(radius * sin(angle_rad));
    
    // Draw target based on index (different sizes/styles)
    drawTarget(x, y, targetIndex);
  }
  
  void drawTargetInfo(Target targets[], int count) {
    // Draw text info at the bottom of screen
    _display->setTextSize(1);
    _display->setTextColor(SSD1306_WHITE);
    
    if (count == 0) {
      _display->setCursor(20, 56);
      _display->print(F("NO TARGETS"));
    } else {
      // Find closest target
      float minDist = 100.0;
      int closestIdx = -1;
      
      for (int i = 0; i < 3; i++) {
        if (targets[i].valid && targets[i].distance_m < minDist) {
          minDist = targets[i].distance_m;
          closestIdx = i;
        }
      }
      
      if (closestIdx >= 0) {
        // Display closest target info
        _display->setCursor(0, 56);
        _display->printf("T%d: %.1fm %d%c", 
                        closestIdx + 1,
                        targets[closestIdx].distance_m,
                        (int)targets[closestIdx].angle_deg,
                        (char)247); // Degree symbol
        
        // Show target count
        _display->setCursor(100, 56);
        _display->printf("[%d]", count);
      }
    }
  }
  
private:
  Adafruit_SSD1306 *_display;
  int _centerX, _centerY;
  int _maxRadius;
  
  void drawDottedCircle(int x0, int y0, int radius) {
    // Draw a dotted circle using Bresenham's algorithm
    int x = radius;
    int y = 0;
    int radiusError = 1 - x;
    int dotCounter = 0;
    
    while (x >= y) {
      // Draw 8 symmetric points, but only every Nth point for dotted effect
      if (dotCounter % 3 == 0) {
        _display->drawPixel(x + x0, y + y0, SSD1306_WHITE);
        _display->drawPixel(y + x0, x + y0, SSD1306_WHITE);
        _display->drawPixel(-x + x0, y + y0, SSD1306_WHITE);
        _display->drawPixel(-y + x0, x + y0, SSD1306_WHITE);
        _display->drawPixel(-x + x0, -y + y0, SSD1306_WHITE);
        _display->drawPixel(-y + x0, -x + y0, SSD1306_WHITE);
        _display->drawPixel(x + x0, -y + y0, SSD1306_WHITE);
        _display->drawPixel(y + x0, -x + y0, SSD1306_WHITE);
      }
      
      y++;
      dotCounter++;
      
      if (radiusError < 0) {
        radiusError += 2 * y + 1;
      } else {
        x--;
        radiusError += 2 * (y - x + 1);
      }
    }
  }
  
  void drawAngleMarkers() {
    // Draw angle markers at 45° intervals
    int markerLength = 4;
    
    for (int angle = 0; angle < 360; angle += 45) {
      float rad = (angle - 90) * PI / 180.0;
      
      // Inner point
      int x1 = _centerX + (int)((_maxRadius - markerLength) * cos(rad));
      int y1 = _centerY + (int)((_maxRadius - markerLength) * sin(rad));
      
      // Outer point
      int x2 = _centerX + (int)(_maxRadius * cos(rad));
      int y2 = _centerY + (int)(_maxRadius * sin(rad));
      
      _display->drawLine(x1, y1, x2, y2, SSD1306_WHITE);
    }
  }
  
  void drawTarget(int x, int y, int targetIndex) {
    // Draw target marker - style varies by target index
    switch (targetIndex) {
      case 0: // Primary target - filled circle
        _display->fillCircle(x, y, 2, SSD1306_WHITE);
        break;
        
      case 1: // Secondary target - hollow circle
        _display->drawCircle(x, y, 2, SSD1306_WHITE);
        break;
        
      case 2: // Tertiary target - small cross
        _display->drawLine(x - 2, y, x + 2, y, SSD1306_WHITE);
        _display->drawLine(x, y - 2, x, y + 2, SSD1306_WHITE);
        break;
    }
    
    // Add a subtle "glow" effect with a larger hollow circle
    if (targetIndex == 0) {
      _display->drawCircle(x, y, 4, SSD1306_WHITE);
    }
  }
};

#endif // RADAR_DISPLAY_H
