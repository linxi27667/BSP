#ifndef __LED_H__
#define __LED_H__

#include "main.h"

#define LED_NUM 8

#define LED1_PIN GPIO_PIN_8
#define LED2_PIN GPIO_PIN_9
#define LED3_PIN GPIO_PIN_10
#define LED4_PIN GPIO_PIN_11
#define LED5_PIN GPIO_PIN_12
#define LED6_PIN GPIO_PIN_13
#define LED7_PIN GPIO_PIN_14
#define LED8_PIN GPIO_PIN_15

#define LED1_PORT GPIOC
#define LED2_PORT GPIOC
#define LED3_PORT GPIOC
#define LED4_PORT GPIOC
#define LED5_PORT GPIOC
#define LED6_PORT GPIOC
#define LED7_PORT GPIOC
#define LED8_PORT GPIOC

#define LED_ON GPIO_PIN_RESET
#define LED_OFF GPIO_PIN_SET


typedef struct led
{
    GPIO_TypeDef *port;
    uint16_t pin;
    GPIO_PinState state;
}led_t;

void Led_Init(led_t *led);
void Led_On(led_t *led);
void Led_Off(led_t *led);

extern led_t my_led[LED_NUM];
#endif
