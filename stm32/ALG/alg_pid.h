/**
 * @file    alg_pid.h
 * @brief   PID 控制算法核心 (位置式 + 增量式，跨平台纯 C)
 * @note    适用于电机速度/位置闭环、温度控制等场景
 */

#ifndef __ALG_PID_H__
#define __ALG_PID_H__

#include <stdint.h>

/* ================= 1. PID 结构体与枚举 ================= */

/**
 * @brief PID 控制器对象
 */
typedef struct {
    /* --- 参数 --- */
    float kp;           // 比例系数
    float ki;           // 积分系数
    float kd;           // 微分系数

    /* --- 状态 --- */
    float error;        // 当前误差
    float error_last;   // 上一次误差
    float error_ll;     // 上上次误差 (增量式需要)
    float integral;     // 积分累积值

    /* --- 限幅 --- */
    float output_max;   // 输出最大值
    float output_min;   // 输出最小值
    float integral_max; // 积分限幅上限 (抗饱和)
    float integral_min; // 积分限幅下限
} pid_t;

/**
 * @brief PID 控制器模式
 */
typedef enum {
    PID_TYPE_POSITION = 0,  // 位置式 PID (适合舵机角度、温度等)
    PID_TYPE_INCREMENT      // 增量式 PID (适合电机速度、步进控制)
} pid_type_t;

/* ================= 2. API ================= */

void Pid_Init(pid_t *pid, float kp, float ki, float kd, float out_max, float out_min);
float Pid_Position_Calc(pid_t *pid, float target, float actual);
float Pid_Increment_Calc(pid_t *pid, float target, float actual);
void Pid_Reset(pid_t *pid);

#endif /* __ALG_PID_H__ */
