#ifndef __BSP_SW_I2C_H__
#define __BSP_SW_I2C_H__

#include <stdint.h>
#include <stddef.h>

typedef struct {
    void    *port;
    uint16_t pin;
} i2c_gpio_t;

typedef struct sw_i2c_dev {
    i2c_gpio_t scl;
    i2c_gpio_t sda;

    void    (*Init)(void);
    void    (*Pin_Write)(void *port, uint16_t pin, uint8_t level);
    uint8_t (*Pin_Read)(void *port, uint16_t pin);
    void    (*Delay_us)(uint32_t us);
} sw_i2c_t;

void I2C_Init_Device(sw_i2c_t *bus);
uint8_t I2C_Write_Reg(sw_i2c_t *bus, uint8_t dev_addr, uint8_t reg_addr, uint8_t *data, uint16_t len);
uint8_t I2C_Read_Reg(sw_i2c_t *bus, uint8_t dev_addr, uint8_t reg_addr, uint8_t *data, uint16_t len);

#endif /* __BSP_SW_I2C_H__ */
