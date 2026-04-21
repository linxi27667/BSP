#ifndef __ENCODER_MOTOR_H__
#define __ENCODER_MOTOR_H__

#include "bsp_encoder_motor.h"

/* ============ 左电机硬件配置 ============ */
#define MOTOR_LEFT_PWM_TIMER        TIMERG0_INST
#define MOTOR_LEFT_PWM_CHANNEL      DL_TIMER_CC_0_INDEX
#define MOTOR_LEFT_ENC_TIMER        TIMERG1_INST
#define MOTOR_LEFT_DIR1_PORT        GPIOB
#define MOTOR_LEFT_DIR1_PIN         DL_GPIO_PIN_12
#define MOTOR_LEFT_DIR2_PORT        GPIOB
#define MOTOR_LEFT_DIR2_PIN         DL_GPIO_PIN_13

/* ============ 业务接口声明 ============ */
extern motor_t Motor_Left;
void App_Motor_System_Init(void);

#endif
