/**
 * @file    alg_competition.c
 * @brief   电赛常用算法集合实现
 */

#include "alg_competition.h"
#include <string.h>

/* ================= 1. 滑动平均滤波 ================= */

void Moving_Avg_Init(moving_avg_t *filter, uint8_t window_len)
{
    memset(filter->buffer, 0, sizeof(filter->buffer));
    filter->len = (window_len > ALG_MOVING_AVG_MAX_LEN) ? ALG_MOVING_AVG_MAX_LEN : window_len;
    filter->index = 0;
    filter->sum = 0.0f;
}

float Moving_Avg_Update(moving_avg_t *filter, float new_value)
{
    filter->sum -= filter->buffer[filter->index];
    filter->buffer[filter->index] = new_value;
    filter->sum += new_value;
    filter->index = (filter->index + 1) % filter->len;
    return filter->sum / filter->len;
}

/* ================= 2. 一阶低通滤波 ================= */

void Lowpass_Filter_Init(lowpass_filter_t *filter, float alpha, float init_val)
{
    filter->alpha = alpha;
    filter->output = init_val;
}

float Lowpass_Filter_Update(lowpass_filter_t *filter, float new_value)
{
    filter->output = filter->alpha * new_value + (1.0f - filter->alpha) * filter->output;
    return filter->output;
}

/* ================= 3. 中值滤波 ================= */

static float find_median(float *arr, uint8_t len)
{
    /* 简单冒泡排序找中值 */
    for (uint8_t i = 0; i < len - 1; i++) {
        for (uint8_t j = 0; j < len - i - 1; j++) {
            if (arr[j] > arr[j + 1]) {
                float temp = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = temp;
            }
        }
    }
    return arr[len / 2];
}

void Median_Filter_Init(median_filter_t *filter, uint8_t window_len)
{
    memset(filter->buffer, 0, sizeof(filter->buffer));
    filter->len = (window_len > ALG_MEDIAN_MAX_LEN) ? ALG_MEDIAN_MAX_LEN : window_len;
    filter->index = 0;
    filter->count = 0;
}

float Median_Filter_Update(median_filter_t *filter, float new_value)
{
    filter->buffer[filter->index] = new_value;
    filter->index = (filter->index + 1) % filter->len;
    if (filter->count < filter->len) filter->count++;
    
    /* 复制一份用于排序 */
    float temp_buf[ALG_MEDIAN_MAX_LEN];
    memcpy(temp_buf, filter->buffer, filter->count * sizeof(float));
    return find_median(temp_buf, filter->count);
}

/* ================= 4. 限幅滤波 ================= */

void Amplitude_Limit_Init(amplitude_limit_filter_t *filter, float max_delta, float init_val)
{
    filter->max_delta = max_delta;
    filter->last_value = init_val;
}

float Amplitude_Limit_Update(amplitude_limit_filter_t *filter, float new_value)
{
    float delta = new_value - filter->last_value;
    if (delta > filter->max_delta) {
        filter->last_value += filter->max_delta;
    } else if (delta < -filter->max_delta) {
        filter->last_value -= filter->max_delta;
    } else {
        filter->last_value = new_value;
    }
    return filter->last_value;
}

/* ================= 5. 互补滤波 ================= */

void Complementary_Filter_Init(complementary_filter_t *filter, float alpha)
{
    filter->alpha = alpha;
    filter->angle = 0.0f;
}

float Complementary_Filter_Update(complementary_filter_t *filter, float gyro_rate, float accel_angle, float dt)
{
    filter->angle = filter->alpha * (filter->angle + gyro_rate * dt) + (1.0f - filter->alpha) * accel_angle;
    return filter->angle;
}

/* ================= 6. 死区处理 ================= */

float Dead_Zone_Apply(float value, float dead_zone_min, float dead_zone_max, float out_range)
{
    if (value >= dead_zone_min && value <= dead_zone_max) {
        return 0.0f;
    } else if (value > dead_zone_max) {
        return (value - dead_zone_max) / (out_range - dead_zone_max) * out_range;
    } else {
        return (value - dead_zone_min) / (-out_range - dead_zone_min) * out_range;
    }
}

/* ================= 7. 分段线性插值 ================= */

float Linear_Interp(float x, const float *x_table, const float *y_table, uint8_t len)
{
    if (x <= x_table[0]) return y_table[0];
    if (x >= x_table[len - 1]) return y_table[len - 1];
    
    for (uint8_t i = 0; i < len - 1; i++) {
        if (x >= x_table[i] && x <= x_table[i + 1]) {
            float ratio = (x - x_table[i]) / (x_table[i + 1] - x_table[i]);
            return y_table[i] + ratio * (y_table[i + 1] - y_table[i]);
        }
    }
    return y_table[len - 1];
}

/* ================= 8. 简单均值 ================= */

float Array_Mean(const float *data, uint8_t len)
{
    if (len == 0) return 0.0f;
    float sum = 0.0f;
    for (uint8_t i = 0; i < len; i++) {
        sum += data[i];
    }
    return sum / len;
}

/* ================= 9. 冒泡排序 ================= */

void Bubble_Sort(float *data, uint8_t len)
{
    for (uint8_t i = 0; i < len - 1; i++) {
        for (uint8_t j = 0; j < len - i - 1; j++) {
            if (data[j] > data[j + 1]) {
                float temp = data[j];
                data[j] = data[j + 1];
                data[j + 1] = temp;
            }
        }
    }
}
