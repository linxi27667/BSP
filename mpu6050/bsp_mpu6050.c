#include "bsp_mpu6050.h"

uint8_t MPU6050_Init_Device(mpu_t *mpu) {
    if (mpu == NULL || mpu->bus == NULL) return 1;

    uint8_t check_id = 0;
    uint8_t write_data = 0;

    // 1. 验证设备
    I2C_Read_Reg(mpu->bus, mpu->dev_addr, MPU_WHO_AM_I_REG, &check_id, 1);
    if (check_id != 0x68 && check_id != 0x71) {
        return 1; 
    }

    // 2. 解除睡眠模式
    write_data = 0x00;
    I2C_Write_Reg(mpu->bus, mpu->dev_addr, MPU_PWR_MGMT_1_REG, &write_data, 1);
    
    if (mpu->Delay_ms) {
        mpu->Delay_ms(50); // 给点时间唤醒
    }

    // 3. 配置采样率 (125Hz)
    write_data = 0x07; 
    I2C_Write_Reg(mpu->bus, mpu->dev_addr, MPU_SMPLRT_DIV_REG, &write_data, 1);
    
    // 4. 配置低通滤波
    write_data = 0x06; 
    I2C_Write_Reg(mpu->bus, mpu->dev_addr, MPU_CONFIG_REG, &write_data, 1);

    // 5. 配置加速度量程 (±2g)
    write_data = 0x00; 
    I2C_Write_Reg(mpu->bus, mpu->dev_addr, MPU_ACCEL_CONFIG_REG, &write_data, 1);
    
    // 6. 配置陀螺仪量程 (±2000°/s)
    write_data = 0x18; 
    I2C_Write_Reg(mpu->bus, mpu->dev_addr, MPU_GYRO_CONFIG_REG, &write_data, 1);

    return 0; 
}

void MPU6050_Read_Data(mpu_t *mpu) {
    if (mpu == NULL || mpu->bus == NULL) return;

    uint8_t raw[14];
    
    // 连读 14 个字节
    if (I2C_Read_Reg(mpu->bus, mpu->dev_addr, MPU_ACCEL_XOUT_H_REG, raw, 14) != 0) {
        return; // 读取失败则不更新数据
    }

    // 拼接 16 位有符号整型
    int16_t ax = (raw[0] << 8) | raw[1];
    int16_t ay = (raw[2] << 8) | raw[3];
    int16_t az = (raw[4] << 8) | raw[5];
    int16_t temp = (raw[6] << 8) | raw[7];
    int16_t gx = (raw[8] << 8) | raw[9];
    int16_t gy = (raw[10] << 8) | raw[11];
    int16_t gz = (raw[12] << 8) | raw[13];

    // 转化为真实浮点物理量
    mpu->accel_x = (float)ax / 16384.0f;
    mpu->accel_y = (float)ay / 16384.0f;
    mpu->accel_z = (float)az / 16384.0f;
    
    mpu->temp    = 36.53f + ((float)temp / 340.0f);
    
    mpu->gyro_x  = (float)gx / 16.4f;
    mpu->gyro_y  = (float)gy / 16.4f;
    mpu->gyro_z  = (float)gz / 16.4f;
}

