/**
 * @file    bsp_uart.c
 * @brief   串口不定长帧接收底层 (纯软件超时判定，跨平台)
 */
#include "bsp_uart.h"

/* 底层接收缓冲区与状态机 */
#define BSP_RX_BUF_SIZE 256
static uint8_t  rx_buf[BSP_RX_BUF_SIZE];
static uint16_t rx_idx = 0;
static uint16_t rx_timeout_ms = 0;
static bool     frame_ready = false;

/* ================= 1. 中断钩子函数 (在 app_uart.c 的 ISR 中调用) ================= */
void BSP_UART_RxCallback(uint8_t data)
{
    if (rx_idx < BSP_RX_BUF_SIZE) {
        rx_buf[rx_idx++] = data;
        rx_timeout_ms = 10;  /* 10ms 超时判定 */
    }
}

void BSP_UART_Timeout_Tick(void)
{
    if (rx_timeout_ms > 0) {
        rx_timeout_ms--;
        if (rx_timeout_ms == 0 && rx_idx > 0) {
            frame_ready = true;
        }
    }
}

/* ================= 2. 提供给 APP 的拉取接口 ================= */
bool BSP_UART_Get_Frame(uint8_t *out_buf, uint16_t *out_len)
{
    if (frame_ready) {
        *out_len = rx_idx;
        memcpy(out_buf, rx_buf, rx_idx);
        rx_idx = 0;
        frame_ready = false;
        return true;
    }
    return false;
}
