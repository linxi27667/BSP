#include "bsp_key.h"

key_t my_key[MAX_KEY_NUM] = 
{
    [0] = { .port = KEY1_PORT, .pin = KEY1_PIN, .judge = KEY_JUDGE_IDLE, .state = KEY_RELEASE},
    [1] = { .port = KEY2_PORT, .pin = KEY2_PIN, .judge = KEY_JUDGE_IDLE, .state = KEY_RELEASE},
    [2] = { .port = KEY3_PORT, .pin = KEY3_PIN, .judge = KEY_JUDGE_IDLE, .state = KEY_RELEASE},
    [3] = { .port = KEY4_PORT, .pin = KEY4_PIN, .judge = KEY_JUDGE_IDLE, .state = KEY_RELEASE},
};

void Key_Init(void)
{
    HAL_TIM_Base_Start_IT(&htim6);

    /*__HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    __HAL_RCC_GPIOD_CLK_ENABLE();

    GPIO_InitStruct.Pin = KEY1_PIN | KEY2_PIN | KEY3_PIN | KEY4_PIN;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;

    HAL_GPIO_Init(KEY1_PORT, &GPIO_InitStruct);
    HAL_GPIO_Init(KEY2_PORT, &GPIO_InitStruct);
    HAL_GPIO_Init(KEY3_PORT, &GPIO_InitStruct);
    HAL_GPIO_Init(KEY4_PORT, &GPIO_InitStruct);
    */
}

void Key_Scan(key_t *key)
{
    uint8_t i;
    for(i = 0; i < MAX_KEY_NUM; i++)
    {
        key[i].state = HAL_GPIO_ReadPin(key[i].port, key[i].pin);
        switch(key[i].judge)
        {
            case KEY_JUDGE_IDLE:
                if(key[i].state == KEY_PRESS)
                {
                        #if (DEBUG_MODE == 1)
                        elog_i("key", "key %d push GO TO KEY_JUDGE_PRESS", i);
                        #endif
                        key[i].judge = KEY_JUDGE_PRESS;
                }
                break;

            case KEY_JUDGE_PRESS:
                if(key[i].state == KEY_PRESS)
                {
                    #if (DEBUG_MODE == 1)
                    elog_i("key", "key %d push GO TO KEY_JUDGE_LONGPUSH", i);
                    #endif
                    key[i].judge = KEY_JUDGE_LONGPUSH;   
                    key[i].longpush_time = 0;
                }
                else
                {
                    #if (DEBUG_MODE == 1)
                    elog_e("key", "key %d release GO TO KEY_JUDGE_IDLE", i);
                    #endif
                    key[i].judge = KEY_JUDGE_IDLE;
                }
                break;

            case KEY_JUDGE_LONGPUSH:
                if(key[i].state == KEY_PRESS) 
                {
                    key[i].longpush_time++;
                    if(key[i].longpush_time >= KEY_LONGPUSH_MINTIME)
                    {
                        key[i].longpush_time = 0;
                        key[i].judge = KEY_JUDGE_RELEASE;
                        key[i].f_longpush = KEY_EVENT_LONGPUSH;
                        #if (DEBUG_MODE == 1)
                        elog_a("key", "key %d KEY_EVENT_LONGPUSH", i);
                        #endif
                    }
                }
                else if(key[i].state == KEY_RELEASE)
                {
                    key[i].longpush_time = 0;
                    key[i].doubleclick_time = 0;
                    key[i].judge = KEY_JUDGE_DOUBLECLICK;
                    #if (DEBUG_MODE == 1)
                    elog_i("key", "key %d GO TO KEY_JUDGE_DOUBLECLICK", i);
                    #endif
                }
                break;

            case KEY_JUDGE_DOUBLECLICK:
                key[i].doubleclick_time++; 
                if(key[i].state == KEY_PRESS && key[i].doubleclick_time <= KEY_DOUBLECLICK_TIMEOUT)
                {
                    key[i].judge = KEY_JUDGE_RELEASE;
                    key[i].doubleclick_time = 0;
                    key[i].f_doubleclick = KEY_EVENT_DOUBLECLICK;
                    #if (DEBUG_MODE == 1)
                    elog_a("key", "key %d KEY_EVENT_DOUBLECLICK", i);
                    #endif
                }
                else if(key[i].state == KEY_RELEASE && key[i].doubleclick_time > KEY_DOUBLECLICK_TIMEOUT)
                {
                    key[i].judge = KEY_JUDGE_IDLE;
                    key[i].doubleclick_time = 0;
                    key[i].f_push = KEY_EVENT_PUSH;
                    #if (DEBUG_MODE == 1)
                    elog_a("key", "key %d KEY_EVENT_PUSH", i);
                    #endif
                }
                break;

            case KEY_JUDGE_RELEASE:
                if(key[i].state == KEY_RELEASE)
                {
                    key[i].judge = KEY_JUDGE_IDLE;
                    #if (DEBUG_MODE == 1)
                    elog_a("key", "key %d release KEY_RELEASE", i);
                    #endif
                }
                break;
        }
    }
}

void Key_EasyScan(key_t *key) //简单比赛使用
{
    key[0].state = HAL_GPIO_ReadPin(key[0].port, key[0].pin);
    key[1].state = HAL_GPIO_ReadPin(key[1].port, key[1].pin);
    key[2].state = HAL_GPIO_ReadPin(key[2].port, key[2].pin);
    key[3].state = HAL_GPIO_ReadPin(key[3].port, key[3].pin);

     uint8_t i;
    for(i = 0; i < MAX_KEY_NUM; i++)
    {
        switch(key[i].judge)
        {
            case 0:
                if(key[i].state == KEY_PRESS)
                {
                    key[i].judge = 1;
                }
                break;

            case 1:
                if(key[i].state == KEY_PRESS)
                {
                    key[i].judge = 2;   
                }
                else
                {
                    key[i].judge = 0;
                }
                break;

             case 2:
                if(key[i].state == KEY_RELEASE)
                {
                 key[i].f_push = 1;
                 key[i].judge = 0;
                }
                 break;
        }
    }
}

key_event_t Key_GetEvent(key_t *key)
{
    if(key->f_push)
    {
        key->f_push = 0;
        return KEY_EVENT_PUSH;
    }
    if(key->f_longpush)
    {
        key->f_longpush = 0;
        return KEY_EVENT_LONGPUSH;
    }
    if(key->f_doubleclick)
    {
        key->f_doubleclick = 0;
        return KEY_EVENT_DOUBLECLICK;
    }
    return KEY_EVENT_IDLE;
}

/*void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
    if(htim->Instance == TIM2)
    {
        app_key_instance1(key);
    }
}*/


