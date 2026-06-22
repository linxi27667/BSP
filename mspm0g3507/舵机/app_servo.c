/**
 * @file    app_servo.c
 * @brief   舵机硬件绑定实现（MSPM0G3507）
 */
#include "app_servo.h"
#include "ti_msp_dl_config.h"

/* ================= 1. 硬件底层函数 (HW_ 前缀) ================= */

static void HW_Gpio_Config(void) { }
static void HW_Tim_Config(void) { }

static int8_t HW_Servo_Init(void *timer, uint32_t channel)
{
    if (timer == NULL) return -1;
    DL_TimerG_enableClock((GPTIMER_Regs *)timer);
    DL_TimerG_startCounter((GPTIMER_Regs *)timer);
    return 0;
}

static void HW_Servo_Set_Pulse(void *timer, uint32_t channel, uint16_t pulse)
{
    if (timer == NULL) return;
    DL_TimerG_setCaptureCompareValue((GPTIMER_Regs *)timer, (uint32_t)pulse, (DL_TIMER_CC_INDEX)channel);
}

/* ================= 2. 对象实例化与引脚拼装 ================= */

/* 定时器和通道需根据实际硬件修改 */
servo_t My_Servo_1 = {
    .pwm_pin = { .timer = TIMERG0_INST, .channel = DL_TIMER_CC_0_INDEX },
    .Gpio_Config = HW_Gpio_Config,
    .Tim_Config  = HW_Tim_Config,
    .Init        = HW_Servo_Init,
    .Set_Pulse   = HW_Servo_Set_Pulse
};

/* ================= 3. 对外业务切入点 ================= */

void App_Servo_System_Init(void)
{
    Servo_Init_Device(&My_Servo_1);
    Servo_Set_Angle(&My_Servo_1, 0.0f);
}
