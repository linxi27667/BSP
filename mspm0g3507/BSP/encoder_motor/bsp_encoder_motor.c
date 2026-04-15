#include "bsp_encoder_motor.h"

void Motor_Init_Device(motor_t *motor) {
    if (motor == NULL) return;
    motor->current_pwm = 0;
    motor->encoder_speed = 0;
    motor->total_position = 0;
    if (motor->Init != NULL) motor->Init();
}

void Motor_Set_Speed(motor_t *motor, int32_t speed_val) {
    if (motor == NULL) return;
    motor->current_pwm = speed_val;
    if (speed_val > 0) {
        if (motor->Gpio_Write) {
            motor->Gpio_Write(motor->dir_pin1.port, motor->dir_pin1.pin, 1);
            motor->Gpio_Write(motor->dir_pin2.port, motor->dir_pin2.pin, 0);
        }
        if (motor->Pwm_Write) motor->Pwm_Write(motor->pwm_timer, motor->pwm_channel, (uint32_t)speed_val);
    } else if (speed_val < 0) {
        if (motor->Gpio_Write) {
            motor->Gpio_Write(motor->dir_pin1.port, motor->dir_pin1.pin, 0);
            motor->Gpio_Write(motor->dir_pin2.port, motor->dir_pin2.pin, 1);
        }
        if (motor->Pwm_Write) motor->Pwm_Write(motor->pwm_timer, motor->pwm_channel, (uint32_t)(-speed_val));
    } else {
        if (motor->Gpio_Write) {
            motor->Gpio_Write(motor->dir_pin1.port, motor->dir_pin1.pin, 0);
            motor->Gpio_Write(motor->dir_pin2.port, motor->dir_pin2.pin, 0);
        }
        if (motor->Pwm_Write) motor->Pwm_Write(motor->pwm_timer, motor->pwm_channel, 0);
    }
}

void Motor_Update_Status(motor_t *motor) {
    if (motor == NULL) return;
    if (motor->Enc_Read) {
        motor->encoder_speed = motor->Enc_Read();
        motor->total_position += motor->encoder_speed;
    }
}
