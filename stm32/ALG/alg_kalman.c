/**
 * @file    alg_kalman.c
 * @brief   卡尔曼滤波实现 (一维 + 二维)
 */

#include "alg_kalman.h"

/* ================= 1. 一维卡尔曼 ================= */

void Kalman_1D_Init(kalman_1d_t *kf, float init_val, float q, float r)
{
    kf->x = init_val;
    kf->q = q;
    kf->r = r;
    kf->p = 1.0f;
    kf->k_gain = 0.0f;
}

float Kalman_1D_Update(kalman_1d_t *kf, float measurement)
{
    kf->p += kf->q;
    kf->k_gain = kf->p / (kf->p + kf->r);
    kf->x += kf->k_gain * (measurement - kf->x);
    kf->p *= (1.0f - kf->k_gain);
    return kf->x;
}

/* ================= 2. 二维卡尔曼 ================= */

void Kalman_2D_Init(kalman_2d_t *kf, float init_pos, float q, float r, float dt)
{
    kf->x = init_pos;
    kf->v = 0.0f;
    kf->q = q;
    kf->r = r;
    kf->dt = dt;
    kf->p[0][0] = 1.0f; kf->p[0][1] = 0.0f;
    kf->p[1][0] = 0.0f; kf->p[1][1] = 1.0f;
}

void Kalman_2D_Update(kalman_2d_t *kf, float measurement)
{
    float dt = kf->dt;

    /* 预测 */
    kf->x = kf->x + kf->v * dt;

    float p_pred[2][2];
    p_pred[0][0] = kf->p[0][0] + dt * (kf->p[1][0] + kf->p[0][1]) + dt * dt * kf->p[1][1] + kf->q;
    p_pred[0][1] = kf->p[0][1] + dt * kf->p[1][1];
    p_pred[1][0] = kf->p[1][0] + dt * kf->p[1][1];
    p_pred[1][1] = kf->p[1][1] + kf->q;

    /* 更新 */
    float y = measurement - kf->x;
    float s = p_pred[0][0] + kf->r;

    float k[2];
    k[0] = p_pred[0][0] / s;
    k[1] = p_pred[1][0] / s;

    kf->x += k[0] * y;
    kf->v += k[1] * y;

    kf->p[0][0] = (1.0f - k[0]) * p_pred[0][0];
    kf->p[0][1] = (1.0f - k[0]) * p_pred[0][1];
    kf->p[1][0] = -k[1] * p_pred[0][0] + p_pred[1][0];
    kf->p[1][1] = -k[1] * p_pred[0][1] + p_pred[1][1];
}
