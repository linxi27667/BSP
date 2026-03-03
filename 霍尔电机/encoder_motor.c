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
 * @brief  底层 PWM 设置实现
 */
static void HW_Pwm_Write(uint32_t duty) {
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, duty);
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

    // 2. 硬件方法绑定
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
