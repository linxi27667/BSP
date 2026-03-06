#ifndef __SW_I2C_H__
#define __SW_I2C_H__

#include "bsp_sw_i2c.h"

// 导出系统级 I2C 总线
extern sw_i2c_t I2C_Bus_1;

void App_I2C_System_Init(void);

#endif /* __SW_I2C_H__ */

