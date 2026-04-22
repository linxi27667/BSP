/**
 * @file    alg_competition.h
 * @brief   电赛常用算法集合 (跨平台纯 C)
 * @note    包含: 滑动平均滤波、一阶互补滤波、限幅滤波、中值滤波、
 *              一阶低通滤波、死区处理、分段线性插值
 */

#ifndef __ALG_COMPETITION_H__
#define __ALG_COMPETITION_H__

#include <stdint.h>

/* ================= 1. 滑动平均滤波 ================= */

#define ALG_MOVING_AVG_MAX_LEN  32

typedef struct {
    float   buffer[ALG_MOVING_AVG_MAX_LEN];
    uint8_t len;
    uint8_t index;
    float   sum;
} moving_avg_t;

void Moving_Avg_Init(moving_avg_t *filter, uint8_t window_len);
float Moving_Avg_Update(moving_avg_t *filter, float new_value);

/* ================= 2. 一阶低通滤波 ================= */

typedef struct {
    float alpha;
    float output;
} lowpass_filter_t;

void Lowpass_Filter_Init(lowpass_filter_t *filter, float alpha, float init_val);
float Lowpass_Filter_Update(lowpass_filter_t *filter, float new_value);

/* ================= 3. 中值滤波 ================= */

#define ALG_MEDIAN_MAX_LEN  15

typedef struct {
    float   buffer[ALG_MEDIAN_MAX_LEN];
    uint8_t len;
    uint8_t index;
    uint8_t count;
} median_filter_t;

void Median_Filter_Init(median_filter_t *filter, uint8_t window_len);
float Median_Filter_Update(median_filter_t *filter, float new_value);

/* ================= 4. 限幅滤波 ================= */

typedef struct {
    float max_delta;
    float last_value;
} amplitude_limit_filter_t;

void Amplitude_Limit_Init(amplitude_limit_filter_t *filter, float max_delta, float init_val);
float Amplitude_Limit_Update(amplitude_limit_filter_t *filter, float new_value);

/* ================= 5. 互补滤波 ================= */

typedef struct {
    float alpha;
    float angle;
} complementary_filter_t;

void Complementary_Filter_Init(complementary_filter_t *filter, float alpha);
float Complementary_Filter_Update(complementary_filter_t *filter, float gyro_rate, float accel_angle, float dt);

/* ================= 6. 死区处理 ================= */

float Dead_Zone_Apply(float value, float dead_zone_min, float dead_zone_max, float out_range);

/* ================= 7. 分段线性插值 ================= */

float Linear_Interp(float x, const float *x_table, const float *y_table, uint8_t len);

/* ================= 8. 简单均值 ================= */

float Array_Mean(const float *data, uint8_t len);

/* ================= 9. 冒泡排序 ================= */

void Bubble_Sort(float *data, uint8_t len);

#endif /* __ALG_COMPETITION_H__ */
