#ifndef __APP_SPI_H__
#define __APP_SPI_H__

#include "bsp_spi.h"

/* ============ SPI0 硬件配置 ============ */
#define SPI_BUS_HANDLE          SPI_0_INST
#define SPI_CS_PORT             GPIOA
#define SPI_CS_PIN              DL_GPIO_PIN_10

/* ============ 全局对象 ============ */
extern spi_bus_t SPI_Bus;

/* ============ 系统初始化 ============ */
void App_SPI_System_Init(void);

#endif /* __APP_SPI_H__ */
