#include "bsp_uart.h"

void Uart_Init(void)
{
//    #if (DEBUG_MODE == 1)
//    elog_a("UART", "Before xQueueCreate");
//    #endif
//    g_uart1_rx_queue_handle = xQueueCreate(5, sizeof(uart_rx_msg_t));
//    if(g_uart1_rx_queue_handle == NULL)
//    {
//        elog_a("UART", "Queue create FAILED!");
//        return;
//    }
//    else
//    {
//        #if (DEBUG_MODE == 1)
//        elog_a("UART", "Queue created OK");
//        #endif
//    }
//    
//    HAL_StatusTypeDef status = HAL_UARTEx_ReceiveToIdle_DMA(&huart1, g_uart1_rx_dma_buf, UART1_RX_BUF_SIZE);
//    if(status != HAL_OK)
//    {
//        elog_a("UART", "DMA init failed: %d", status);
//    }
//    else
//    {
//        #if (DEBUG_MODE == 1)
//        elog_a("UART", "DMA init success");
//        #endif
//    }

	//HAL_UART_Receive_IT(&huart1, &rx_data, 1);
	//HAL_TIM_Base_Start_IT(&htim7);

    HAL_UARTEx_ReceiveToIdle_DMA(&huart1, rx_dma_buf, UART1_RX_BUF_SIZE);
}

// 定义在 bsp_uart.c 或 elog_port.c

/*SemaphoreHandle_t g_uart_tx_sem_handle = NULL;

void Uart_Dma_Tx_Init(void) 
{
    // 创建一个二值信号量用于同步 DMA 发送
    g_uart_tx_sem_handle = xSemaphoreCreateBinary();
    // 初始先给一个信号量，表示“绿灯”
    xSemaphoreGive(g_uart_tx_sem_handle); 
}*/

/* 这个函数是 HAL 库预留的弱函数，你在 bsp_uart.c 里重写它
void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart) {
    if (huart->Instance == USART1) {
        BaseType_t x_higher_priority_task_woken = pdFALSE;
        
        //DMA 搬完了！把信号量还回去，让排队的下一个人可以发送 
        xSemaphoreGiveFromISR(g_uart_tx_sem_handle, &x_higher_priority_task_woken);
        
        // 触发任务切换
        portYIELD_FROM_ISR(x_higher_priority_task_woken);
    }
}
*/

/* 回调函数模板
void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t size)
{
    if(huart->Instance == USART1)
    {
       uart_rx_msg_t rx_msg;
       uint16_t copy_size = (size < UART1_RX_BUF_SIZE) ? size : UART1_RX_BUF_SIZE;
       rx_msg.len = copy_size;
       memcpy(rx_msg.data, g_uart1_rx_dma_buf, copy_size);

       BaseType_t xHigherPriorityTaskWoken = pdFALSE;
       xQueueSendFromISR(g_uart1_rx_queue_handle, &rx_msg, &xHigherPriorityTaskWoken);
       portYIELD_FROM_ISR(xHigherPriorityTaskWoken);

       HAL_UARTEx_ReceiveToIdle_DMA(&huart1, g_uart1_rx_dma_buf, UART1_RX_BUF_SIZE);
    }
}
*/

/*void Serial_Task(void *paramater) 队列任务消费者
{
    uart_rx_msg_t rx_msg;
    while(1)
    {
        elog_i("serial_task:","waiting for queue");
        if(xQueueReceive(g_uart1_rx_queue_handle, &rx_msg, portMAX_DELAY) == pdPASS)
        {
            uint8_t i;
            for(i = 0; i < rx_msg.len; i++)
            {
                elog_a("serial_task:","rx_msg.data[%d] = %c", i, rx_msg.data[i]);
            }
            if(sscanf((char *)rx_msg.data, "%[^-]-%3s", (char *)old_password, (char *)current_password) == 2)
            {
                elog_i("serial_task:", "old_password = %s, current_password = %s", old_password, current_password);
                
            }
        }
    }
}*/
