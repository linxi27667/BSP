/**
 * @file    bsp_servo.c
 * @brief   舵机核心逻辑实现（BSP — 纯逻辑，跨平台）
 */
#include "bsp_servo.h"

/* ================= 1. 设备初始化 ================= */

void Servo_Init_Device(servo_t *servo)
{
    if (servo == NULL) return;
    servo->angle = SERVO_MIN_ANGLE;
    if (servo->Init != NULL) {
        servo->Init(servo->pwm_pin.timer, servo->pwm_pin.channel);
    }
}

/* ================= 2. 角度控制 ================= */

void Servo_Set_Angle(servo_t *servo, float angle)
{
    if (servo == NULL) return;

    if (angle < SERVO_MIN_ANGLE) angle = SERVO_MIN_ANGLE;
    if (angle > SERVO_MAX_ANGLE) angle = SERVO_MAX_ANGLE;
    servo->angle = angle;

    /* 0° -> 500us, 180° -> 2500us */
    uint16_t pulse = (uint16_t)((angle / 180.0f) * 2000.0f + 500.0f);
    if (servo->Set_Pulse != NULL) {
        servo->Set_Pulse(servo->pwm_pin.timer, servo->pwm_pin.channel, pulse);
    }
}
