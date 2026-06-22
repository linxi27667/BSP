#ifndef APP_LED_H
#define APP_LED_H

#include "bsp_led.h"

#define LED_NUM 1
extern led_t g_led[LED_NUM];
void App_LED_Init(void);

#endif /* APP_LED_H */
