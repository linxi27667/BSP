/**
 * @file    bsp_encoder_motor.c
 * @brief   电机驱动核心逻辑流转
 * @note    此文件不关心引脚叫什么，也不关心用什么定时器，只负责逻辑判断并调用指针。
 */

#include "bsp_encoder_motor.h"

/**
 * @brief 初始化电机对象的数据流
 */
void Motor_Init_Device(motor_t *motor) {
    if (motor == NULL) return; 
    
    motor->current_pwm = 0;
    motor->encoder_speed = 0;
    motor->total_position = 0;

    // 执行底层硬件的初始化回调
    if (motor->Init != NULL) {
        motor->Init();
    }
}

/**
 * @brief 核心控制逻辑：设置速度与方向
 */
void Motor_Set_Speed(motor_t *motor, int32_t speed_val) {
    if (motor == NULL) return;

    motor->current_pwm = speed_val;

    // 根据符号决定运行方向，并通过抽象 Gpio_Write 接口控制绑定的引脚对象
    if (speed_val > 0) {
        if (motor->Gpio_Write != NULL) {
            // 正转逻辑：PIN1 置高，PIN2 置低
            motor->Gpio_Write(motor->dir_pin1.port, motor->dir_pin1.pin, 1);
            motor->Gpio_Write(motor->dir_pin2.port, motor->dir_pin2.pin, 0);
        }
        if (motor->Pwm_Write != NULL) {
            motor->Pwm_Write((uint32_t)speed_val);
        }
    } 
    else if (speed_val < 0) {
        if (motor->Gpio_Write != NULL) {
            // 反转逻辑：PIN1 置低，PIN2 置高
            motor->Gpio_Write(motor->dir_pin1.port, motor->dir_pin1.pin, 0);
            motor->Gpio_Write(motor->dir_pin2.port, motor->dir_pin2.pin, 1);
        }
        if (motor->Pwm_Write != NULL) {
            motor->Pwm_Write((uint32_t)(-speed_val)); // 取绝对值下发
        }
    } 
    else {
        if (motor->Gpio_Write != NULL) {
            // 停止/刹车逻辑
            motor->Gpio_Write(motor->dir_pin1.port, motor->dir_pin1.pin, 0);
            motor->Gpio_Write(motor->dir_pin2.port, motor->dir_pin2.pin, 0);
        }
        if (motor->Pwm_Write != NULL) {
            motor->Pwm_Write(0);
        }
    }
}

/**
 * @brief 获取实时增量数据 (里程计更新)
 */
void Motor_Update_Status(motor_t *motor) {
    if (motor == NULL) return;

    if (motor->Enc_Read != NULL) {
        motor->encoder_speed = motor->Enc_Read();
        motor->total_position += motor->encoder_speed;
    }
}
