#include "bsp_led.h"

led_t my_led[LED_NUM] = {
    {LED1_PORT, LED1_PIN, LED_OFF},
    {LED2_PORT, LED2_PIN, LED_OFF},
    {LED3_PORT, LED3_PIN, LED_OFF},
    {LED4_PORT, LED4_PIN, LED_OFF},
    {LED5_PORT, LED5_PIN, LED_OFF},
    {LED6_PORT, LED6_PIN, LED_OFF},
    {LED7_PORT, LED7_PIN, LED_OFF},
    {LED8_PORT, LED8_PIN, LED_OFF},
};

void Led_Init(led_t *led)
{
    uint8_t i = 0;
    for(i = 0; i < LED_NUM; i++)
    {
        HAL_GPIO_WritePin(led[i].port, led[i].pin, led[i].state);
    }
    #if(DEBUG_MODE == 1)
    elog_i("Led_Init", "led_init_successful");
    #endif
   // GPIO_InitTypeDef GPIO_InitStruct = {0};

   // __HAL_RCC_GPIOC_CLK_ENABLE();

   // GPIO_InitStruct.Pin = LED1_PIN|LED2_PIN|LED3_PIN|LED4_PIN|LED5_PIN|LED6_PIN|LED7_PIN|LED8_PIN;
   // GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
   // GPIO_InitStruct.Pull = GPIO_NOPULL;
    //GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;

    //HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);
}

void Led_On(led_t *led)
{
    HAL_GPIO_WritePin(led->port, led->pin, LED_ON);
    led->state = LED_ON;
}

void Led_Off(led_t *led)
{
    HAL_GPIO_WritePin(led->port, led->pin, LED_OFF);
    led->state = LED_OFF;
}
