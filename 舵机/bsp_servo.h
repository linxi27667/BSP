#ifndef __BSP_SERVO_H__
#define __BSP_SERVO_H__

#include "main.h"

#define SERVO_TIM          &htim2
#define SERVO_CHANNEL      TIM_CHANNEL_1

#define SERVO_MIN_ANGLE    0
#define SERVO_MAX_ANGLE    180

typedef struct servo
{
    TIM_HandleTypeDef *htim;
    uint32_t channel;
    float angle;
}servo_t;

void Servo_Init(servo_t* my_servo);
void Servo_SetAngle(servo_t* my_servo, float angle);

extern TIM_HandleTypeDef htim2;

#endif


