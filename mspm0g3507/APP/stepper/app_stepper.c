#include "app_stepper.h"
#include "main.h"

static void HW_Stepper_Init(void) { }

static void HW_Gpio_Write(void *port, uint16_t pin, uint8_t level) {
    if (level) DL_GPIO_setPins((GPIO_RegDef *)port, pin);
    else DL_GPIO_clearPins((GPIO_RegDef *)port, pin);
}

static void HW_Delay_us(uint32_t us) {
    uint32_t delay = us * (CPUCLK_FREQ / 1000000) / 4;
    while (delay--) __asm("nop");
}

/* DIR/STEP 引脚需根据实际硬件修改 */
stepper_t Stepper_X = {
    .dir_pin  = { .port = GPIOA, .pin = DL_GPIO_PIN_1 },
    .step_pin = { .port = GPIOA, .pin = DL_GPIO_PIN_2 },
    .Init       = HW_Stepper_Init,
    .Gpio_Write = HW_Gpio_Write,
    .Delay_us   = HW_Delay_us
};

void App_Stepper_System_Init(void) {
    Stepper_Init_Device(&Stepper_X);
}
