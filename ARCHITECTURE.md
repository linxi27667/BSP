# 嵌入式三层分离架构

> 驱动与逻辑跨平台复用，调度方式按需切换。

---

## 核心理念

**驱动层和逻辑层保持不动，只改变最顶层的调度方式。**

无论底层是裸机还是 FreeRTOS，驱动层（Drivers）和逻辑层（Logic）的代码一字不改。裸机的外壳是 `main.c` 里的 `while(1)`，RTOS 的外壳是 `Tasks/` 文件夹里的任务函数。

---

## 架构分层

```
┌─────────────────────────────────────────────────────────┐
│                    调度层 (Scheduler)                    │
│  裸机: main.c 的 while(1) + 时标轮询                    │
│  RTOS: Tasks/ 文件夹 + 任务外壳 + 消息队列               │
├─────────────────────────────────────────────────────────┤
│                    逻辑层 (Logic)                        │
│  Logic/ 文件夹，2文件模式 (.c + .h)                      │
│  纯C业务逻辑：PID运算、状态机、协议解析                    │
│  不关心自己是在裸机 while(1) 里还是在 RTOS 任务里运行     │
├─────────────────────────────────────────────────────────┤
│                    驱动层 (Driver)                       │
│  Drivers/ 文件夹，4文件模式 (bsp_xxx + app_xxx)          │
│  BSP: 抽象对象结构体 + 函数指针，绝对硬件无关             │
│  APP: 唯一硬件解禁区，负责引脚分配和硬件绑定              │
└─────────────────────────────────────────────────────────┘
```

---

## 目录结构

### 裸机版

```
Project/
├── Drivers/
│   ├── bsp_motor.c      BSP 抽象层（纯逻辑，不含硬件头文件）
│   ├── bsp_motor.h
│   ├── app_motor.c      APP 硬件绑定层（唯一硬件解禁区）
│   └── app_motor.h
├── Logic/
│   ├── logic_control.c  纯C逻辑（PID、状态机）
│   ├── logic_control.h
│   ├── logic_protocol.c  协议解析
│   └── logic_protocol.h
└── main.c               时标轮询调度入口
```

### RTOS版

```
Project/
├── Drivers/              ← 与裸机版完全相同，直接复用
├── Logic/                ← 与裸机版完全相同，直接复用
├── Tasks/
│   ├── task_control.c    电机控制任务外壳
│   ├── task_control.h
│   ├── task_comm.c       通信任务外壳
│   └── task_comm.h
└── main.c               FreeRTOS 任务创建入口
```

---

## 调度方式对比

### 裸机：时标轮询

```c
/* main.c */
while (1) {
    if (Timer_10ms_Flag) {          // 时标由 SysTick 中断产生
        Timer_10ms_Flag = 0;

        App_Sensor_GetRaw(&raw_data);       // 1. 驱动层：获取数据
        Logic_Control_Process(raw_data);    // 2. 逻辑层：运算
        App_Motor_Update();                 // 3. 驱动层：输出
    }

    if (Timer_100ms_Flag) {
        Timer_100ms_Flag = 0;
        Logic_Update_OLED_Display();        // 低频任务
    }
}
```

### RTOS：任务外壳

```c
/* task_control.c */
void Task_MotorControl(void *pv) {
    TickType_t xLast = xTaskGetTickCount();
    for(;;) {
        vTaskDelayUntil(&xLast, pdMS_TO_TICKS(10));    // 精确周期

        App_Sensor_GetRaw(&raw_data);       // 驱动层（同裸机）
        Logic_Control_Process(raw_data);    // 逻辑层（同裸机）
        App_Motor_Update();                 // 驱动层（同裸机）
    }
}
```

---

## 架构优势

### 1. 代码 100% 跨平台复用

驱动层（Drivers）和逻辑层（Logic）在裸机和 RTOS 工程之间可以直接拷贝，不需要改一行代码。

| 场景 | 不分层 | 三层分离 |
|------|--------|----------|
| 裸机 → RTOS | 重写整个项目 | 只加 Tasks/ 文件夹 |
| RTOS → 裸机 | 删掉所有 vTaskDelay/Queue | 只改 main.c 调度循环 |
| STM32 → ESP32 | 逐文件改引脚 | 只改 app_xxx.c 绑定层 |
| 电赛中途切 RTOS | 几小时 | 10 分钟 |

### 2. 排错极其精准

出问题时你知道去哪查：

| 症状 | 检查层级 | 常见原因 |
|------|----------|----------|
| 算错了、逻辑不对 | Logic/ | 公式写错、状态机状态遗漏 |
| 没有波形/无信号 | Drivers/ | 引脚配错、时钟未使能 |
| 不动了、卡死 | Scheduler/Tasks/ | 死锁、任务饿死、时标丢失 |
| 换芯片后编译失败 | app_xxx.c | 硬件头文件和引脚绑定需调整 |

### 3. BSP 与 APP 彻底解耦

BSP 层（`bsp_xxx.c`）不包含任何芯片外设头文件，通过函数指针抽象硬件操作。APP 层（`app_xxx.c`）是唯一可以包含 `stm32f4xx_hal.h` / `esp_rom_gpio.h` 等硬件头文件的地方。

**效果**：换芯片时只需要重写 `app_xxx.c`，`bsp_xxx.c` 和 `Logic/` 全部不动。

```
换芯片 STM32 → GD32:
  bsp_xxx.c  ← 不动
  logic_xxx.c ← 不动
  app_xxx.c  ← 重写硬件绑定（唯一要改的）
```

### 4. 裸机也能模拟多任务

通过 SysTick 时标 + 状态机，裸机可以实现类似多任务的效果，避免面条代码。1ms 处理紧急保护，10ms 跑控制循环，100ms 刷新显示——每个模块知道自己该在什么时候执行。

### 5. RTOS 任务职责单一

每个任务只做一件事：等待 → 调驱动 → 调逻辑 → 输出。任务之间通过消息队列通信，禁止共享全局变量。任务不会饿死，因为每个任务循环中都有阻塞点（`vTaskDelayUntil` 或 `xQueueReceive`）。

---

## 设计模式速查

### 4文件驱动模式

```
bsp_xxx.h/c  ← 抽象对象结构体 + 函数指针方法
app_xxx.h/c  ← 硬件函数(HW_前缀) + 对象实例化 + 对外API
```

### 2文件逻辑模式

```
logic_xxx.h/c  ← 纯C函数，只能调用驱动层API
```

### 调度模式

```
裸机: main.c 的 while(1) + 时标标志位
RTOS: task_xxx.c 的任务函数 + vTaskDelayUntil + Queue
```

---

## 命名规范

| 层级 | 文件前缀 | 函数风格 | 示例 |
|------|----------|----------|------|
| BSP 抽象 | `bsp_` | `BSP_Motor_SetSpeed()` | `bsp_motor.c` |
| APP 绑定 | `app_` | `App_Motor_Init()` | `app_motor.c` |
| 硬件底层 | - | `HW_Gpio_Write()` | `app_motor.c` 内 static |
| 业务逻辑 | `logic_` | `Logic_PID_Compute()` | `logic_control.c` |
| 任务外壳 | `task_` | `Task_MotorControl()` | `task_control.c` |

---

## 何时用裸机，何时用 RTOS

| 维度 | 裸机 | FreeRTOS |
|------|------|----------|
| 外设数量 | 1-3 个 | 4 个以上 |
| 实时性要求 | 单一控制回路 | 多回路并发 |
| 通信协议 | 简单串口/AT指令 | WiFi + MQTT + BLE 同时运行 |
| Flash/RAM | 极度受限 (32K以下) | 资源充裕 (64K以上) |
| 开发速度 | 快，无调试器也能跑 | 需要 RTOS 调试经验 |
| 典型场景 | 电赛基础题、简单传感器采集 | 双轮平衡车、物联网终端 |
