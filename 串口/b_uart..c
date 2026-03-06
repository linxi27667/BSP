/**
 * @file    bsp_uart.c
 * @brief   STM32 裸机串口底层 (不使用 IDLE，纯软件超时判定不定长数据)
 */
#include "bsp_uart.h"

// 引入 CubeMX 生成的串口句柄
extern UART_HandleTypeDef huart1;

// 内部硬件配置结构体
typedef struct {
    UART_HandleTypeDef *huart;
} uart_hw_config_t;

// 底层接收缓冲区与状态机
#define BSP_RX_BUF_SIZE 256
static uint8_t  rx_buf[BSP_RX_BUF_SIZE];
static uint16_t rx_idx = 0;
static uint16_t rx_timeout_ms = 0;
static bool     frame_ready = false;
static uint8_t  rx_temp = 0; // 每次接收 1 字节的暂存

/* ================= 1. 硬件绑定配置 ================= */
static void HW_UART_Config_Get(uart_hw_config_t *config) {
    // 严格绑定底层的硬件句柄
    config->huart = &huart1;
}

/* ================= 2. 核心设备初始化 ================= */
void BSP_UART_Init(void) {
    uart_hw_config_t hw;
    HW_UART_Config_Get(&hw);
    
    // 比赛时波特率和引脚通常在 CubeMX 里配置好了
    // 这里只负责开启第一次单字节接收中断
    HAL_UART_Receive_IT(hw.huart, &rx_temp, 1);
}

/* ================= 3. 底层中断钩子函数 ================= */
// ⚠️ 这个函数必须放到 HAL_UART_RxCpltCallback 中调用
void BSP_UART_RxCallback(uint8_t data) {
    if (rx_idx < BSP_RX_BUF_SIZE) {
        rx_buf[rx_idx++] = data;
        // 只要收到新数据，就重置超时计数器 (例如 10 毫秒没有新数据，判定为一帧结束)
        rx_timeout_ms = 10; 
    }
}

// ⚠️ 这个函数必须放到 SysTick_Handler (每 1ms 触发一次) 中调用
void BSP_UART_Timeout_Tick(void) {
    if (rx_timeout_ms > 0) {
        rx_timeout_ms--;
        if (rx_timeout_ms == 0 && rx_idx > 0) {
            // 定时器归零，说明有一段时间没收到数据了，触发截断！
            frame_ready = true; 
        }
    }
}

/* ================= 4. 提供给 APP 的拉取接口 ================= */
bool BSP_UART_Get_Frame(uint8_t *out_buf, uint16_t *out_len) {
    if (frame_ready) {
        *out_len = rx_idx;
        memcpy(out_buf, rx_buf, rx_idx);
        
        // 提取完毕，重置底层状态
        rx_idx = 0;
        frame_ready = false;
        return true;
    }
    return false;
}