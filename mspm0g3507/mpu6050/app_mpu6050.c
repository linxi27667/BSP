/**
 * @file    app_mpu6050.c
 * @brief   MPU6050 硬件绑定实现（MSPM0G3507）
 */
#include "app_mpu6050.h"
#include "app_sw_i2c.h"
#include "ti_msp_dl_config.h"

/* ================= 1. 硬件底层函数 (HW_ 前缀) ================= */

static void HW_Delay_ms(uint32_t ms)
{
    volatile uint32_t i;
    for (uint32_t m = 0; m < ms; m++)
        for (i = 0; i < (CPUCLK_FREQ / 1000 / 4); i++)
            __asm("nop");
}

/* ================= 2. 对象实例化与引脚拼装 ================= */

mpu_t my_mpu = {
    .bus      = &I2C_Bus_1,
    .dev_addr = 0x68,
    .Delay_ms = HW_Delay_ms
};

/* ================= 3. 对外业务切入点 ================= */

void App_MPU6050_System_Init(void)
{
    MPU6050_Init_Device(&my_mpu);
}
