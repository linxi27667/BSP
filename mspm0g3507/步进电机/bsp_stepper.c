/**
 * @file    bsp_stepper.c
 * @brief   步进电机核心逻辑实现（BSP — 纯逻辑，跨平台）
 */
#include "bsp_stepper.h"

/* ================= 1. 设备初始化 ================= */

void Stepper_Init_Device(stepper_t *stepper)
{
    if (stepper == NULL || stepper->Init == NULL) return;
    stepper->Init();
}

/* ================= 2. 步进控制 ================= */

void Stepper_Run(stepper_t *stepper, uint8_t dir, uint32_t steps, uint32_t delay_us)
{
    if (stepper == NULL || stepper->Gpio_Write == NULL || stepper->Delay_us == NULL) return;

    stepper->Gpio_Write(stepper->dir_pin.port, stepper->dir_pin.pin, dir ? 1 : 0);
    for (uint32_t i = 0; i < steps; i++) {
        stepper->Gpio_Write(stepper->step_pin.port, stepper->step_pin.pin, 1);
        stepper->Delay_us(delay_us);
        stepper->Gpio_Write(stepper->step_pin.port, stepper->step_pin.pin, 0);
        stepper->Delay_us(delay_us);
    }
}
