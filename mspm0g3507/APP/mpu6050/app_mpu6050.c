#include "app_mpu6050.h"
#include "app_sw_i2c.h"
#include "main.h"

static void HW_Delay_ms(uint32_t ms) {
    volatile uint32_t i;
    for (uint32_t m = 0; m < ms; m++)
        for (i = 0; i < (CPUCLK_FREQ / 1000 / 4); i++)
            __asm("nop");
}

mpu_t my_mpu = {
    .bus      = &I2C_Bus_1,
    .dev_addr = 0x68,
    .Delay_ms = HW_Delay_ms
};

void App_MPU6050_System_Init(void) {
    MPU6050_Init_Device(&my_mpu);
}
