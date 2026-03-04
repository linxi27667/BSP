#include "bsp_sw_i2c.h"

/* 内部辅助宏：保持时序代码整洁 */
#define SCL_H(bus)    bus->Pin_Write(bus->scl.port, bus->scl.pin, 1)
#define SCL_L(bus)    bus->Pin_Write(bus->scl.port, bus->scl.pin, 0)
#define SDA_H(bus)    bus->Pin_Write(bus->sda.port, bus->sda.pin, 1)
#define SDA_L(bus)    bus->Pin_Write(bus->sda.port, bus->sda.pin, 0)
#define SDA_READ(bus) bus->Pin_Read(bus->sda.port, bus->sda.pin)
#define I2C_DELAY(bus) bus->Delay_us(2)

/* ================= 内部基础时序动作 ================= */
static void I2C_Start(sw_i2c_t *bus) {
    SDA_H(bus); SCL_H(bus); I2C_DELAY(bus);
    SDA_L(bus); I2C_DELAY(bus);
    SCL_L(bus); I2C_DELAY(bus);
}

static void I2C_Stop(sw_i2c_t *bus) {
    SDA_L(bus); SCL_L(bus); I2C_DELAY(bus);
    SCL_H(bus); I2C_DELAY(bus);
    SDA_H(bus); I2C_DELAY(bus);
}

static uint8_t I2C_Wait_Ack(sw_i2c_t *bus) {
    uint8_t timeout = 0;
    SDA_H(bus); I2C_DELAY(bus); 
    SCL_H(bus); I2C_DELAY(bus);
    
    while (SDA_READ(bus)) {
        timeout++;
        if (timeout > 250) { 
            I2C_Stop(bus); 
            return 1; // 1 表示失败，超时未收到 ACK
        }
    }
    SCL_L(bus); I2C_DELAY(bus);
    return 0; // 0 表示成功收到 ACK
}

static void I2C_Send_Byte(sw_i2c_t *bus, uint8_t data) {
    for (uint8_t i = 0; i < 8; i++) {
        if (data & 0x80) {
            SDA_H(bus);
        } else {
            SDA_L(bus);
        }
        I2C_DELAY(bus);
        SCL_H(bus); I2C_DELAY(bus);
        SCL_L(bus); I2C_DELAY(bus);
        data <<= 1;
    }
}

static uint8_t I2C_Read_Byte(sw_i2c_t *bus, uint8_t ack) {
    uint8_t data = 0;
    SDA_H(bus); 
    
    for (uint8_t i = 0; i < 8; i++) {
        data <<= 1;
        SCL_H(bus); I2C_DELAY(bus);
        if (SDA_READ(bus)) {
            data++;
        }
        SCL_L(bus); I2C_DELAY(bus);
    }
    
    if (ack) {
        SDA_L(bus); // 产生 ACK
    } else {
        SDA_H(bus); // 产生 NACK
    }
    I2C_DELAY(bus);
    SCL_H(bus); I2C_DELAY(bus);
    SCL_L(bus); I2C_DELAY(bus);
    
    return data;
}

/* ================= 暴露给外部的工业级读写 API ================= */
void I2C_Init_Device(sw_i2c_t *bus) {
    if (bus && bus->Init) {
        bus->Init();
    }
}

uint8_t I2C_Write_Reg(sw_i2c_t *bus, uint8_t dev_addr, uint8_t reg_addr, uint8_t *data, uint16_t len) {
    if (!bus) return 1;
    
    I2C_Start(bus);
    
    I2C_Send_Byte(bus, dev_addr << 1);
    if (I2C_Wait_Ack(bus)) { I2C_Stop(bus); return 1; }
    
    I2C_Send_Byte(bus, reg_addr);
    if (I2C_Wait_Ack(bus)) { I2C_Stop(bus); return 1; }
    
    for (uint16_t i = 0; i < len; i++) {
        I2C_Send_Byte(bus, data[i]);
        if (I2C_Wait_Ack(bus)) { I2C_Stop(bus); return 1; }
    }
    
    I2C_Stop(bus);
    return 0;
}

uint8_t I2C_Read_Reg(sw_i2c_t *bus, uint8_t dev_addr, uint8_t reg_addr, uint8_t *data, uint16_t len) {
    if (!bus) return 1;
    
    I2C_Start(bus);
    
    I2C_Send_Byte(bus, dev_addr << 1);
    if (I2C_Wait_Ack(bus)) { I2C_Stop(bus); return 1; }
    
    I2C_Send_Byte(bus, reg_addr);
    if (I2C_Wait_Ack(bus)) { I2C_Stop(bus); return 1; }
    
    I2C_Start(bus); // 重复起始信号
    
    I2C_Send_Byte(bus, (dev_addr << 1) | 1);
    if (I2C_Wait_Ack(bus)) { I2C_Stop(bus); return 1; }
    
    for (uint16_t i = 0; i < len; i++) {
        // 最后一个字节回 NACK(0)，前面回 ACK(1)
        if (i == (len - 1)) {
            data[i] = I2C_Read_Byte(bus, 0); 
        } else {
            data[i] = I2C_Read_Byte(bus, 1); 
        }
    }
    
    I2C_Stop(bus);
    return 0;
}

