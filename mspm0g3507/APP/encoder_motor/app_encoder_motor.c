#include "app_encoder_motor.h"
#include "main.h"
#include <ti/driverlib/devices/mspm0g3507/dl_timer.h>

static void HW_GPIO_Config(void) { }

static void HW_Timer_Init(void) {
    DL_TimerG_enableClock(TIMERG0_INST);
    DL_TimerG_startCounter(TIMERG0_INST);
}

static void HW_Gpio_Write(void *port, uint16_t pin, uint8_t level) {
    if (level) DL_GPIO_setPins((GPIO_RegDef *)port, pin);
    else DL_GPIO_clearPins((GPIO_RegDef *)port, pin);
}

static void HW_Pwm_Write(void *timer, uint32_t channel, uint32_t duty) {
    if (timer == NULL) return;
    DL_TimerG_setCCValue((TimerG_RegDef *)timer, channel, duty);
}

static int32_t HW_Enc_Read(void) {
    int32_t count = (int32_t)(int16_t)DL_TimerG_getCounterValue(TIMERG1_INST);
    DL_TimerG_setCounterValue(TIMERG1_INST, 0);
    return count;
}

/* 引脚和定时器需根据实际硬件修改 */
motor_t Motor_Left = {
    .dir_pin1    = { .port = GPIOB, .pin = DL_GPIO_PIN_12 },
    .dir_pin2    = { .port = GPIOB, .pin = DL_GPIO_PIN_13 },
    .pwm_timer   = TIMERG0_INST,
    .pwm_channel = DL_TIMER_CC_0_INDEX,
    .Gpio_Config = HW_GPIO_Config,
    .Init        = HW_Timer_Init,
    .Gpio_Write  = HW_Gpio_Write,
    .Pwm_Write   = HW_Pwm_Write,
    .Enc_Read    = HW_Enc_Read
};

void App_Motor_System_Init(void) {
    Motor_Init_Device(&Motor_Left);
}
