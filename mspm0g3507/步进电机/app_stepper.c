/**
 * @file    app_stepper.c
 * @brief   步进电机硬件绑定实现（MSPM0G3507）
 */
#include "app_stepper.h"
#include "ti_msp_dl_config.h"

/* ================= 1. 硬件底层函数 (HW_ 前缀) ================= */

static void HW_Stepper_Init(void) { }

static void HW_Gpio_Write(void *port, uint16_t pin, uint8_t level)
{
    if (level)
        DL_GPIO_setPins((GPIO_Regs *)port, pin);
    else
        DL_GPIO_clearPins((GPIO_Regs *)port, pin);
}

static void HW_Delay_us(uint32_t us)
{
    uint32_t delay = us * (CPUCLK_FREQ / 1000000) / 4;
    while (delay--) __asm("nop");
}

/* ================= 2. 对象实例化与引脚拼装 ================= */

/* DIR/STEP 引脚需根据实际硬件修改 */
stepper_t Stepper_X = {
    .dir_pin  = { .port = GPIOA, .pin = DL_GPIO_PIN_1 },
    .step_pin = { .port = GPIOA, .pin = DL_GPIO_PIN_2 },
    .Init       = HW_Stepper_Init,
    .Gpio_Write = HW_Gpio_Write,
    .Delay_us   = HW_Delay_us
};

/* ================= 3. 对外业务切入点 ================= */

void App_Stepper_System_Init(void)
{
    Stepper_Init_Device(&Stepper_X);
}
