#ifndef __BSP_SW_I2C_H__
#define __BSP_SW_I2C_H__

#include <stdint.h>
#include <stddef.h>

/* --- 1. 抽象 GPIO 泛型 --- */
typedef struct {
    void* port;
    uint16_t pin;
} i2c_gpio_t;

/* --- 2. 软件 I2C 对象类 --- */
typedef struct sw_i2c_dev {
    // 物理引脚属性
    i2c_gpio_t scl;
    i2c_gpio_t sda;

    // 硬件底层操作方法指针
    void    (*Init)(void);
    void    (*Pin_Write)(void* port, uint16_t pin, uint8_t level);
    uint8_t (*Pin_Read)(void* port, uint16_t pin);
    void    (*Delay_us)(uint32_t us);
} sw_i2c_t;

/* --- 3. 对外暴露的高级 API --- */
void I2C_Init_Device(sw_i2c_t *bus);
uint8_t I2C_Write_Reg(sw_i2c_t *bus, uint8_t dev_addr, uint8_t reg_addr, uint8_t *data, uint16_t len);
uint8_t I2C_Read_Reg(sw_i2c_t *bus, uint8_t dev_addr, uint8_t reg_addr, uint8_t *data, uint16_t len);

#endif /* __BSP_SW_I2C_H__ */



