/**
 * @file    bsp_key.c
 * @brief   按键状态机核心逻辑（BSP — 纯逻辑，跨平台）
 */
#include "bsp_key.h"

void BSP_Key_Init(key_t *keys, uint8_t num)
{
    for (uint8_t i = 0; i < num; i++) {
        keys[i].judge = KEY_JUDGE_IDLE;
        keys[i].state = KEY_RELEASE;
        keys[i].f_push = 0;
        keys[i].f_longpush = 0;
        keys[i].f_doubleclick = 0;
        keys[i].debounce_cnt = 0;
        keys[i].longpush_time = 0;
        keys[i].doubleclick_time = 0;
    }
}

void BSP_Key_Scan(key_t *key, uint8_t num)
{
    for (uint8_t i = 0; i < num; i++) {
        key[i].state = key[i].Gpio_Read(key[i].gpio.port, key[i].gpio.pin);
        switch (key[i].judge) {
        case KEY_JUDGE_IDLE:
            if (key[i].state == KEY_PRESS) key[i].judge = KEY_JUDGE_PRESS;
            break;
        case KEY_JUDGE_PRESS:
            if (key[i].state == KEY_PRESS) {
                key[i].judge = KEY_JUDGE_LONGPUSH;
                key[i].longpush_time = 0;
            } else {
                key[i].judge = KEY_JUDGE_IDLE;
            }
            break;
        case KEY_JUDGE_LONGPUSH:
            if (key[i].state == KEY_PRESS) {
                key[i].longpush_time++;
                if (key[i].longpush_time >= KEY_LONGPUSH_MINTIME) {
                    key[i].longpush_time = 0;
                    key[i].judge = KEY_JUDGE_RELEASE;
                    key[i].f_longpush = KEY_EVENT_LONGPUSH;
                }
            } else {
                key[i].longpush_time = 0;
                key[i].doubleclick_time = 0;
                key[i].judge = KEY_JUDGE_DOUBLECLICK;
            }
            break;
        case KEY_JUDGE_DOUBLECLICK:
            key[i].doubleclick_time++;
            if (key[i].state == KEY_PRESS && key[i].doubleclick_time <= KEY_DOUBLECLICK_TIMEOUT) {
                key[i].judge = KEY_JUDGE_RELEASE;
                key[i].doubleclick_time = 0;
                key[i].f_doubleclick = KEY_EVENT_DOUBLECLICK;
            } else if (key[i].state == KEY_RELEASE && key[i].doubleclick_time > KEY_DOUBLECLICK_TIMEOUT) {
                key[i].judge = KEY_JUDGE_IDLE;
                key[i].doubleclick_time = 0;
                key[i].f_push = KEY_EVENT_PUSH;
            }
            break;
        case KEY_JUDGE_RELEASE:
            if (key[i].state == KEY_RELEASE) key[i].judge = KEY_JUDGE_IDLE;
            break;
        }
    }
}

void BSP_Key_EasyScan(key_t *key, uint8_t num)
{
    for (uint8_t i = 0; i < num; i++)
        key[i].state = key[i].Gpio_Read(key[i].gpio.port, key[i].gpio.pin);

    for (uint8_t i = 0; i < num; i++) {
        switch (key[i].judge) {
        case KEY_JUDGE_IDLE:
            if (key[i].state == KEY_PRESS) key[i].judge = KEY_JUDGE_PRESS;
            break;
        case KEY_JUDGE_PRESS:
            if (key[i].state == KEY_PRESS) key[i].judge = KEY_JUDGE_LONGPUSH;
            else key[i].judge = KEY_JUDGE_IDLE;
            break;
        case KEY_JUDGE_LONGPUSH:
            if (key[i].state == KEY_RELEASE) {
                key[i].f_push = 1;
                key[i].judge = KEY_JUDGE_IDLE;
            }
            break;
        default:
            key[i].judge = KEY_JUDGE_IDLE;
            break;
        }
    }
}

key_event_t BSP_Key_GetEvent(key_t *key)
{
    if (key->f_push) { key->f_push = 0; return KEY_EVENT_PUSH; }
    if (key->f_longpush) { key->f_longpush = 0; return KEY_EVENT_LONGPUSH; }
    if (key->f_doubleclick) { key->f_doubleclick = 0; return KEY_EVENT_DOUBLECLICK; }
    return KEY_EVENT_IDLE;
}
