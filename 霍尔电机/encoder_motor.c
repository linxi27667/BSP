/**
 * @file    encoder_motor.c
 * @brief   电机底层硬件绑定代码 (适配当前 MCU 和 HAL 库)
 * @note    此文件是将虚拟的 "motor_t" 对象与真实的物理芯片联系起来的桥梁。
 */

#include "main.h" // 【唯一解禁区】整个库只有这里可以包含底层硬件头文件！
#include "encoder_motor.h"

/* 引入 CubeMX 生成的定时器句柄 */
extern TIM_HandleTypeDef htim1;
extern TIM_HandleTypeDef htim2;

/* ================= 1. 编写通用的硬件底层函数 (HW_ 前缀) ================= */
/**
 * @brief  硬件IO口配置
 */
static void HW_GPIO_Config(void) {
    /* 如果是 ESP32，这里就写 gpio_config_t 逻辑 */
    /* 如果是 STM32 且没用 CubeMX，这里写 GPIO_InitTypeDef 逻辑 */
    
    // 示范：即使是用 CubeMX，也可以在这里统一处理电机驱动的 STBY 引脚
    // HAL_GPIO_WritePin(GPIOA, GPIO_PIN_8, GPIO_PIN_SET); 
}

/**
 * @brief  硬件定时器启动
 */
static void HW_Timer_Init(void) {
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
		__HAL_TIM_MOE_ENABLE(&htim1);
    HAL_TIM_Encoder_Start(&htim2, TIM_CHANNEL_ALL);
}

/**
 * @brief  通用 GPIO 写接口实现
 * @param  port: 端口基地址 (在 BSP 层是 void*，在这里强制转回 GPIO_TypeDef*)
 * @param  pin:  引脚号
 * @param  level: 电平状态 (1高 0低)
 */
static void HW_Gpio_Write(void *port, uint16_t pin, uint8_t level) {
    if (port == NULL) return;
    HAL_GPIO_WritePin((GPIO_TypeDef *)port, pin, (GPIO_PinState)level);
}

/**
 * @brief  底层PWM设置实现
 * @param  timer: 定时器句柄指针
 * @param  channel: 定时器通道号
 * @param  duty: PWM占空比值
 */
static void HW_Pwm_Write(void *timer, uint32_t channel, uint32_t duty) {
    if (timer == NULL) return;
    __HAL_TIM_SET_COMPARE((TIM_HandleTypeDef *)timer, channel, duty);
}

/**
 * @brief  底层编码器读取实现
 */
static int32_t HW_Enc_Read(void) {
    int32_t count = (short)__HAL_TIM_GET_COUNTER(&htim2);
    __HAL_TIM_SET_COUNTER(&htim2, 0); // 读后清零，获取增量
    return count;
}

/* ================= 2. 实例化对象并拼装引脚 (面向对象高潮部分) ================= */

/**
 * @brief 左侧电机实例化配置
 * @note  在这里像填表格一样，把对应的引脚和写好的通用接口“挂载”上去！
 */
motor_t Motor_Left = {
    // 1. 物理引脚配置 (再也不需要去代码里硬找引脚了)
    .dir_pin1 = {GPIOB, GPIO_PIN_12}, 
    .dir_pin2 = {GPIOB, GPIO_PIN_13},
    .pwm_timer = &htim1,
    .pwm_channel = TIM_CHANNEL_1,

    // 2. 硬件方法绑定
    .Gpio_Config = HW_Gpio_Config,
    .Init       = HW_Timer_Init,
    .Gpio_Write = HW_Gpio_Write,
    .Pwm_Write  = HW_Pwm_Write,
    .Enc_Read   = HW_Enc_Read
};

/* ================= 3. 提供给 main.c 的统一切入点 ================= */

/**
 * @brief 初始化整个应用层的电机系统
 */
void App_Motor_System_Init(void) {
    Motor_Init_Device(&Motor_Left);
    // 如果有 Motor_Right, 继续在这里调用 Motor_Init_Device(&Motor_Right);
}
