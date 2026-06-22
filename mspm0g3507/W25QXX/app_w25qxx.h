#ifndef __APP_W25QXX_H__
#define __APP_W25QXX_H__

#include <stdint.h>
#include "bsp_w25qxx.h"

/* ============ W25Q 存储地址（双扇区轮转） ============ */

#define W25Q_SLOT_A_ADDR        0x00000000U
#define W25Q_SLOT_B_ADDR        0x00001000U

/* ============ 持久化数据结构 ============ */

typedef struct {
    uint32_t magic;
    uint32_t debug_counter;
    uint32_t crc;
} w25q_storage_t;

#define W25Q_STORAGE_MAGIC      0x53544F52U
#define W25Q_STORAGE_SIZE       sizeof(w25q_storage_t)

/* ============ 全局对象 ============ */

extern w25q_t W25Q_Flash;
extern w25q_storage_t g_w25q_storage;

/* ============ 系统初始化 ============ */
void App_W25Qxx_System_Init(void);

/* ============ 对外接口 ============ */
uint32_t App_W25Qxx_Get_JEDEC_ID(void);
uint8_t  App_W25Qxx_Storage_Save(void);
void     App_W25Qxx_Storage_Load(void);

#endif /* __APP_W25QXX_H__ */
