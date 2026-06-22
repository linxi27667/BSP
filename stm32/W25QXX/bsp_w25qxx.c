/**
 * @file    bsp_w25qxx.c
 * @brief   W25Qxx Flash 驱动核心逻辑实现（BSP — 纯逻辑，跨平台）
 */
#include "bsp_w25qxx.h"

/* ================= W25Q128 命令定义 ================= */

#define W25Q_CMD_READ_JEDEC_ID    0x9F
#define W25Q_CMD_READ_DEV_ID      0x90
#define W25Q_CMD_READ_DATA        0x03
#define W25Q_CMD_WRITE_ENABLE     0x06
#define W25Q_CMD_PAGE_PROGRAM     0x02
#define W25Q_CMD_SECTOR_ERASE     0x20
#define W25Q_CMD_CHIP_ERASE       0xC7
#define W25Q_CMD_STATUS_REG       0x05

/* W25Q128 参数 */
#define W25Q_PAGE_SIZE            256
#define W25Q_SECTOR_SIZE          4096

/* ================= 内部辅助函数 ================= */

static uint8_t W25Q_Wait_Busy(w25q_t *flash)
{
    spi_bus_t *bus = flash->bus;
    uint8_t tx[2], rx[2];
    uint32_t timeout = 100000;

    while (timeout--) {
        tx[0] = W25Q_CMD_STATUS_REG;
        tx[1] = 0xFF;
        SPI_Bus_Select(bus);
        if (bus->Transmit_Receive(bus->handle, tx, rx, 2, 100) != 0) {
            SPI_Bus_Deselect(bus);
            return W25Q_ERR;
        }
        SPI_Bus_Deselect(bus);
        if ((rx[1] & 0x01) == 0) return W25Q_OK;
        for (volatile int i = 0; i < 50; i++);
    }
    return W25Q_ERR;
}

static uint8_t W25Q_Write_Enable(w25q_t *flash)
{
    spi_bus_t *bus = flash->bus;
    if (W25Q_Wait_Busy(flash) != W25Q_OK) return W25Q_ERR;
    uint8_t cmd = W25Q_CMD_WRITE_ENABLE;
    SPI_Bus_Select(bus);
    if (bus->Transmit(bus->handle, &cmd, 1, 100) != 0) {
        SPI_Bus_Deselect(bus);
        return W25Q_ERR;
    }
    SPI_Bus_Deselect(bus);
    return W25Q_OK;
}

/* ================= W25Q128 对外 API ================= */

uint8_t W25Q_Init_Device(w25q_t *flash)
{
    if (!flash || !flash->bus) return W25Q_ERR;
    if (W25Q_Wait_Busy(flash) != W25Q_OK) return W25Q_ERR;
    /* 读取 JEDEC ID 验证通信，W25Q128 应返回 0xEF4018 */
    uint32_t jedec_id = W25Q_Read_JEDEC_ID(flash);
    (void)jedec_id;
    return W25Q_OK;
}

uint32_t W25Q_Read_JEDEC_ID(w25q_t *flash)
{
    if (!flash || !flash->bus) return 0;
    spi_bus_t *bus = flash->bus;
    uint8_t tx[4] = {W25Q_CMD_READ_JEDEC_ID, 0xFF, 0xFF, 0xFF};
    uint8_t rx[4];
    SPI_Bus_Select(bus);
    if (bus->Transmit_Receive(bus->handle, tx, rx, 4, 100) != 0) {
        SPI_Bus_Deselect(bus);
        return 0;
    }
    SPI_Bus_Deselect(bus);
    return (uint32_t)(rx[1] << 16) | (uint32_t)(rx[2] << 8) | (uint32_t)rx[3];
}

uint16_t W25Q_Read_Device_ID(w25q_t *flash)
{
    if (!flash || !flash->bus) return 0;
    spi_bus_t *bus = flash->bus;
    uint8_t tx[5] = {W25Q_CMD_READ_DEV_ID, 0x00, 0x00, 0x00, 0xFF};
    uint8_t rx[5];
    SPI_Bus_Select(bus);
    if (bus->Transmit_Receive(bus->handle, tx, rx, 5, 100) != 0) {
        SPI_Bus_Deselect(bus);
        return 0;
    }
    SPI_Bus_Deselect(bus);
    return (uint16_t)(rx[3] << 8) | (uint16_t)rx[4];
}

uint8_t W25Q_Read_Byte(w25q_t *flash, uint32_t addr)
{
    uint8_t data;
    W25Q_Read_Buffer(flash, addr, &data, 1);
    return data;
}

uint8_t W25Q_Read_Buffer(w25q_t *flash, uint32_t addr, uint8_t *buf, uint16_t len)
{
    if (!flash || !flash->bus || !buf) return W25Q_ERR;
    spi_bus_t *bus = flash->bus;
    uint8_t cmd[4];
    cmd[0] = W25Q_CMD_READ_DATA;
    cmd[1] = (addr >> 16) & 0xFF;
    cmd[2] = (addr >> 8) & 0xFF;
    cmd[3] = addr & 0xFF;

    SPI_Bus_Select(bus);
    if (bus->Transmit(bus->handle, cmd, 4, 100) != 0) {
        SPI_Bus_Deselect(bus);
        return W25Q_ERR;
    }
    if (bus->Transmit_Receive(bus->handle, NULL, buf, len, 1000) != 0) {
        SPI_Bus_Deselect(bus);
        return W25Q_ERR;
    }
    SPI_Bus_Deselect(bus);
    return W25Q_OK;
}

uint8_t W25Q_Sector_Erase(w25q_t *flash, uint32_t addr)
{
    if (!flash || !flash->bus) return W25Q_ERR;
    if (addr % W25Q_SECTOR_SIZE != 0) return W25Q_ERR;
    spi_bus_t *bus = flash->bus;
    uint8_t cmd[4];
    cmd[0] = W25Q_CMD_SECTOR_ERASE;
    cmd[1] = (addr >> 16) & 0xFF;
    cmd[2] = (addr >> 8) & 0xFF;
    cmd[3] = addr & 0xFF;

    if (W25Q_Write_Enable(flash) != W25Q_OK) return W25Q_ERR;
    SPI_Bus_Select(bus);
    if (bus->Transmit(bus->handle, cmd, 4, 100) != 0) {
        SPI_Bus_Deselect(bus);
        return W25Q_ERR;
    }
    SPI_Bus_Deselect(bus);
    return W25Q_Wait_Busy(flash);
}

uint8_t W25Q_Chip_Erase(w25q_t *flash)
{
    if (!flash || !flash->bus) return W25Q_ERR;
    spi_bus_t *bus = flash->bus;
    uint8_t cmd = W25Q_CMD_CHIP_ERASE;
    if (W25Q_Write_Enable(flash) != W25Q_OK) return W25Q_ERR;
    SPI_Bus_Select(bus);
    if (bus->Transmit(bus->handle, &cmd, 1, 100) != 0) {
        SPI_Bus_Deselect(bus);
        return W25Q_ERR;
    }
    SPI_Bus_Deselect(bus);
    return W25Q_Wait_Busy(flash);
}

uint8_t W25Q_Page_Program(w25q_t *flash, uint32_t addr, const uint8_t *data, uint16_t len)
{
    if (!flash || !flash->bus || !data) return W25Q_ERR;
    if (len == 0 || len > W25Q_PAGE_SIZE) return W25Q_ERR;
    /* 检查是否跨页边界 */
    uint32_t page_end_addr = (addr + W25Q_PAGE_SIZE) & ~(W25Q_PAGE_SIZE - 1);
    if (addr + len > page_end_addr) return W25Q_ERR;

    spi_bus_t *bus = flash->bus;
    uint8_t cmd[4];
    cmd[0] = W25Q_CMD_PAGE_PROGRAM;
    cmd[1] = (addr >> 16) & 0xFF;
    cmd[2] = (addr >> 8) & 0xFF;
    cmd[3] = addr & 0xFF;

    if (W25Q_Write_Enable(flash) != W25Q_OK) return W25Q_ERR;
    SPI_Bus_Select(bus);
    if (bus->Transmit(bus->handle, cmd, 4, 100) != 0) {
        SPI_Bus_Deselect(bus);
        return W25Q_ERR;
    }
    if (bus->Transmit(bus->handle, data, len, 1000) != 0) {
        SPI_Bus_Deselect(bus);
        return W25Q_ERR;
    }
    SPI_Bus_Deselect(bus);
    return W25Q_Wait_Busy(flash);
}

uint8_t W25Q_Write_MultiPage(w25q_t *flash, uint32_t addr, const uint8_t *data, uint16_t len)
{
    if (!flash || !flash->bus || !data) return W25Q_ERR;
    if (len == 0) return W25Q_ERR;

    while (len > 0) {
        uint16_t page_remain = W25Q_PAGE_SIZE - (addr % W25Q_PAGE_SIZE);
        uint16_t cur_len = (len < page_remain) ? len : page_remain;
        if (W25Q_Page_Program(flash, addr, data, cur_len) != W25Q_OK) return W25Q_ERR;
        data += cur_len;
        addr += cur_len;
        len  -= cur_len;
    }
    return W25Q_OK;
}
