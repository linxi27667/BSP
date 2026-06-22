#ifndef __BSP_LED_H__
#define __BSP_LED_H__

#include <stdint.h>
#include <stdbool.h>

/* --- 1. 抽象 GPIO 泛型 --- */
typedef struct {
    void    *port;
    uint16_t pin;
} led_gpio_t;

/* --- 2. LED 状态枚举 --- */
typedef enum {
    LED_STATE_OFF = 0,
    LED_STATE_ON  = 1
} led_state_t;

/* --- 3. LED 对象类 --- */
typedef struct led_dev {
    led_gpio_t gpio;
    led_state_t state;

    /* 硬件底层操作方法指针 */
    void (*Gpio_Write)(void *port, uint16_t pin, uint8_t level);
} led_t;

/* --- 4. 对外暴露的高级 API --- */
void BSP_LED_Init(led_t *led);
void BSP_LED_On(led_t *led);
void BSP_LED_Off(led_t *led);
void BSP_LED_Toggle(led_t *led);

#endif /* __BSP_LED_H__ */
