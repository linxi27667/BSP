#include "mpu6050.h"
#include "sw_i2c.h" // 获取 I2C_Bus_1
#include "main.h"

static void HW_Delay_ms(uint32_t ms) {
    HAL_Delay(ms); 
}

/* ================= 实例化并依赖注入 ================= */
mpu_t my_mpu = {
    .bus      = &I2C_Bus_1,  // 将写好的 I2C 总线挂载进来
    .dev_addr = 0x68,        // 如果你的模块 AD0 接 3.3V，请改为 0x69
    .Delay_ms = HW_Delay_ms
};

void App_MPU6050_System_Init(void) {
    MPU6050_Init_Device(&my_mpu);
}
