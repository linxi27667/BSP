#ifndef __KEY_H__
#define __KEY_H__

#include "main.h"

#define KEY1_PIN    GPIO_PIN_0
#define KEY2_PIN    GPIO_PIN_1
#define KEY3_PIN    GPIO_PIN_2
#define KEY4_PIN    GPIO_PIN_0

#define KEY1_PORT    GPIOB
#define KEY2_PORT    GPIOB
#define KEY3_PORT    GPIOB
#define KEY4_PORT    GPIOA

#define KEY_PRESS    0
#define KEY_RELEASE  1

#define MAX_KEY_NUM 4
#define KEY_LONGPUSH_MINTIME 80
#define KEY_DOUBLECLICK_TIMEOUT 15
#define DEBOUNCE_CNT 10

typedef enum key_judge
{
    KEY_JUDGE_IDLE = 0,
    KEY_JUDGE_PRESS,
    KEY_JUDGE_LONGPUSH,
    KEY_JUDGE_DOUBLECLICK,
    KEY_JUDGE_RELEASE,
}key_judge_t;

typedef enum key_event
{
    KEY_EVENT_IDLE = 0,
    KEY_EVENT_PUSH,
    KEY_EVENT_LONGPUSH,
    KEY_EVENT_DOUBLECLICK
}key_event_t;

typedef struct key
{
    key_judge_t judge;

    uint8_t state;
    GPIO_TypeDef* port;
    uint16_t pin;
    volatile uint8_t f_push;
    volatile uint8_t f_longpush;
    volatile uint8_t f_doubleclick;
    uint8_t debounce_cnt;
    uint32_t longpush_time;
    uint32_t doubleclick_time;

    void (*Init_Interface)(void);
}key_t;

void Key_Init(void);
void Key_Scan(key_t *key);
void Key_EasyScan(key_t *key);
key_event_t Key_GetEvent(key_t *key);

extern TIM_HandleTypeDef htim2;
extern key_t my_key[MAX_KEY_NUM];

#endif
