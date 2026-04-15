#ifndef __BSP_MPU6050_H__
#define __BSP_MPU6050_H__

#include "bsp_sw_i2c.h"

#define MPU_SMPLRT_DIV_REG      0x19
#define MPU_CONFIG_REG          0x1A
#define MPU_GYRO_CONFIG_REG     0x1B
#define MPU_ACCEL_CONFIG_REG    0x1C
#define MPU_ACCEL_XOUT_H_REG    0x3B
#define MPU_PWR_MGMT_1_REG      0x6B
#define MPU_WHO_AM_I_REG        0x75

typedef struct mpu_dev {
    sw_i2c_t *bus;
    uint8_t   dev_addr;
    float accel_x, accel_y, accel_z;
    float gyro_x, gyro_y, gyro_z;
    float temp;
    void (*Delay_ms)(uint32_t ms);
} mpu_t;

uint8_t MPU6050_Init_Device(mpu_t *mpu);
void MPU6050_Read_Data(mpu_t *mpu);

#endif /* __BSP_MPU6050_H__ */
