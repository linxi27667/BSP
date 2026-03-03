#include "stepper.h"
#include "main.h"

/* ================= 1. 编写通用的硬件底层函数 (HW_ 前缀) ================= */

/**
 * @brief 手动初始化 GPIO (针对不使用 CubeMX 的情况或额外配置)
 */
static void HW_GPIO_Config(void) {
    // 如果 CubeMX 已经配好了 PA1, PA2 为输出，这里可以留空
}

static void HW_Stepper_Init(void) {
    HW_GPIO_Config();
}

static void HW_Gpio_Write(void* port, uint16_t pin, uint8_t level) {
    HAL_GPIO_WritePin((GPIO_TypeDef*)port, pin, (GPIO_PinState)level);
}

static void HW_Delay_us(uint32_t us) {
    uint32_t delay = us * 10; 
    while (delay--) {
        __NOP();
    }
}

/* ================= 2. 实例化对象并拼装引脚 ================= */

stepper_t Stepper_X = {
    // 绑定物理引脚
    .dir_pin  = {GPIOA, GPIO_PIN_1},
    .step_pin = {GPIOA, GPIO_PIN_2},

    // 绑定硬件方法
    .Init       = HW_Stepper_Init,
    .Gpio_Write = HW_Gpio_Write,
    .Delay_us   = HW_Delay_us
};

/* ================= 3. 提供给 main.c 的统一切入点 ================= */

void App_Stepper_System_Init(void) {
    Stepper_Init_Device(&Stepper_X);
}
