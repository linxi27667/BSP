#include "app_servo.h"
#include "main.h"
#include <ti/driverlib/devices/mspm0g3507/dl_timer.h>

static void HW_Gpio_Config(void) { }
static void HW_Tim_Config(void) { }

static int8_t HW_Servo_Init(void *timer, uint32_t channel) {
    if (timer == NULL) return -1;
    DL_TimerG_enableClock((TimerG_RegDef *)timer);
    DL_TimerG_startCounter((TimerG_RegDef *)timer);
    return 0;
}

static void HW_Servo_Set_Pulse(void *timer, uint32_t channel, uint16_t pulse) {
    if (timer == NULL) return;
    DL_TimerG_setCCValue((TimerG_RegDef *)timer, channel, (uint32_t)pulse);
}

/* 定时器和通道需根据实际硬件修改 */
servo_t My_Servo_1 = {
    .pwm_pin = { .timer = TIMERG0_INST, .channel = DL_TIMER_CC_0_INDEX },
    .Gpio_Config = HW_Gpio_Config,
    .Tim_Config  = HW_Tim_Config,
    .Init        = HW_Servo_Init,
    .Set_Pulse   = HW_Servo_Set_Pulse
};

void App_Servo_System_Init(void) {
    Servo_Init_Device(&My_Servo_1);
    Servo_Set_Angle(&My_Servo_1, 0.0f);
}
