/*
 * ESP32-S3 HLK-LD2450 Radar Tracker with OLED Display
 * 
 * A radar motion tracker inspired by the Alien Motion Tracker
 * Features circular radar display with up to 3 target tracking
 * 
 * Hardware:
 * - ESP32-S3 ProS3 (UnexpectedMaker)
 * - HLK-LD2450 24GHz Radar Sensor
 * - Adafruit 128x64 Monochrome OLED (SSD1306)
 * 
 * Connections:
 * Radar: TX->GPIO17, RX->GPIO18, VCC->5V, GND->GND
 * OLED:  SDA->GPIO8, SCL->GPIO9, VCC->3.3V, GND->GND
 */

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "HLK_LD2450.h"
#include "RadarDisplay.h"

// OLED Display settings
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define SCREEN_ADDRESS 0x3C

// UART pins for HLK-LD2450
#define RADAR_RX_PIN 17
#define RADAR_TX_PIN 18

// I2C pins for OLED
#define I2C_SDA 8
#define I2C_SCL 9

// Create objects
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
HLK_LD2450 radar(Serial1);
RadarDisplay radarDisplay(&display);

unsigned long lastUpdate = 0;
const unsigned long UPDATE_INTERVAL = 50; // Update every 50ms (20 FPS)

void setup() {
  // Initialize USB Serial for debugging
  Serial.begin(115200);
  delay(1000);
  Serial.println("ESP32-S3 Radar Tracker Starting...");
  
  // Initialize I2C for OLED
  Wire.begin(I2C_SDA, I2C_SCL);
  
  // Initialize OLED display
  if(!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) {
    Serial.println(F("SSD1306 allocation failed"));
    for(;;); // Don't proceed, loop forever
  }
  
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(10, 20);
  display.println(F("Radar Tracker"));
  display.setCursor(10, 35);
  display.println(F("Initializing..."));
  display.display();
  delay(1000);
  
  // Initialize UART for HLK-LD2450
  Serial1.begin(256000, SERIAL_8N1, RADAR_RX_PIN, RADAR_TX_PIN);
  Serial.println("UART initialized at 256000 baud");
  
  // Initialize radar display
  radarDisplay.begin();
  
  Serial.println("Setup complete!");
  delay(500);
}

void loop() {
  unsigned long currentMillis = millis();
  
  // Read radar data
  radar.update();
  
  // Update display at regular intervals
  if (currentMillis - lastUpdate >= UPDATE_INTERVAL) {
    lastUpdate = currentMillis;
    
    // Clear display
    display.clearDisplay();
    
    // Draw radar screen
    radarDisplay.drawRadarScreen();
    
    // Get target data and plot on radar
    int targetCount = 0;
    for (int i = 0; i < 3; i++) {
      if (radar.targets[i].valid) {
        float distance = radar.targets[i].distance_m;
        float angle = radar.targets[i].angle_deg;
        
        // Only display targets within reasonable range
        if (distance > 0.1 && distance < 8.0) {
          radarDisplay.plotTarget(distance, angle, i);
          targetCount++;
        }
      }
    }
    
    // Draw target info text
    radarDisplay.drawTargetInfo(radar.targets, targetCount);
    
    // Display everything
    display.display();
    
    // Debug output to Serial
    if (targetCount > 0) {
      Serial.printf("Targets: %d | ", targetCount);
      for (int i = 0; i < 3; i++) {
        if (radar.targets[i].valid) {
          Serial.printf("T%d: %.2fm %.1f° | ", 
                       i+1, 
                       radar.targets[i].distance_m, 
                       radar.targets[i].angle_deg);
        }
      }
      Serial.println();
    }
  }
  
  // Small delay to prevent overwhelming the CPU
  delay(5);
}
