/**
 * @file    alg_pid.c
 * @brief   PID 控制器实现 (位置式 + 增量式)
 */

#include "alg_pid.h"

/* ================= 1. 初始化 ================= */

void Pid_Init(pid_t *pid, float kp, float ki, float kd, float out_max, float out_min)
{
    pid->kp          = kp;
    pid->ki          = ki;
    pid->kd          = kd;
    pid->output_max  = out_max;
    pid->output_min  = out_min;
    pid->integral_max = out_max * 0.6f;
    pid->integral_min = out_min * 0.6f;
    Pid_Reset(pid);
}

void Pid_Reset(pid_t *pid)
{
    pid->error      = 0.0f;
    pid->error_last = 0.0f;
    pid->error_ll   = 0.0f;
    pid->integral   = 0.0f;
}

/* ================= 2. 位置式 PID ================= */

float Pid_Position_Calc(pid_t *pid, float target, float actual)
{
    pid->error = target - actual;

    /* 积分抗饱和 (Clamping) */
    pid->integral += pid->error;
    if (pid->integral > pid->integral_max) pid->integral = pid->integral_max;
    if (pid->integral < pid->integral_min) pid->integral = pid->integral_min;

    /* PID 计算 */
    float output = pid->kp * pid->error
                 + pid->ki * pid->integral
                 + pid->kd * (pid->error - pid->error_last);

    /* 输出限幅 */
    if (output > pid->output_max) output = pid->output_max;
    if (output < pid->output_min) output = pid->output_min;

    pid->error_last = pid->error;

    return output;
}

/* ================= 3. 增量式 PID ================= */

float Pid_Increment_Calc(pid_t *pid, float target, float actual)
{
    pid->error = target - actual;

    /* 增量式公式 */
    float delta = pid->kp * (pid->error - pid->error_last)
                + pid->ki * pid->error
                + pid->kd * (pid->error - 2.0f * pid->error_last + pid->error_ll);

    /* 输出限幅 */
    if (delta > pid->output_max) delta = pid->output_max;
    if (delta < pid->output_min) delta = pid->output_min;

    pid->error_ll   = pid->error_last;
    pid->error_last = pid->error;

    return delta;
}
