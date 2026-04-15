#ifndef BSP_UART_H
#define BSP_UART_H

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

/* 暴露给 APP 层的接口 */
void BSP_UART_Init(void);
bool BSP_UART_Get_Frame(uint8_t *out_buf, uint16_t *out_len);

/* 中断钩子函数 —— 必须在 UART 中断回调中调用 */
void BSP_UART_RxCallback(uint8_t data);
/* 超时判定 —— 必须在 1ms 周期 Tick 中调用 */
void BSP_UART_Timeout_Tick(void);

#endif /* BSP_UART_H */
