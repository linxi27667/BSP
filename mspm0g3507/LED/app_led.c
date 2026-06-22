/**
 * @file    app_led.c
 * @brief   LED 硬件绑定实现（MSPM0G3507）
 */
#include "app_led.h"
#include "ti_msp_dl_config.h"

/* ================= 1. 硬件底层函数 (HW_ 前缀) ================= */

static void HW_Gpio_Write(void *port, uint16_t pin, uint8_t level)
{
    if (level)
        DL_GPIO_setPins((GPIO_Regs *)port, pin);
    else
        DL_GPIO_clearPins((GPIO_Regs *)port, pin);
}

/* ================= 2. 对象实例化与引脚拼装 ================= */

led_t g_led[LED_NUM] = {
    {
        .gpio = { .port = LED1_PORT, .pin = LED1_PIN_22_PIN },
        .state = LED_STATE_OFF,
        .Gpio_Write = HW_Gpio_Write
    }
};

/* ================= 3. 对外业务切入点 ================= */

void App_LED_Init(void)
{
    for (uint8_t i = 0; i < LED_NUM; i++)
        BSP_LED_Init(&g_led[i]);
}
