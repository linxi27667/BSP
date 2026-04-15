#include "bsp_servo.h"

void Servo_Init_Device(servo_t *servo) {
    if (servo == NULL) return;
    servo->angle = SERVO_MIN_ANGLE;
    if (servo->Init != NULL) servo->Init(servo->pwm_pin.timer, servo->pwm_pin.channel);
}

void Servo_Set_Angle(servo_t *servo, float angle) {
    if (servo == NULL) return;
    if (angle < SERVO_MIN_ANGLE) angle = SERVO_MIN_ANGLE;
    if (angle > SERVO_MAX_ANGLE) angle = SERVO_MAX_ANGLE;
    servo->angle = angle;
    uint16_t pulse = (uint16_t)((angle / 180.0f) * 2000.0f + 500.0f);
    if (servo->Set_Pulse != NULL) servo->Set_Pulse(servo->pwm_pin.timer, servo->pwm_pin.channel, pulse);
}
