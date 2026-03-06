#ifndef __STEPPER_H__
#define __STEPPER_H__

#include "bsp_stepper.h"

// 导出电机实体 (比如球杆系统的 X 轴)
extern stepper_t Stepper_X;

// 应用层初始化
void App_Stepper_System_Init(void);

#endif
