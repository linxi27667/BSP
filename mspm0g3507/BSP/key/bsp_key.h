#ifndef __BSP_KEY_H__
#define __BSP_KEY_H__

#include <stdint.h>

#define KEY_PRESS    0
#define KEY_RELEASE  1

#define MAX_KEY_NUM          4
#define KEY_LONGPUSH_MINTIME 80
#define KEY_DOUBLECLICK_TIMEOUT 15
#define DEBOUNCE_CNT         10

typedef enum {
    KEY_JUDGE_IDLE = 0,
    KEY_JUDGE_PRESS,
    KEY_JUDGE_LONGPUSH,
    KEY_JUDGE_DOUBLECLICK,
    KEY_JUDGE_RELEASE
} key_judge_t;

typedef enum {
    KEY_EVENT_IDLE = 0,
    KEY_EVENT_PUSH,
    KEY_EVENT_LONGPUSH,
    KEY_EVENT_DOUBLECLICK
} key_event_t;

typedef struct {
    void    *port;
    uint16_t pin;
} key_gpio_t;

typedef struct key_dev {
    key_judge_t judge;
    uint8_t  state;
    key_gpio_t gpio;
    volatile uint8_t f_push;
    volatile uint8_t f_longpush;
    volatile uint8_t f_doubleclick;
    uint8_t  debounce_cnt;
    uint32_t longpush_time;
    uint32_t doubleclick_time;
    uint8_t (*Gpio_Read)(void *port, uint16_t pin);
} key_t;

void BSP_Key_Init(void);
void BSP_Key_Scan(key_t *key);
void BSP_Key_EasyScan(key_t *key);
key_event_t BSP_Key_GetEvent(key_t *key);

#endif /* __BSP_KEY_H__ */
