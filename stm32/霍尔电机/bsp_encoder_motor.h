/**
 * @file    bsp_encoder_motor.h
 * @brief   电机驱动核心框架层 (跨平台，纯C语言面向对象实现)
 * @note    此文件定义了电机类的所有属性和底层抽象接口。
 * 【铁律】严禁在此文件包含任何单片机特有的库文件 (如 main.h, stm32f4xx.h)。
 */

#ifndef __BSP_ENCODER_MOTOR_H__
#define __BSP_ENCODER_MOTOR_H__

#include <stdint.h>
#include <stddef.h> // 提供 NULL 宏定义

/* ================= 1. 基础数据类型与枚举 ================= */

/**
 * @brief 抽象 GPIO 引脚对象
 * @note  使用 void* 屏蔽不同芯片的端口类型差异 (如 STM32 的 GPIO_TypeDef*)
 */
typedef struct {
    void     *port;     // 端口基地址指针 (应用层自行强转)
    uint16_t pin;       // 引脚号
} motor_gpio_t;

/**
 * @brief 电机运行方向枚举
 */
typedef enum {
    MOTOR_DIR_STOP = 0,     // 停止/刹车
    MOTOR_DIR_FORWARD,      // 正转
    MOTOR_DIR_REVERSE       // 反转
} motor_dir_t;

/* ================= 2. 核心类定义 (Class) ================= */

/**
 * @brief 霍尔编码器电机对象 (Object)
 */
typedef struct motor_dev {
    /* --- 1. 物理配置 (Config) --- */
    motor_gpio_t dir_pin1;   // 方向控制引脚 1
    motor_gpio_t dir_pin2;   // 方向控制引脚 2
    void     *pwm_timer;     // PWM 定时器句柄
    uint32_t  pwm_channel;   // PWM 通道号

    /* --- 2. 运行状态 (Status) --- */
    int32_t current_pwm;     // 当前设定的 PWM 值 (带符号)
    int32_t encoder_speed;   // 实时速度 (当前周期脉冲增量)
    int32_t total_position;  // 累计运行里程 (积分位置)

    /* --- 3. 抽象硬件操作方法 (Methods / Function Pointers) --- */
    // 这些“空壳函数”必须在应用层实例化时绑定真实的硬件代码
    void    (*Gpio_Config)(void);                                   // 硬件 GPIO 配置
    void    (*Init)(void);                                          // 硬件外设初始化
    void    (*Gpio_Write)(void *port, uint16_t pin, uint8_t level); // 抽象 GPIO 写操作
    void    (*Pwm_Write)(void *timer, uint32_t channel, uint32_t duty); // 抽象 PWM 写操作 (占空比正数)
    int32_t (*Enc_Read)(void);                                      // 抽象编码器读取 (读取后需清零)
} motor_t;

/* ================= 3. 对外暴露的控制 API ================= */

void Motor_Init_Device(motor_t *motor);
void Motor_Set_Speed(motor_t *motor, int32_t speed_val);
void Motor_Update_Status(motor_t *motor);

#endif /* __BSP_ENCODER_MOTOR_H__ */
