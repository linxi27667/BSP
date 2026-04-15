#include "app_led.h"
#include "main.h"

static void HW_Gpio_Write(void *port, uint16_t pin, uint8_t level) {
    if (level) DL_GPIO_setPins((GPIO_RegDef *)port, pin);
    else DL_GPIO_clearPins((GPIO_RegDef *)port, pin);
}

led_t g_led[LED_NUM] = {
    {
        .gpio = { .port = LED1_PORT, .pin = LED1_PIN_22_PIN },
        .state = LED_STATE_OFF,
        .Gpio_Write = HW_Gpio_Write
    }
};

void App_LED_Init(void) {
    for (uint8_t i = 0; i < LED_NUM; i++) BSP_LED_Init(&g_led[i]);
}
