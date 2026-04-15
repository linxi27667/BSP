#include "app_sw_i2c.h"
#include "main.h"

static void HW_Delay_us(uint32_t us) {
    uint32_t ticks = us * (CPUCLK_FREQ / 1000000) / 4;
    while (ticks--) __asm("nop");
}

static void HW_I2C_Init(void) { }

static void HW_Pin_Write(void *port, uint16_t pin, uint8_t level) {
    if (level) DL_GPIO_setPins((GPIO_RegDef *)port, pin);
    else DL_GPIO_clearPins((GPIO_RegDef *)port, pin);
}

static uint8_t HW_Pin_Read(void *port, uint16_t pin) {
    return DL_GPIO_readPins((GPIO_RegDef *)port, pin) ? 1 : 0;
}

/* SCL/SDA 引脚需根据实际硬件修改 */
sw_i2c_t I2C_Bus_1 = {
    .scl = { .port = GPIOB, .pin = DL_GPIO_PIN_8 },
    .sda = { .port = GPIOB, .pin = DL_GPIO_PIN_9 },
    .Init      = HW_I2C_Init,
    .Pin_Write = HW_Pin_Write,
    .Pin_Read  = HW_Pin_Read,
    .Delay_us  = HW_Delay_us
};

void App_I2C_System_Init(void) {
    I2C_Init_Device(&I2C_Bus_1);
}
