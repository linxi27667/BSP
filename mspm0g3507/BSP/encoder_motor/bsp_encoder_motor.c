/**
 * @file    bsp_encoder_motor.c
 * @brief   霍尔编码器电机核心逻辑实现（BSP — 纯逻辑，跨平台）
 */
#include "bsp_encoder_motor.h"

/* ================= 1. 设备初始化 ================= */
void BSP_Motor_Init_Device(bsp_motor_t *motor)
{
    if (motor == NULL) return;

    motor->current_pwm    = 0;
    motor->encoder_speed  = 0;
    motor->total_position = 0;

    if (motor->Init != NULL) {
        motor->Init(motor);
    }
}

/* ================= 2. 速度控制（正转/反转/停止） ================= */
void BSP_Motor_Set_Speed(bsp_motor_t *motor, int32_t speed_val)
{
    if (motor == NULL) return;

    motor->current_pwm = speed_val;

    if (speed_val > 0) {
        if (motor->Gpio_Write) {
            motor->Gpio_Write(motor->dir_pin1.port, motor->dir_pin1.pin, 1);
            motor->Gpio_Write(motor->dir_pin2.port, motor->dir_pin2.pin, 0);
        }
        if (motor->Pwm_Write) {
            motor->Pwm_Write(motor->pwm_timer, motor->pwm_channel, (uint32_t)speed_val);
        }
    } else if (speed_val < 0) {
        if (motor->Gpio_Write) {
            motor->Gpio_Write(motor->dir_pin1.port, motor->dir_pin1.pin, 0);
            motor->Gpio_Write(motor->dir_pin2.port, motor->dir_pin2.pin, 1);
        }
        if (motor->Pwm_Write) {
            motor->Pwm_Write(motor->pwm_timer, motor->pwm_channel, (uint32_t)(-speed_val));
        }
    } else {
        if (motor->Gpio_Write) {
            motor->Gpio_Write(motor->dir_pin1.port, motor->dir_pin1.pin, 0);
            motor->Gpio_Write(motor->dir_pin2.port, motor->dir_pin2.pin, 0);
        }
        if (motor->Pwm_Write) {
            motor->Pwm_Write(motor->pwm_timer, motor->pwm_channel, 0);
        }
    }
}

/* ================= 3. 状态更新（编码器读取） ================= */
void BSP_Motor_Update_Status(bsp_motor_t *motor)
{
    if (motor == NULL) return;

    if (motor->Enc_Read != NULL) {
        motor->encoder_speed = motor->Enc_Read(motor->enc_timer);
        motor->total_position += motor->encoder_speed;
    }
}
