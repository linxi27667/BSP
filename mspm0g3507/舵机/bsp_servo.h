#ifndef __BSP_SERVO_H__
#define __BSP_SERVO_H__

#include <stdint.h>
#include <stddef.h>

#define SERVO_MIN_ANGLE    0.0f
#define SERVO_MAX_ANGLE    180.0f

typedef struct {
    void     *timer;
    uint32_t  channel;
} servo_pwm_t;

typedef struct servo_dev {
    servo_pwm_t pwm_pin;
    float angle;
    void   (*Gpio_Config)(void);
    void   (*Tim_Config)(void);
    int8_t (*Init)(void *timer, uint32_t channel);
    void   (*Set_Pulse)(void *timer, uint32_t channel, uint16_t pulse);
} servo_t;

void Servo_Init_Device(servo_t *servo);
void Servo_Set_Angle(servo_t *servo, float angle);

#endif /* __BSP_SERVO_H__ */
