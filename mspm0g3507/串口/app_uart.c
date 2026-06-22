/**
 * @file    app_uart.c
 * @brief   UART 硬件绑定与业务层（MSPM0G3507 —— 唯一硬件解禁区）
 */
#include "app_uart.h"
#include "bsp_uart.h"
#include "ti_msp_dl_config.h"
#include <stdio.h>

/* ================= 1. 硬件底层函数 (HW_ 前缀) ================= */

static void HW_UART_Config(void)
{
    DL_UART_Main_enableInterrupt(UART_0_INST, DL_UART_MAIN_INTERRUPT_RX);
}

/* ================= 2. 硬件中断入口 ================= */

void UART0_IRQHandler(void)
{
    if (DL_UART_Main_getEnabledInterruptStatus(UART_0_INST) & DL_UART_MAIN_INTERRUPT_RX) {
        uint8_t data = DL_UART_Main_receiveData(UART_0_INST);
        BSP_UART_RxCallback(data);
    }
}

SYSCONFIG_WEAK void SysTick_Handler(void)
{
    BSP_UART_Timeout_Tick();
}

/* ================= 3. 对外业务切入点 ================= */

void App_UART_Init(void)
{
    HW_UART_Config();
    printf("MSPM0G3507 APP UART 业务层初始化完成!\r\n");
}

void App_UART_Task_Run(void)
{
    uint8_t frame_buf[256];
    uint16_t frame_len = 0;
    if (BSP_UART_Get_Frame(frame_buf, &frame_len)) {
        frame_buf[frame_len] = '\0';
        printf("MSPM0 收到 %d 字节的串口数据: %s\r\n", frame_len, frame_buf);
    }
}
