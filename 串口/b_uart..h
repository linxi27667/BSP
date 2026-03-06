#ifndef BSP_UART_H
#define BSP_UART_H

#include "main.h" // 包含 STM32 HAL 库头文件
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

// 暴露给 APP 层的接口
void BSP_UART_Init(void);
bool BSP_UART_Get_Frame(uint8_t *out_buf, uint16_t *out_len);

// 必须挂载到 STM32 中断里的底层处理函数
void BSP_UART_RxCallback(uint8_t data); 
void BSP_UART_Timeout_Tick(void);       

#endif
