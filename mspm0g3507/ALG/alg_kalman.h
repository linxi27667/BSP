/**
 * @file    alg_kalman.h
 * @brief   卡尔曼滤波算法 (一维 + 二维，跨平台纯 C)
 * @note    适用于传感器数据融合、噪声滤除、状态估计
 */

#ifndef __ALG_KALMAN_H__
#define __ALG_KALMAN_H__

#include <stdint.h>

/* ================= 1. 卡尔曼滤波结构体 ================= */

/**
 * @brief 一维卡尔曼滤波器 (单变量，适合单一传感器滤波)
 */
typedef struct {
    float x;        // 状态估计值 (最优输出)
    float p;        // 估计误差协方差
    float q;        // 过程噪声协方差 (系统模型不准确程度)
    float r;        // 测量噪声协方差 (传感器精度)
    float k_gain;   // 卡尔曼增益
} kalman_1d_t;

/**
 * @brief 二维卡尔曼滤波器 (位置+速度，适合追踪运动目标)
 */
typedef struct {
    float x;        // 位置估计值
    float v;        // 速度估计值
    float p[2][2];  // 误差协方差矩阵 2x2
    float q;        // 过程噪声
    float r;        // 测量噪声
    float dt;       // 采样时间间隔
} kalman_2d_t;

/* ================= 2. API ================= */

/* --- 一维卡尔曼 --- */
void Kalman_1D_Init(kalman_1d_t *kf, float init_val, float q, float r);
float Kalman_1D_Update(kalman_1d_t *kf, float measurement);

/* --- 二维卡尔曼 --- */
void Kalman_2D_Init(kalman_2d_t *kf, float init_pos, float q, float r, float dt);
void Kalman_2D_Update(kalman_2d_t *kf, float measurement);

#endif /* __ALG_KALMAN_H__ */
