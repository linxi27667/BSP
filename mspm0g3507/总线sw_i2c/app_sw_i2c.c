/**
 * @file    app_sw_i2c.c
 * @brief   软件 I2C 总线硬件绑定实现（MSPM0G3507）
 */
#include "app_sw_i2c.h"
#include "ti_msp_dl_config.h"

/* ================= 1. 硬件底层函数 (HW_ 前缀) ================= */

static void HW_Delay_us(uint32_t us)
{
    uint32_t ticks = us * (CPUCLK_FREQ / 1000000) / 4;
    while (ticks--) __asm("nop");
}

static void HW_I2C_Init(void) { }

static void HW_Pin_Write(void *port, uint16_t pin, uint8_t level)
{
    if (level)
        DL_GPIO_setPins((GPIO_Regs *)port, pin);
    else
        DL_GPIO_clearPins((GPIO_Regs *)port, pin);
}

static uint8_t HW_Pin_Read(void *port, uint16_t pin)
{
    return DL_GPIO_readPins((GPIO_Regs *)port, pin) ? 1 : 0;
}

/* ================= 2. 对象实例化与引脚拼装 ================= */

/* SCL/SDA 引脚需根据实际硬件修改 */
sw_i2c_t I2C_Bus_1 = {
    .scl = { .port = GPIOB, .pin = DL_GPIO_PIN_8 },
    .sda = { .port = GPIOB, .pin = DL_GPIO_PIN_9 },
    .Init      = HW_I2C_Init,
    .Pin_Write = HW_Pin_Write,
    .Pin_Read  = HW_Pin_Read,
    .Delay_us  = HW_Delay_us
};

/* ================= 3. 对外业务切入点 ================= */

void App_I2C_System_Init(void)
{
    I2C_Init_Device(&I2C_Bus_1);
}
