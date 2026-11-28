/*
 * OLED Display Test
 * 
 * Tests the Adafruit 128x64 OLED display
 * Draws a test pattern and text
 * 
 * No radar required - just ESP32-S3 and OLED
 */

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define SCREEN_ADDRESS 0x3C

#define I2C_SDA 8
#define I2C_SCL 9

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("OLED Display Test");
  
  // Initialize I2C
  Wire.begin(I2C_SDA, I2C_SCL);
  
  // Initialize OLED
  if(!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) {
    Serial.println(F("SSD1306 allocation failed"));
    for(;;);
  }
  
  Serial.println("OLED initialized successfully!");
  
  // Show initial display
  display.clearDisplay();
  display.setTextSize(2);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(10, 10);
  display.println(F("OLED"));
  display.setCursor(10, 30);
  display.println(F("Works!"));
  display.display();
  delay(2000);
}

void loop() {
  // Test pattern 1: Circles
  display.clearDisplay();
  for (int i = 10; i < 50; i += 10) {
    display.drawCircle(64, 32, i, SSD1306_WHITE);
  }
  display.display();
  delay(2000);
  
  // Test pattern 2: Lines
  display.clearDisplay();
  for (int i = 0; i < SCREEN_WIDTH; i += 10) {
    display.drawLine(0, 0, i, SCREEN_HEIGHT - 1, SSD1306_WHITE);
    display.drawLine(SCREEN_WIDTH - 1, 0, SCREEN_WIDTH - 1 - i, SCREEN_HEIGHT - 1, SSD1306_WHITE);
  }
  display.display();
  delay(2000);
  
  // Test pattern 3: Text
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println(F("Line 1: Test"));
  display.println(F("Line 2: Test"));
  display.println(F("Line 3: Test"));
  display.setTextSize(2);
  display.println(F("BIG!"));
  display.display();
  delay(2000);
  
  Serial.println("Test cycle complete");
}
