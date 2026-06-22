/**
 * @file    app_w25qxx.c
 * @brief   W25Qxx 业务层实现（STM32F4）
 */
#include "app_w25qxx.h"
#include "app_spi.h"
#include <stdio.h>

#define W25QXX_DEBUG_MODE   0

/* ================= 1. 全局数据 ================= */

w25q_storage_t g_w25q_storage = {0};

/* ================= 2. W25Q 对象实例化 ================= */

w25q_t W25Q_Flash = {
    .bus = &SPI_Bus
};

/* ================= 3. 内部辅助函数 ================= */

static uint32_t storage_crc(const w25q_storage_t *s)
{
    return s->magic ^ s->debug_counter;
}

static uint8_t storage_validate(const w25q_storage_t *s)
{
    return (s->magic == W25Q_STORAGE_MAGIC) && (s->crc == storage_crc(s));
}

static void storage_set_crc(w25q_storage_t *s)
{
    s->crc = storage_crc(s);
}

/* 读取一个 slot 并验证有效性 */
static uint8_t storage_read_slot(w25q_storage_t *out, uint32_t addr)
{
    if (W25Q_Read_Buffer(&W25Q_Flash, addr, (uint8_t *)out, W25Q_STORAGE_SIZE) != W25Q_OK)
        return W25Q_ERR;
    return storage_validate(out) ? W25Q_OK : W25Q_ERR;
}

/* ================= 4. 系统初始化 ================= */

void App_W25Qxx_System_Init(void)
{
    App_SPI_System_Init();

#if W25QXX_DEBUG_MODE == 1
    uint32_t jedec_id = W25Q_Read_JEDEC_ID(&W25Q_Flash);
    printf("W25Q JEDEC ID raw: 0x%06lX\r\n", jedec_id);
#endif

    uint8_t ret = W25Q_Init_Device(&W25Q_Flash);
    if (ret == W25Q_OK) {
        App_W25Qxx_Storage_Load();
#if W25QXX_DEBUG_MODE == 1
        printf("W25Q Init OK\r\n");
#endif
    } else {
#if W25QXX_DEBUG_MODE == 1
        printf("W25Q Init FAILED!\r\n");
#endif
    }
}

/* ================= 5. 对外接口 ================= */

uint32_t App_W25Qxx_Get_JEDEC_ID(void)
{
    return W25Q_Read_JEDEC_ID(&W25Q_Flash);
}

void App_W25Qxx_Storage_Load(void)
{
    w25q_storage_t slot_a, slot_b;
    uint8_t a_ok = storage_read_slot(&slot_a, W25Q_SLOT_A_ADDR);
    uint8_t b_ok = storage_read_slot(&slot_b, W25Q_SLOT_B_ADDR);

    if (a_ok == W25Q_OK && b_ok == W25Q_OK) {
        if (slot_b.debug_counter > slot_a.debug_counter)
            g_w25q_storage = slot_b;
        else
            g_w25q_storage = slot_a;
    } else if (a_ok == W25Q_OK) {
        g_w25q_storage = slot_a;
    } else if (b_ok == W25Q_OK) {
        g_w25q_storage = slot_b;
    } else {
        g_w25q_storage.magic = W25Q_STORAGE_MAGIC;
        g_w25q_storage.debug_counter = 0;
        g_w25q_storage.crc = storage_crc(&g_w25q_storage);
    }
}

uint8_t App_W25Qxx_Storage_Save(void)
{
    storage_set_crc(&g_w25q_storage);

    w25q_storage_t slot_a, slot_b;
    uint8_t a_ok = storage_read_slot(&slot_a, W25Q_SLOT_A_ADDR);
    uint8_t b_ok = storage_read_slot(&slot_b, W25Q_SLOT_B_ADDR);

    /* 写入非活跃 slot，保证双备份 */
    uint32_t target_addr;
    if (a_ok != W25Q_OK && b_ok != W25Q_OK)
        target_addr = W25Q_SLOT_A_ADDR;
    else if (a_ok != W25Q_OK)
        target_addr = W25Q_SLOT_A_ADDR;
    else if (b_ok != W25Q_OK)
        target_addr = W25Q_SLOT_B_ADDR;
    else if (slot_a.debug_counter <= slot_b.debug_counter)
        target_addr = W25Q_SLOT_A_ADDR;
    else
        target_addr = W25Q_SLOT_B_ADDR;

    uint8_t ret = W25Q_Sector_Erase(&W25Q_Flash, target_addr);
    if (ret != W25Q_OK) return W25Q_ERR;

    ret = W25Q_Page_Program(&W25Q_Flash, target_addr,
                            (uint8_t *)&g_w25q_storage, W25Q_STORAGE_SIZE);
    return ret;
}
