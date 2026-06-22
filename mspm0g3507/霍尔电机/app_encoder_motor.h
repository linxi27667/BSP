/**
 * @file    app_encoder_motor.h
 * @brief   霍尔编码器电机应用层声明（硬件绑定 + 业务逻辑入口）
 */
#ifndef APP_ENCODER_MOTOR_H
#define APP_ENCODER_MOTOR_H

#include "bsp_encoder_motor.h"

/* ============ 左电机硬件配置 ============ */
#define MOTOR_LEFT_PWM_TIMER        TIMG7
#define MOTOR_LEFT_PWM_CHANNEL      0
#define MOTOR_LEFT_ENC_TIMER        TIMG8
#define MOTOR_LEFT_DIR1_PORT        GPIOA
#define MOTOR_LEFT_DIR1_PIN         DL_GPIO_PIN_14
#define MOTOR_LEFT_DIR2_PORT        GPIOA
#define MOTOR_LEFT_DIR2_PIN         DL_GPIO_PIN_15

/* ============ 业务接口声明 ============ */
extern bsp_motor_t App_Motor_Left;

void App_Motor_System_Init(void);
void App_Motor_Set_Speed(int32_t speed);
void App_Motor_Forward(int32_t speed);
void App_Motor_Backward(int32_t speed);
void App_Motor_Stop(void);
void App_Motor_Update_Status(void);

#endif /* APP_ENCODER_MOTOR_H */
