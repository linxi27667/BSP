/**
 * @file    bsp_stepper.h
 * @brief   步进电机核心驱动层
 */

#ifndef __BSP_STEPPER_H__
#define __BSP_STEPPER_H__

#include <stdint.h>
#include <stddef.h>

/* 1. 抽象 GPIO 对象 */
typedef struct {
    void* port;      // 端口 (如 GPIOA)
    uint16_t pin;       // 引脚 (如 GPIO_PIN_1)
} stepper_gpio_t;

/* 2. 步进电机类定义 */
typedef struct stepper_dev {
    // 物理引脚绑定
    stepper_gpio_t dir_pin;    // 方向引脚
    stepper_gpio_t step_pin;   // 脉冲引脚

    // 硬件接口绑定
    void (*Init)(void);                                   // 硬件初始化
    void (*Gpio_Write)(void* port, uint16_t pin, uint8_t level); // GPIO控制
    void (*Delay_us)(uint32_t us);                        // 微秒延时
} stepper_t;

/* 通用 API */
void Stepper_Init_Device(stepper_t *stepper);
void Stepper_Run(stepper_t *stepper, uint8_t dir, uint32_t steps, uint32_t delay_us);


#endif

