#ifndef __BSP_UART_H__
#define __BSP_UART_H__

#include "main.h"

#define UART1_RX_BUF_SIZE 256

typedef struct {
    uint8_t data[UART1_RX_BUF_SIZE]; // 接收数据缓存
    uint16_t len; // 接收数据长度
}uart_rx_msg_t;



void Uart_Init(void);
void Uart_Dma_Tx_Init(void);

extern QueueHandle_t g_uart1_rx_queue_handle; //声明应用层变量
extern uint8_t g_uart1_rx_dma_buf[UART1_RX_BUF_SIZE]; //声明应用层变量
//extern SemaphoreHandle_t g_uart_tx_sem_handle;

#endif






