#ifndef __BSP_ENCODER_MOTOR_H__
#define __BSP_ENCODER_MOTOR_H__

#include <stdint.h>
#include <stddef.h>

typedef struct {
    void     *port;
    uint16_t  pin;
} motor_gpio_t;

typedef enum {
    MOTOR_DIR_STOP = 0,
    MOTOR_DIR_FORWARD,
    MOTOR_DIR_REVERSE
} motor_dir_t;

typedef struct motor_dev {
    motor_gpio_t dir_pin1;
    motor_gpio_t dir_pin2;
    void     *pwm_timer;
    uint32_t  pwm_channel;
    int32_t current_pwm;
    int32_t encoder_speed;
    int32_t total_position;
    void    (*Gpio_Config)(void);
    void    (*Init)(void);
    void    (*Gpio_Write)(void *port, uint16_t pin, uint8_t level);
    void    (*Pwm_Write)(void *timer, uint32_t channel, uint32_t duty);
    int32_t (*Enc_Read)(void);
} motor_t;

void Motor_Init_Device(motor_t *motor);
void Motor_Set_Speed(motor_t *motor, int32_t speed_val);
void Motor_Update_Status(motor_t *motor);

#endif /* __BSP_ENCODER_MOTOR_H__ */
