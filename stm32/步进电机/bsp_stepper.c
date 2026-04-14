/**
 * @file    bsp_stepper.c
 * @brief   实现脉冲发送逻辑
 */

#include "bsp_stepper.h"

void Stepper_Init_Device(stepper_t *stepper) {
    if (stepper == NULL || stepper->Init == NULL) return;
    stepper->Init();
}

/**
 * @brief 发送指定数量的脉冲
 * @param steps: 脉冲数 (比如输入1600就是转一圈)
 * @param delay_us: 脉冲宽度 (决定速度)
 */
void Stepper_Run(stepper_t *stepper, uint8_t dir, uint32_t steps, uint32_t delay_us) {
    if (stepper == NULL || stepper->Gpio_Write == NULL || stepper->Delay_us == NULL) return;

    // 1. 设置方向
    stepper->Gpio_Write(stepper->dir_pin.port, stepper->dir_pin.pin, dir ? 1 : 0);

    // 2. 循环发送脉冲：每个循环产生一次“高电平+低电平”
    for (uint32_t i = 0; i < steps; i++) {
        // 高电平
        stepper->Gpio_Write(stepper->step_pin.port, stepper->step_pin.pin, 1);
        stepper->Delay_us(delay_us);
        
        // 低电平
        stepper->Gpio_Write(stepper->step_pin.port, stepper->step_pin.pin, 0);
        stepper->Delay_us(delay_us);
    }
}
