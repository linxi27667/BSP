#include "bsp_key.h"

#define KEY1_PIN    DL_GPIO_PIN_0
#define KEY2_PIN    DL_GPIO_PIN_1
#define KEY3_PIN    DL_GPIO_PIN_2
#define KEY4_PIN    DL_GPIO_PIN_0

#define KEY1_PORT   (GPIOB)
#define KEY2_PORT   (GPIOB)
#define KEY3_PORT   (GPIOB)
#define KEY4_PORT   (GPIOA)

static key_t g_keys[MAX_KEY_NUM];

static uint8_t HW_Gpio_Read(void *port, uint16_t pin) {
    return DL_GPIO_readPins((GPIO_RegDef *)port, pin) ? KEY_RELEASE : KEY_PRESS;
}

void BSP_Key_Init(void) {
    g_keys[0].gpio.port = KEY1_PORT; g_keys[0].gpio.pin = KEY1_PIN;
    g_keys[1].gpio.port = KEY2_PORT; g_keys[1].gpio.pin = KEY2_PIN;
    g_keys[2].gpio.port = KEY3_PORT; g_keys[2].gpio.pin = KEY3_PIN;
    g_keys[3].gpio.port = KEY4_PORT; g_keys[3].gpio.pin = KEY4_PIN;

    for (uint8_t i = 0; i < MAX_KEY_NUM; i++) {
        g_keys[i].judge = KEY_JUDGE_IDLE;
        g_keys[i].state = KEY_RELEASE;
        g_keys[i].f_push = 0;
        g_keys[i].f_longpush = 0;
        g_keys[i].f_doubleclick = 0;
        g_keys[i].debounce_cnt = 0;
        g_keys[i].longpush_time = 0;
        g_keys[i].doubleclick_time = 0;
        g_keys[i].Gpio_Read = HW_Gpio_Read;
    }
}

void BSP_Key_Scan(key_t *key) {
    uint8_t i;
    for (i = 0; i < MAX_KEY_NUM; i++) {
        key[i].state = key[i].Gpio_Read(key[i].gpio.port, key[i].gpio.pin);
        switch (key[i].judge) {
        case KEY_JUDGE_IDLE:
            if (key[i].state == KEY_PRESS) key[i].judge = KEY_JUDGE_PRESS;
            break;
        case KEY_JUDGE_PRESS:
            if (key[i].state == KEY_PRESS) { key[i].judge = KEY_JUDGE_LONGPUSH; key[i].longpush_time = 0; }
            else key[i].judge = KEY_JUDGE_IDLE;
            break;
        case KEY_JUDGE_LONGPUSH:
            if (key[i].state == KEY_PRESS) {
                key[i].longpush_time++;
                if (key[i].longpush_time >= KEY_LONGPUSH_MINTIME) {
                    key[i].longpush_time = 0;
                    key[i].judge = KEY_JUDGE_RELEASE;
                    key[i].f_longpush = KEY_EVENT_LONGPUSH;
                }
            } else { key[i].longpush_time = 0; key[i].doubleclick_time = 0; key[i].judge = KEY_JUDGE_DOUBLECLICK; }
            break;
        case KEY_JUDGE_DOUBLECLICK:
            key[i].doubleclick_time++;
            if (key[i].state == KEY_PRESS && key[i].doubleclick_time <= KEY_DOUBLECLICK_TIMEOUT) {
                key[i].judge = KEY_JUDGE_RELEASE; key[i].doubleclick_time = 0; key[i].f_doubleclick = KEY_EVENT_DOUBLECLICK;
            } else if (key[i].state == KEY_RELEASE && key[i].doubleclick_time > KEY_DOUBLECLICK_TIMEOUT) {
                key[i].judge = KEY_JUDGE_IDLE; key[i].doubleclick_time = 0; key[i].f_push = KEY_EVENT_PUSH;
            }
            break;
        case KEY_JUDGE_RELEASE:
            if (key[i].state == KEY_RELEASE) key[i].judge = KEY_JUDGE_IDLE;
            break;
        }
    }
}

void BSP_Key_EasyScan(key_t *key) {
    uint8_t i;
    for (i = 0; i < MAX_KEY_NUM; i++) key[i].state = key[i].Gpio_Read(key[i].gpio.port, key[i].gpio.pin);
    for (i = 0; i < MAX_KEY_NUM; i++) {
        switch (key[i].judge) {
        case 0: if (key[i].state == KEY_PRESS) key[i].judge = 1; break;
        case 1: if (key[i].state == KEY_PRESS) key[i].judge = 2; else key[i].judge = 0; break;
        case 2: if (key[i].state == KEY_RELEASE) { key[i].f_push = 1; key[i].judge = 0; } break;
        }
    }
}

key_event_t BSP_Key_GetEvent(key_t *key) {
    if (key->f_push) { key->f_push = 0; return KEY_EVENT_PUSH; }
    if (key->f_longpush) { key->f_longpush = 0; return KEY_EVENT_LONGPUSH; }
    if (key->f_doubleclick) { key->f_doubleclick = 0; return KEY_EVENT_DOUBLECLICK; }
    return KEY_EVENT_IDLE;
}
