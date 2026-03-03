#include "bsp_servo.h"

void Servo_Init(servo_t *my_servo)
{
    if (my_servo == NULL)
    {
        return;
    }

    my_servo->htim = SERVO_TIM;
    my_servo->channel = SERVO_CHANNEL;
    my_servo->angle = SERVO_MIN_ANGLE;

    HAL_StatusTypeDef status = HAL_TIM_PWM_Start(my_servo->htim, my_servo->channel);
		
		if (status != HAL_OK)
		{
			elog_e("Servo", "Init Error");
		}
}

void Servo_SetAngle(servo_t *my_servo, float angle)
{
    if (my_servo == NULL || my_servo->htim == NULL)
    {
        return;
    }

    my_servo->angle = angle;
    uint16_t pulse = (uint16_t)(angle / 180 * 2000 + 500);
    __HAL_TIM_SET_COMPARE(my_servo->htim, my_servo->channel, pulse);
}

