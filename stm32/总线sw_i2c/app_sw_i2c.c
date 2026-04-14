#include "app_sw_i2c.h"
#include "main.h"

static void Delay_us(uint32_t us){
    // SystemCoreClock 是 HAL 库自带的全局变量，代表当前的 CPU 频率 (比如 80000000 或 168000000)
    // 除以 1000000 得到每微秒的 CPU 周期数，再除以 4 (因为 while 循环大概需要 4 个时钟周期)
    uint32_t ticks = us * (SystemCoreClock / 1000000) / 4; 
    
    while (ticks--) {
        __NOP(); // __NOP() 是空指令，防止这个循环被编译器(如 -O2)自作聪明地优化掉
    }
}

/* ================= 硬件操作函数 ================= */
static void HW_I2C_Init(void) {
    // 假设已在 CubeMX 中将 PB8 和 PB9 配置为开漏输出(Open-Drain)
}

static void HW_Pin_Write(void* port, uint16_t pin, uint8_t level) {
    if (port) {
        HAL_GPIO_WritePin((GPIO_TypeDef *)port, pin, (GPIO_PinState)level);
    }
}

static uint8_t HW_Pin_Read(void* port, uint16_t pin) {
    if (port) {
        return (uint8_t)HAL_GPIO_ReadPin((GPIO_TypeDef *)port, pin);
    }
    return 0;
}

static void HW_Delay_us(uint32_t us) {
    Delay_us(us);
}

/* ================= 实例化总线对象 ================= */
sw_i2c_t I2C_Bus_1 = {
    .scl = {GPIOB, GPIO_PIN_8}, // 替换为你的 SCL 引脚
    .sda = {GPIOB, GPIO_PIN_9}, // 替换为你的 SDA 引脚

    .Init      = HW_I2C_Init,
    .Pin_Write = HW_Pin_Write,
    .Pin_Read  = HW_Pin_Read,
    .Delay_us  = HW_Delay_us
};

void App_I2C_System_Init(void) {
    I2C_Init_Device(&I2C_Bus_1);
}
