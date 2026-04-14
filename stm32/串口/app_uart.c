#include "app_uart.h"
#include "bsp_uart.h"
#include <stdio.h>

// 业务层初始化
void App_UART_Init(void) {
    BSP_UART_Init();
    printf("STM32 APP 串口业务层已启动!\r\n");
}

// 裸机业务轮询任务 (放进 main 的 while(1) 里面无脑跑)
void App_UART_Task_Run(void) {
    uint8_t frame_buf[256];
    uint16_t frame_len = 0;

    // 尝试从 BSP 层“摸”一帧数据出来
    if (BSP_UART_Get_Frame(frame_buf, &frame_len)) {
        
        // 加上字符串结束符，方便打印测试
        frame_buf[frame_len] = '\0';
        
        // ==========================================
        // ?? 这里就是你的业务处理核心区！
        // ==========================================
        printf("?? 收到 %d 字节的不定长数据: %s\r\n", frame_len, frame_buf);
        
        // 如果是电机指令，直接调用 app_motor_set(...) 等等
    }
}
