#ifndef __BSP_SERVO_H__
#define __BSP_SERVO_H__

#define SERVO_GPIO_PIN GPIO_PIN_9
#define SERVO_GPIO_PORT GPIOA

#include "main.h"

typedef struct servo
{
    GPIO_TypeDef* GPIOx;
    uint16_t GPIO_Pin;
    uint32_t Angle;

    void (*Init)(struct servo* my_servo);
    void (*SetAngle)(struct servo* my_servo, uint32_t Angle);
}servo_t;

void Servo_Init(servo_t* my_servo);
void Servo_SetAngle(servo_t* my_servo, uint32_t Angle);

#endif


