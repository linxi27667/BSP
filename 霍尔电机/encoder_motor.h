/**
 * @file    encoder_motor.h
 * @brief   电机应用层适配头文件
 * @note    对外声明当前工程中实际使用的电机对象。
 */

#ifndef __ENCODER_MOTOR_H__
#define __ENCODER_MOTOR_H__

#include "bsp_encoder_motor.h"

/* 声明当前系统存在的电机实体 (例如左轮、右轮，或 X轴、Y轴) */
extern motor_t Motor_Left; 

/* 应用层一键初始化接口 */
void App_Motor_System_Init(void);

#endif /* __ENCODER_MOTOR_H__ */
