#include "app_encoder_motor.h"
#include "main.h"
#include <ti/driverlib/devices/mspm0g3507/dl_timer.h>

/* ================= 1. 硬件底层函数 (HW_ 前缀) ================= */
static void HW_GPIO_Config(void) { }

static void HW_Motor_Init(motor_t *motor) {
    if (motor == NULL) return;
    /* 使能时钟 - 通过结构体字段，换对象自动切换 */
    DL_TimerG_enableClock(motor->pwm_timer);
    DL_TimerG_enableClock(motor->enc_timer);
    /* PWM 定时器初始化 - 配置周期、预分频、通道 */
    /* 编码器定时器初始化 - 配置编码器模式 */
    /* 调用 GPIO 配置 */
    motor->Gpio_Config();
}

static void HW_Gpio_Write(void *port, uint16_t pin, uint8_t level) {
    if (level) DL_GPIO_setPins((GPIO_RegDef *)port, pin);
    else DL_GPIO_clearPins((GPIO_RegDef *)port, pin);
}

static void HW_Pwm_Write(void *timer, uint32_t channel, uint32_t duty) {
    if (timer == NULL) return;
    DL_TimerG_setCCValue((TimerG_RegDef *)timer, channel, duty);
}

static int32_t HW_Enc_Read(void *enc_timer) {
    int32_t count = (int32_t)(int16_t)DL_TimerG_getCounterValue((TimerG_RegDef *)enc_timer);
    DL_TimerG_setCounterValue((TimerG_RegDef *)enc_timer, 0);
    return count;
}

/* ================= 2. 对象实例化与引脚拼装 ================= */
motor_t Motor_Left = {
    .dir_pin1    = { .port = MOTOR_LEFT_DIR1_PORT, .pin = MOTOR_LEFT_DIR1_PIN },
    .dir_pin2    = { .port = MOTOR_LEFT_DIR2_PORT, .pin = MOTOR_LEFT_DIR2_PIN },
    .pwm_timer   = MOTOR_LEFT_PWM_TIMER,
    .pwm_channel = MOTOR_LEFT_PWM_CHANNEL,
    .enc_timer   = MOTOR_LEFT_ENC_TIMER,
    .Gpio_Config = HW_GPIO_Config,
    .Init        = HW_Motor_Init,
    .Gpio_Write  = HW_Gpio_Write,
    .Pwm_Write   = HW_Pwm_Write,
    .Enc_Read    = HW_Enc_Read
};

/* ================= 3. 对外业务/功能切入点 ================= */
void App_Motor_System_Init(void) {
    HW_Motor_Init(&Motor_Left);
    Motor_Init_Device(&Motor_Left);
}
