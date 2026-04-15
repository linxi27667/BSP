#include "app_uart.h"
#include "bsp_uart.h"
#include <stdio.h>

void App_UART_Init(void) {
    BSP_UART_Init();
    printf("MSPM0G3507 APP UART 业务层初始化完成!\r\n");
}

void App_UART_Task_Run(void) {
    uint8_t frame_buf[256];
    uint16_t frame_len = 0;
    if (BSP_UART_Get_Frame(frame_buf, &frame_len)) {
        frame_buf[frame_len] = '\0';
        printf("MSPM0 收到 %d 字节的串口数据: %s\r\n", frame_len, frame_buf);
    }
}
