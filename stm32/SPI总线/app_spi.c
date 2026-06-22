/**
 * @file    app_spi.c
 * @brief   SPI 硬件绑定实现（STM32F4 —— 唯一硬件解禁区）
 */
#include "app_spi.h"
#include "main.h"
#include "spi.h"

/* ================= 1. 硬件底层函数 (HW_ 前缀) ================= */

/* SPI 初始化函数（拉高 CS） */
static void HW_SPI_Init(void)
{
    /* SPI 已在 CubeMX 中配置，此处仅拉高 CS */
    HAL_GPIO_WritePin(SPI_CS_PORT, SPI_CS_PIN, GPIO_PIN_SET);
}

/* CS 引脚写操作 */
static void HW_CS_Write(void *port, uint16_t pin, uint8_t level)
{
    HAL_GPIO_WritePin((GPIO_TypeDef *)port, pin,
        level ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

/* SPI 数据发送 */
static uint8_t HW_SPI_Transmit(void *hspi, const uint8_t *tx_data, uint16_t size, uint32_t timeout)
{
    SPI_HandleTypeDef *handle = (SPI_HandleTypeDef *)hspi;
    if (handle->State != HAL_SPI_STATE_READY) {
        handle->State = HAL_SPI_STATE_READY;
        handle->ErrorCode = HAL_SPI_ERROR_NONE;
    }
    return HAL_SPI_Transmit(handle, (uint8_t *)tx_data, size, timeout) == HAL_OK ? 0 : 1;
}

/* SPI 数据收发 */
static uint8_t HW_SPI_Transmit_Receive(void *hspi, const uint8_t *tx_data, uint8_t *rx_data, uint16_t size, uint32_t timeout)
{
    SPI_HandleTypeDef *handle = (SPI_HandleTypeDef *)hspi;
    if (handle->State != HAL_SPI_STATE_READY) {
        handle->State = HAL_SPI_STATE_READY;
        handle->ErrorCode = HAL_SPI_ERROR_NONE;
    }
    if (!tx_data) {
        return HAL_SPI_Receive(handle, rx_data, size, timeout) == HAL_OK ? 0 : 1;
    }
    return HAL_SPI_TransmitReceive(handle, (uint8_t *)tx_data, rx_data, size, timeout) == HAL_OK ? 0 : 1;
}

/* ================= 2. 对象实例化与引脚拼装 ================= */

spi_bus_t SPI_Bus = {
    .handle = &hspi1,
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
