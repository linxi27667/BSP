/**
 * @file    bsp_servo.h
 * @brief   舵机核心协议层 (完全对象化，跨平台)
 */

#ifndef __BSP_SERVO_H__
#define __BSP_SERVO_H__

#include <stdint.h>
#include <stddef.h>

#define SERVO_MIN_ANGLE    0.0f
#define SERVO_MAX_ANGLE    180.0f

/* ================= 1. 定义抽象硬件资源 ================= */

/**
 * @brief 抽象 PWM 资源对象
 * @note  使用 void* 屏蔽不同单片机的定时器句柄类型
 */
typedef struct {
    void     *timer;    // 定时器基地址/句柄 (应用层自行强转)
    uint32_t channel;   // 定时器通道号
} servo_pwm_t;

/* ================= 2. 核心类定义 ================= */

/**
 * @brief 舵机对象结构体
 */
typedef struct servo_dev {
    /* --- 1. 物理配置 (Config) --- */
    servo_pwm_t pwm_pin;   // 该舵机绑定的 PWM 硬件资源

    /* --- 2. 状态属性 (Status) --- */
    float angle;           // 当前角度

    /* --- 3. 抽象硬件接口 (Methods) --- */
    // 注意：这里的接口直接接收绑定的 timer 和 channel，实现一份代码控制无数个舵机
    void   (*Gpio_Config)(void);                                   // 硬件 GPIO 配置
    void   (*Tim_Config)(void);            // 硬件定时器配置
    int8_t (*Init)(void *timer, uint32_t channel);
    void   (*Set_Pulse)(void *timer, uint32_t channel, uint16_t pulse);
} servo_t;

/* ================= 3. 通用控制 API ================= */
void Servo_Init_Device(servo_t *servo);
void Servo_Set_Angle(servo_t *servo, float angle);

#endif /* __BSP_SERVO_H__ */









