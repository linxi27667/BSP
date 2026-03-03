/**
 * @file    bsp_servo.c
 * @brief   舵机核心逻辑实现
 */

#include "bsp_servo.h"

void Servo_Init_Device(servo_t *servo) {
    if (servo == NULL) return;
    //servo->Gpio_Config();
    //servo->Tim_Config(servo->pwm_pin.timer, servo->pwm_pin.channel);

    servo->angle = SERVO_MIN_ANGLE;
    
    // 调用底层初始化时，把绑定的定时器资源传进去
    if (servo->Init != NULL) {
        servo->Init(servo->pwm_pin.timer, servo->pwm_pin.channel); 
    }
}

void Servo_Set_Angle(servo_t *servo, float angle) {
    if (servo == NULL) return;

    // 限幅保护
    if (angle < SERVO_MIN_ANGLE) angle = SERVO_MIN_ANGLE;
    if (angle > SERVO_MAX_ANGLE) angle = SERVO_MAX_ANGLE;
    
    servo->angle = angle;

    // 转换为计数值 (TIM2: Period=20000-1, 计数值范围0-19999)
    // 0.5ms (500) ~ 2.5ms (2500)
    uint16_t pulse = (uint16_t)((angle / 180.0f) * 2000.0f + 500.0f);

    // 下发给绑定的硬件
    if (servo->Set_Pulse != NULL) {
        servo->Set_Pulse(servo->pwm_pin.timer, servo->pwm_pin.channel, pulse);
    }
}
