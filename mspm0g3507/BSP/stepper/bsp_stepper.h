#ifndef __BSP_STEPPER_H__
#define __BSP_STEPPER_H__

#include <stdint.h>
#include <stddef.h>

typedef struct {
    void    *port;
    uint16_t pin;
} stepper_gpio_t;

typedef struct stepper_dev {
    stepper_gpio_t dir_pin;
    stepper_gpio_t step_pin;
    void (*Init)(void);
    void (*Gpio_Write)(void *port, uint16_t pin, uint8_t level);
    void (*Delay_us)(uint32_t us);
} stepper_t;

void Stepper_Init_Device(stepper_t *stepper);
void Stepper_Run(stepper_t *stepper, uint8_t dir, uint32_t steps, uint32_t delay_us);

#endif /* __BSP_STEPPER_H__ */
