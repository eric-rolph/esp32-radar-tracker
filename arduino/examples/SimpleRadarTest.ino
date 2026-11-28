/*
 * Simple HLK-LD2450 Radar Test
 * 
 * This example prints raw radar data to Serial Monitor
 * Useful for testing radar connectivity and data reception
 * 
 * No OLED display required - just ESP32-S3 and radar
 */

#include "HLK_LD2450.h"

#define RADAR_RX_PIN 17
#define RADAR_TX_PIN 18

HLK_LD2450 radar(Serial1);

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("HLK-LD2450 Radar Test");
  Serial.println("====================");
  
  // Initialize UART for radar
  Serial1.begin(256000, SERIAL_8N1, RADAR_RX_PIN, RADAR_TX_PIN);
  Serial.println("Radar UART initialized at 256000 baud");
  Serial.println("Waiting for data...\n");
}

void loop() {
  radar.update();
  
  static unsigned long lastPrint = 0;
  if (millis() - lastPrint > 200) { // Print every 200ms
    lastPrint = millis();
    
    bool foundTarget = false;
    
    for (int i = 0; i < 3; i++) {
      if (radar.targets[i].valid) {
        if (!foundTarget) {
          Serial.println("--- Targets Detected ---");
          foundTarget = true;
        }
        
        Serial.printf("Target %d:\n", i + 1);
        Serial.printf("  Position: X=%d mm, Y=%d mm\n", 
                     radar.targets[i].x_mm, 
                     radar.targets[i].y_mm);
        Serial.printf("  Distance: %.2f m\n", radar.targets[i].distance_m);
        Serial.printf("  Angle: %.1f degrees\n", radar.targets[i].angle_deg);
        Serial.printf("  Speed: %d cm/s\n", radar.targets[i].speed_cm_s);
        Serial.printf("  Resolution: %u mm\n\n", radar.targets[i].resolution);
      }
    }
    
    if (!foundTarget) {
      Serial.println("No targets detected");
    }
    
    Serial.println();
  }
  
  delay(10);
}
