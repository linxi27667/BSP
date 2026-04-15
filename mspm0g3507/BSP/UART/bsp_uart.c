/**
 * @file    bsp_uart.c
 * @brief   MSPM0G3507 裸机串口底层 (纯软件超时判定不定长数据)
 */
#include "bsp_uart.h"
#include "ti_msp_dl_config.h"

/* 内部硬件配置结构体 */
typedef struct {
    UART_Regs *uart_inst;
} uart_hw_config_t;

/* 底层接收缓冲区与状态机 */
#define BSP_RX_BUF_SIZE 256
static uint8_t  rx_buf[BSP_RX_BUF_SIZE];
static uint16_t rx_idx = 0;
static uint16_t rx_timeout_ms = 0;
static bool     frame_ready = false;
static uint8_t  rx_temp = 0;

/* ================= 1. 硬件绑定配置 ================= */
static void HW_UART_Config_Get(uart_hw_config_t *config) {
    config->uart_inst = UART_0_INST;
}

/* ================= 2. 核心设备初始化 ================= */
void BSP_UART_Init(void) {
    uart_hw_config_t hw;
    HW_UART_Config_Get(&hw);
    DL_UART_Main_enableInterrupt(hw.uart_inst, DL_UART_MAIN_INTERRUPT_RX);
}

/* ================= 3. 底层中断钩子函数 ================= */
void BSP_UART_RxCallback(uint8_t data) {
    if (rx_idx < BSP_RX_BUF_SIZE) {
        rx_buf[rx_idx++] = data;
        rx_timeout_ms = 10;
    }
}

void BSP_UART_Timeout_Tick(void) {
    if (rx_timeout_ms > 0) {
        rx_timeout_ms--;
        if (rx_timeout_ms == 0 && rx_idx > 0) {
            frame_ready = true;
        }
    }
}

/* ================= 4. 提供给 APP 的拉取接口 ================= */
bool BSP_UART_Get_Frame(uint8_t *out_buf, uint16_t *out_len) {
    if (frame_ready) {
        *out_len = rx_idx;
        memcpy(out_buf, rx_buf, rx_idx);
        rx_idx = 0;
        frame_ready = false;
        return true;
    }
    return false;
}

/* ================= 5. 中断入口 ================= */
void UART0_IRQHandler(void) {
    if (DL_UART_Main_getEnabledInterruptStatus(UART_0_INST) & DL_UART_MAIN_INTERRUPT_RX) {
        uint8_t data = DL_UART_Main_receiveData(UART_0_INST);
        BSP_UART_RxCallback(data);
    }
}

SYSCONFIG_WEAK void SysTick_Handler(void) {
    BSP_UART_Timeout_Tick();
}
