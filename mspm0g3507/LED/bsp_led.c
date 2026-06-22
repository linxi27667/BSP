/**
 * @file    bsp_led.c
 * @brief   LED 驱动核心逻辑实现（BSP — 纯逻辑，跨平台）
 */
#include "bsp_led.h"

/* ================= 1. 设备初始化 ================= */

void BSP_LED_Init(led_t *led)
{
    if (led == NULL || led->Gpio_Write == NULL) return;
    led->Gpio_Write(led->gpio.port, led->gpio.pin, led->state);
}

/* ================= 2. 开关控制 ================= */

void BSP_LED_On(led_t *led)
{
    if (led == NULL || led->Gpio_Write == NULL) return;
    led->Gpio_Write(led->gpio.port, led->gpio.pin, LED_STATE_ON);
    led->state = LED_STATE_ON;
}

void BSP_LED_Off(led_t *led)
{
    if (led == NULL || led->Gpio_Write == NULL) return;
    led->Gpio_Write(led->gpio.port, led->gpio.pin, LED_STATE_OFF);
    led->state = LED_STATE_OFF;
}

void BSP_LED_Toggle(led_t *led)
{
    if (led == NULL || led->Gpio_Write == NULL) return;
    led->state = (led->state == LED_STATE_ON) ? LED_STATE_OFF : LED_STATE_ON;
    led->Gpio_Write(led->gpio.port, led->gpio.pin, led->state);
}
