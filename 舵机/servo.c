/**
 * @file    servo.c
 * @brief   舵机硬件底层绑定代码
 */

#include "servo.h"
#include "main.h"

/* 声明外部的定时器句柄 */
extern TIM_HandleTypeDef htim2;

/* ================= 1. 编写通用的硬件底层函数 (HW_ 前缀) ================= */
// 【精髓】：这两个函数现在是通用的！无论是 htim2 还是 htim3，通道 1 还是通道 4，都共用这段代码！
/**
 * @brief  硬件GPIO配置
 * @note   此函数用于配置舵机PWM输出的GPIO引脚
 *         暂时为空，等待CubeMX生成代码
 */
static void HW_Gpio_Config(void){


}

/**
 * @brief  硬件定时器配置
 * @note   此函数用于配置舵机PWM输出的定时器
 *         暂时为空，等待CubeMX生成代码
 */
static void HW_Tim_Config(void){


}

/**
 * @brief  舵机硬件初始化
 * @param  timer: 定时器句柄指针
 * @param  channel: 定时器通道号
 * @return 0: 成功, -1: 失败
 */
static int8_t HW_Servo_Init(void *timer, uint32_t channel) {
    if (timer == NULL) return -1;
    // 把 void* 强制转回 STM32 认识的 TIM_HandleTypeDef*
    HAL_StatusTypeDef status = HAL_TIM_PWM_Start((TIM_HandleTypeDef *)timer, channel);
    if (status != HAL_OK) return -1;
    return 0;
}

/**
 * @brief  设置舵机PWM脉冲宽度
 * @param  timer: 定时器句柄指针
 * @param  channel: 定时器通道号
 * @param  pulse: 脉冲宽度值
 */
static void HW_Servo_Set_Pulse(void *timer, uint32_t channel, uint16_t pulse) {
    if (timer == NULL) return;
    // 使用宏定义直接设置 CCR 寄存器
    __HAL_TIM_SET_COMPARE((TIM_HandleTypeDef *)timer, channel, pulse);
}

/* ================= 2. 实例化对象并拼装硬件资源 ================= */

servo_t My_Servo_1 = {
    // 1. 物理资源绑定：像查字典一样把定时器和通道填进去
    .pwm_pin = {&htim2, TIM_CHANNEL_1},

    // 2. 硬件方法绑定：挂载通用的 HW_ 函数
    .Gpio_Config = HW_Gpio_Config,
    .Tim_Config = HW_Tim_Config,
    .Init      = HW_Servo_Init,
    .Set_Pulse = HW_Servo_Set_Pulse
};

// 如果有第二个舵机，只需要复制粘贴，改一下资源，无需多写一行底层的初始化代码！
/*
servo_t My_Servo_2 = {
    .pwm_pin   = {&htim2, TIM_CHANNEL_2},
    .Init      = HW_Servo_Init,
    .Set_Pulse = HW_Servo_Set_Pulse
};
*/

/* ================= 3. 提供给 main.c 的统一切入点 ================= */

/**
 * @brief  应用层舵机系统初始化
 * @note   此函数是提供给main.c的统一切入点
 *         初始化所有舵机设备并设置初始角度
 */  
void App_Servo_System_Init(void) {
    Servo_Init_Device(&My_Servo_1);
    Servo_Set_Angle(&My_Servo_1, 0.0f); 
}
