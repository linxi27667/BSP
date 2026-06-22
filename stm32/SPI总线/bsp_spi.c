/**
 * @file    bsp_spi.c
 * @brief   SPI 总线核心逻辑实现（BSP — 纯逻辑，跨平台）
 */
#include "bsp_spi.h"

/* ================= 1. SPI 总线基础操作 ================= */

void SPI_Bus_Init(spi_bus_t *bus)
{
    if (bus && bus->Init) {
        bus->Init();
    }
}

/* ================= 2. 片选控制 ================= */

void SPI_Bus_Select(spi_bus_t *bus)
{
    bus->CS_Write(bus->cs.port, bus->cs.pin, 0);
}

void SPI_Bus_Deselect(spi_bus_t *bus)
{
    bus->CS_Write(bus->cs.port, bus->cs.pin, 1);
}
