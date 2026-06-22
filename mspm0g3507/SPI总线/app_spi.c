/**
 * @file    app_spi.c
 * @brief   SPI 硬件绑定实现（MSPM0G3507 —— 唯一硬件解禁区）
 */
#include "app_spi.h"
#include "ti_msp_dl_config.h"
#include <ti/driverlib/devices/mspm0g3507/dl_spi.h>

/* ================= 1. 硬件底层函数 (HW_ 前缀) ================= */

/* SPI 初始化函数（拉高 CS） */
static void HW_SPI_Init(void)
{
    /* SPI 已在 SysConfig 中配置，此处仅拉高 CS */
    DL_GPIO_setPins(SPI_CS_PORT, SPI_CS_PIN);
}

/* CS 引脚写操作 */
static void HW_CS_Write(void *port, uint16_t pin, uint8_t level)
{
    if (level)
        DL_GPIO_setPins((GPIO_Regs *)port, pin);
    else
        DL_GPIO_clearPins((GPIO_Regs *)port, pin);
}

/* SPI 数据发送（阻塞式） */
static uint8_t HW_SPI_Transmit(void *hspi, const uint8_t *tx_data, uint16_t size, uint32_t timeout)
{
    SPI_Regs *spi_inst = (SPI_Regs *)hspi;
    (void)timeout;
    for (uint16_t i = 0; i < size; i++) {
        DL_SPI_transmitDataBlocking(spi_inst, tx_data[i]);
    }
    return 0;
}

/* SPI 数据收发（全双工阻塞式） */
static uint8_t HW_SPI_Transmit_Receive(void *hspi, const uint8_t *tx_data, uint8_t *rx_data, uint16_t size, uint32_t timeout)
{
    SPI_Regs *spi_inst = (SPI_Regs *)hspi;
    (void)timeout;

    if (tx_data == NULL) {
        /* 纯接收模式：发 dummy 0xFF */
        for (uint16_t i = 0; i < size; i++) {
            DL_SPI_transmitData(spi_inst, 0xFF);
            DL_SPI_receiveDataBlocking(spi_inst, &rx_data[i]);
        }
        return 0;
    }

    /* 全双工收发 */
    for (uint16_t i = 0; i < size; i++) {
        DL_SPI_transmitData(spi_inst, tx_data[i]);
        DL_SPI_receiveDataBlocking(spi_inst, &rx_data[i]);
    }
    return 0;
}

/* ================= 2. 对象实例化与引脚拼装 ================= */

spi_bus_t SPI_Bus = {
    .handle = SPI_BUS_HANDLE,
    .cs = {SPI_CS_PORT, SPI_CS_PIN},
    .Init             = HW_SPI_Init,
    .CS_Write         = HW_CS_Write,
    .Transmit         = HW_SPI_Transmit,
    .Transmit_Receive = HW_SPI_Transmit_Receive
};

/* ================= 3. 系统初始化 ================= */

void App_SPI_System_Init(void)
{
    SPI_Bus_Init(&SPI_Bus);
}
