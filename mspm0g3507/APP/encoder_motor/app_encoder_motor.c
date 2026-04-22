/**
 * @file    app_encoder_motor.c
 * @brief   霍尔编码器电机硬件绑定实现（MSPM0G3507）
 */
#include "app_encoder_motor.h"
#include "ti_msp_dl_config.h"
#include "my_easylog.h"

/* ================= 1. 硬件底层函数 (HW_ 前缀) ================= */

static void HW_GPIO_Config(void)
{
    /* 方向引脚由 SysConfig 配置为输出 */
}

static void HW_Motor_Init(bsp_motor_t *motor)
{
    if (motor == NULL) return;

    DL_TimerG_enableClock(motor->pwm_timer);
    DL_TimerG_startCounter(motor->pwm_timer);

    DL_TimerG_enableClock(motor->enc_timer);
    DL_TimerG_startCounter(motor->enc_timer);

    motor->Gpio_Config();
}

static void HW_Gpio_Write(void *port, uint32_t pin, uint8_t level)
{
    if (port == NULL) return;
    if (level) {
        DL_GPIO_setPins((GPIO_Regs *)port, pin);
    } else {
        DL_GPIO_clearPins((GPIO_Regs *)port, pin);
    }
}

static void HW_Pwm_Write(void *timer, uint32_t channel, uint32_t duty)
{
    if (timer == NULL) return;
    DL_TimerG_setCaptureCompareValue((GPTIMER_Regs *)timer, duty, (DL_TIMER_CC_INDEX)channel);
}

static int32_t HW_Enc_Read(void *enc_timer)
{
    static uint32_t last_count = 0;
    static bool first_read = true;

    uint32_t current_count = DL_Timer_getTimerCount((GPTIMER_Regs *)enc_timer) & 0xFFFF;

    if (first_read) {
        last_count = current_count;
        first_read = false;
        //log_i("DEBUG", "First: cur=%u", current_count);
        return 0;
    }

    int16_t delta = (int16_t)(last_count - current_count);
    last_count = current_count;
    return (int32_t)delta;
}

/* ================= 2. 对象实例化与引脚拼装 ================= */

bsp_motor_t App_Motor_Left = {
    .dir_pin1   = {MOTOR_LEFT_DIR1_PORT, MOTOR_LEFT_DIR1_PIN},
    .dir_pin2   = {MOTOR_LEFT_DIR2_PORT, MOTOR_LEFT_DIR2_PIN},
    .pwm_timer  = MOTOR_LEFT_PWM_TIMER,
    .pwm_channel = MOTOR_LEFT_PWM_CHANNEL,
    .enc_timer  = MOTOR_LEFT_ENC_TIMER,

    .Gpio_Config = HW_GPIO_Config,
    .Init        = HW_Motor_Init,
    .Gpio_Write  = HW_Gpio_Write,
    .Pwm_Write   = HW_Pwm_Write,
    .Enc_Read    = HW_Enc_Read
};

/* ================= 3. 对外业务切入点 ================= */

void App_Motor_System_Init(void)
{
    HW_Motor_Init(&App_Motor_Left);
    BSP_Motor_Init_Device(&App_Motor_Left);
}

void App_Motor_Set_Speed(int32_t speed)
{
    BSP_Motor_Set_Speed(&App_Motor_Left, speed);
}

void App_Motor_Forward(int32_t speed)
{
    BSP_Motor_Set_Speed(&App_Motor_Left, speed);
}

void App_Motor_Backward(int32_t speed)
{
    BSP_Motor_Set_Speed(&App_Motor_Left, -speed);
}

void App_Motor_Stop(void)
{
    BSP_Motor_Set_Speed(&App_Motor_Left, 0);
}

void App_Motor_Update_Status(void)
{
    BSP_Motor_Update_Status(&App_Motor_Left);
}
