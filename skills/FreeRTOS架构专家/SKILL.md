---
name: FreeRTOS架构专家
description: FreeRTOS任务架构、优先级分配、栈管理、队列/信号量/任务通知、ESP32双核调度。TRIGGER when: xTaskCreate/Queue/Semaphore或RTOS代码。
---
# FreeRTOS 架构专家 Skill

## 定位
本Skill是嵌入式领域的FreeRTOS十年经验架构师养成指南，涵盖从入门到精通的所有核心知识点，特别针对ESP32、STM32等主流MCU平台，提供实战级别的任务架构设计、优先级分配、栈空间管理、资源优化等经验总结。

---

## 一、FreeRTOS 核心概念速查

### 1.1 任务状态机

```
                    ┌─────────────┐
                    │   Running   │ ← 当前运行的任务
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          ↓                ↓                ↓
    ┌──────────┐    ┌────────────┐    ┌──────────┐
    │  Ready   │    │   Blocked  │    │ Suspended│
    │ 就绪态   │    │   阻塞态   │    │  挂起态   │
    └──────────┘    └────────────┘    └──────────┘
```

**状态转换规则：**
- Running → Ready：时间片用完或更高优先级任务抢占
- Running → Blocked：调用 `vTaskDelay()`、`ulTaskNotifyTake()` 等待事件
- Ready → Running：调度器选择该任务执行
- Any → Suspended：调用 `vTaskSuspend()`
- Suspended → Ready：调用 `vTaskResume()`

### 1.2 调度算法

| 调度方式 | 说明 |
|---------|------|
| 抢占式优先级调度 | 高优先级任务可抢占低优先级任务（默认） |
| 时间片轮转 | 同优先级任务按时间片轮转（configUSE_TIME_SLICING） |
| 协程模式 | 轻量级协作式多任务（已过时，不推荐） |

**ESP32默认配置：**
```c
#define configUSE_PREEMPTION    1    // 抢占式调度
#define configUSE_TIME_SLICING   1    // 开启时间片
#define configIDLE_SHOULD_YIELD  1    // Idle任务让出时间片
```

### 1.3 关键配置参数

```c
/* FreeRTOSConfig.h 核心配置 */
#define configMAX_PRIORITIES        25          // 最大优先级数量
#define configMINIMAL_STACK_SIZE     128         // 最小栈大小(字)
#define configSTACK_DEPTH_TYPE       uint16_t     // 栈深度类型
#define configUSE_16_BIT_TICKS       0           // 0=32位Tick
#define configENABLE_BACKWARD_COMPAT 1           // 兼容旧API

/* ESP32特定配置 */
#define configNUM_THREAD_LOCAL_STORAGE_POINTERS 5  // 线程本地存储指针数
#define configTASK_NOTIFICATION_ARRAY_ENTRIES    5  // 任务通知数组大小
```

---

## 二、任务创建与管理

### 2.1 任务创建三要素

```c
BaseType_t xTaskCreate(
    TaskFunction_t pvTaskCode,     // 1. 任务函数（必须返回void）
    const char *pcName,             // 2. 任务名称（用于调试）
    uint32_t ulStackDepth,         // 3. 栈深度（字，不是字节！）
    void *pvParameters,            //    传递给任务的参数
    UBaseType_t uxPriority,        //    优先级
    TaskHandle_t *pxCreatedTask     //    任务句柄（输出）
);
```

**ESP32栈大小计算：**
```c
// 栈大小(字节) = ulStackDepth * sizeof(StackType_t)
// ESP32中 StackType_t = uint32_t (4字节)

// 4096字栈 = 4096 * 4 = 16384字节 = 16KB
xTaskCreate(task_func, "task", 4096, NULL, 3, NULL);
```

### 2.2 任务删除与清理

```c
/* 删除任务 */
void vTaskDelete(TaskHandle_t xTaskToDelete);

/* 删除自己 */
vTaskDelete(NULL);

/* 栈溢出钩子（必须启用configCHECK_FOR_STACK_OVERFLOW） */
void vApplicationStackOverflowHook(TaskHandle_t xTask, char *pcTaskName);
```

### 2.3 任务优先级

**FreeRTOS优先级规则：**
- 数字越小，优先级越低
- 优先级0是最低优先级（idle任务）
- 最大优先级 = configMAX_PRIORITIES - 1

**ESP32优先级映射：**
```c
// ESP32使用硬件优先级，配置configMAX_PRIORITIES=25
// 但实际可用的优先级受芯片限制

// 推荐优先级分配：
Priority 0-3:   系统保留（Idle、Timer等）
Priority 4-10:  应用任务
Priority 11-24: 最高优先级（根据芯片）
```

---

## 三、任务间通信与同步

### 3.1 队列（Queue）

```c
/* 创建队列 */
QueueHandle_t xQueueCreate(UBaseType_t uxQueueLength, UBaseType_t uxItemSize);

/* 发送（带超时） */
BaseType_t xQueueSend(QueueHandle_t xQueue,
                      const void *pvItemToQueue,
                      TickType_t xTicksToWait);

/* 接收（带超时） */
BaseType_t xQueueReceive(QueueHandle_t xQueue,
                         void *pvBuffer,
                         TickType_t xTicksToWait);

/* 中断安全版本 */
BaseType_t xQueueSendFromISR(QueueHandle_t xQueue,
                             const void *pvItemToQueue,
                             BaseType_t *pxHigherPriorityTaskWoken);

BaseType_t xQueueReceiveFromISR(QueueHandle_t xQueue,
                                void *pvBuffer,
                                BaseType_t *pxHigherPriorityTaskWoken);
```

**队列使用场景：**
```c
// 生产者-消费者模式
QueueHandle_t data_queue;

void producer_task(void *arg) {
    int data = 0;
    while (1) {
        xQueueSend(data_queue, &data, portMAX_DELAY);
        data++;
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

void consumer_task(void *arg) {
    int received;
    while (1) {
        if (xQueueReceive(data_queue, &received, portMAX_DELAY) == pdTRUE) {
            ESP_LOGI(TAG, "Received: %d", received);
        }
    }
}
```

### 3.2 信号量（Semaphore）

```c
/* 二值信号量（同步用） */
SemaphoreHandle_t xSemaphoreCreateBinary(void);
SemaphoreHandle_t xSemaphoreCreateBinaryStatic(&semaphoreBuffer);

/* 互斥信号量（保护共享资源） */
SemaphoreHandle_t xSemaphoreCreateMutex(void);
SemaphoreHandle_t xSemaphoreCreateMutexStatic(&mutexBuffer);

/* 计数信号量（资源计数） */
SemaphoreHandle_t xSemaphoreCreateCounting(UBaseType_t uxMaxCount,
                                           UBaseType_t uxInitialCount);

/* 获取/释放 */
BaseType_t xSemaphoreTake(SemaphoreHandle_t xSemaphore, TickType_t xTicksToWait);
BaseType_t xSemaphoreGive(SemaphoreHandle_t xSemaphore);
BaseType_t xSemaphoreGiveFromISR(SemaphoreHandle_t xSemaphore,
                                 BaseType_t *pxHigherPriorityTaskWoken);
```

**互斥信号量保护共享资源：**
```c
SemaphoreHandle_t uart_mutex;

void uart_print(const char *str) {
    xSemaphoreTake(uart_mutex, portMAX_DELAY);
    printf("%s", str);
    xSemaphoreGive(uart_mutex);
}

void task1(void *arg) {
    while (1) {
        uart_print("Task 1 printing\n");
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}
```

### 3.3 任务通知（Task Notification）

**优势：比信号量更快、更轻量**

```c
/* 发送通知（可累加） */
BaseType_t xTaskNotifyGive(TaskHandle_t xTaskToNotify);
uint32_t ulTaskNotifyTake(BaseType_t xClearCountOnExit, TickType_t xTicksToWait);

/* 通知（带事件值） */
BaseType_t xTaskNotify(TaskHandle_t xTaskToNotify,
                       uint32_t ulValue,
                       eNotifyAction eAction);

/* 等待通知 */
BaseType_t xTaskNotifyWait(uint32_t ulBitsToClearOnEnter,
                           uint32_t ulBitsToClearOnExit,
                           uint32_t *pulNotificationValue,
                           TickType_t xTicksToWait);
```

**典型用法：中断与任务同步**
```c
// 任务端：等待中断通知
void uart_task(void *arg) {
    while (1) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);  // 阻塞等待
        // 处理UART数据
    }
}

// 中断端：发送通知
void UART_ISR(void) {
    BaseType_t higher_priority_woken = pdFALSE;
    xTaskNotifyGiveFromISR(uart_task_handle, &higher_priority_woken);
    portYIELD_FROM_ISR(higher_priority_woken);
}
```

---

## 四、定时器服务

### 4.1 软件定时器

```c
/* 创建定时器 */
TimerHandle_t xTimerCreate(const char *pcTimerName,
                          TickType_t xTimerPeriodInTicks,
                          UBaseType_t uxAutoReload,
                          void *pvTimerID,
                          TimerCallbackFunction_t pxCallbackFunction);

/* 启动/停止 */
BaseType_t xTimerStart(TimerHandle_t xTimer, TickType_t xTicksToWait);
BaseType_t xTimerStop(TimerHandle_t xTimer, TickType_t xTicksToWait);
BaseType_t xTimerReset(TimerHandle_t xTimer, TickType_t xTicksToWait);

/* 定时器ID（用于区分多个定时器） */
void vTimerSetTimerID(TimerHandle_t xTimer, void *pvNewID);
void *pvTimerGetTimerID(TimerHandle_t xTimer);
```

**示例：周期任务 vs 定时器**
```c
// 方式1：vTaskDelay周期任务（推荐用于简单场景）
void periodic_task(void *arg) {
    while (1) {
        do_something();
        vTaskDelay(pdMS_TO_TICKS(1000));  // 阻塞，不占用CPU
    }
}

// 方式2：软件定时器（适合需要动态管理）
TimerHandle_t my_timer = xTimerCreate("my_timer",
                                       pdMS_TO_TICKS(1000),
                                       pdTRUE,  // 自动重载
                                       NULL,
                                       timer_callback);

void timer_callback(TimerHandle_t xTimer) {
    do_something();  // 不能使用阻塞调用
}
```

---

## 五、内存管理

### 5.1 堆内存分配策略

| 策略 | 文件 | 特点 | 适用场景 |
|------|------|------|----------|
| heap_1 | 简单，不允许释放 | 永不删除任务 | 最小系统 |
| heap_2 | 允许释放，不合并 | 频繁创建删除 | 通用嵌入式 |
| heap_3 | 线程安全包装 | 调用malloc/free | 兼容旧代码 |
| heap_4 | 首次适配+合并 | 最佳匹配 | **ESP32默认** |
| heap_5 | heap_4+分段 | 支持不连续内存 | 大型嵌入式 |

### 5.2 ESP32内存布局

```c
// ESP32双核内存分布（512KB SRAM per core）
// IRAM: 128KB (指令RAM)
// DRAM: 128KB (数据RAM)
// DIRAM: 32KB (片上共享RAM)
// FLASH: 4MB

// 配置项
#define configESP_DRAM_SIZE     (0x20000)  // 128KB
#define configTOTAL_HEAP_SIZE   (1024 * 1024)  // 堆总大小
```

### 5.3 动态内存注意事项

```c
/* ✅ 推荐：使用静态分配代替动态分配 */
StaticTask_t xTaskBuffer;
StaticTask_t xTaskBufferArray[10];
StackType_t xStack[4096];

TaskHandle_t xTaskCreateStatic(task_func,
                               "task",
                               4096,
                               NULL,
                               3,
                               xStack,
                               &xTaskBuffer);

/* ✅ 推荐：创建队列时指定缓冲区 */
QueueHandle_t xQueueCreateStatic(qlen, item_size, qstorage, qbuf);

/* ⚠️ 避免：在中断或高优先级任务中分配大内存 */
```

---

## 六、ESP32-FreeRTOS 特定优化

### 6.1 双核调度

```c
// ESP32有两个CPU核心
// Core 0: 通常用于WiFi/BT协议栈
// Core 1: 应用任务

// 创建任务时指定核心
xTaskCreatePinnedToCore(task_func, "task", 4096, NULL, 3, NULL, 1);  // Core 1

// 或者使用宏
#if CONFIG_FREERTOS_UNICORE
    #define PRO_CPU_NUM 0
#else
    #define PRO_CPU_NUM 1
#endif
```

**核心分配建议：**
| 核心 | 任务 | 说明 |
|:----:|------|------|
| Core 0 | WiFi/BT任务、系统任务 | 协议栈需要 |
| Core 1 | 应用任务 | 用户代码 |

### 6.2 _tick烙函数

```c
// ESP32使用Tickless低功耗模式
// 配置项
#define configUSE_TICKLESS_IDLE       1
#define configEXPECTED_IDLE_TIME_BEFORE_SLEEP 2

// 自定义Tickless钩子
void vApplicationSleep(TickType_t xExpectedIdleTime) {
    if (gpio_get_level(GPIO_WAKEUP) == 0) {
        return;  // 有唤醒源，不休眠
    }
    esp_light_sleep_start();
}
```

### 6.3 中断优先级

```c
// ESP32中断优先级配置
// 优先级0-15（数字越小优先级越高）
// 优先级5-15会调用portYIELD_FROM_ISR

#define configMAX_API_CALL_INTERRUPT_PRIORITY    5

// 低于此优先级的ISR可以调用FreeRTOS API
// 高于此优先级的ISR不能调用任何FreeRTOS API
```

---

## 七、任务架构设计模式

### 7.1 分层架构（推荐）

```
┌─────────────────────────────────────────────────────────────────┐
│                      分层任务架构                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Priority N: 中断层 (最高实时性)                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  ISR/Callback: UART_DMA, SPI, I2C, Timer              │    │
│  │  - 只更新标志位/队列，不做复杂处理                       │    │
│  │  - 使用FromISR版本API                                   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                  │
│  Priority 3-4: 驱动层 (高优先级)                                │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Device_Refresh_Task                                     │    │
│  │  - 100ms周期刷新GPIO                                     │    │
│  │  - 读取标志位 → 控制硬件                                 │    │
│  │  - **实时性直接影响用户体验**                             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                  │
│  Priority 5-6: 感知层 (中等优先级)                              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Sensor_Task: ADC采样、传感器融合                        │    │
│  │  Communication_Task: 协议解析                            │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                  │
│  Priority 7-8: 业务层 (普通优先级)                             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Business_Task: 状态机、业务逻辑                         │    │
│  │  Display_Task: UI刷新、屏幕更新                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                  │
│  Priority 9-10: 通信层 (低优先级)                              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Heartbeat_Task: 心跳保活                                │    │
│  │  Log_Task: 日志上报                                     │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                  │
│  Priority 0: Idle (系统保留)                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  vApplicationIdleTask: 清理资源、统计CPU                 │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 7.2 生产者-消费者模式

```c
QueueHandle_t data_queue;

void producer_task(void *arg) {
    static uint32_t count = 0;
    while (1) {
        sensor_data_t data = read_sensor();
        xQueueSend(data_queue, &data, portMAX_DELAY);
        ESP_LOGD(TAG, "Produced: %lu", count++);
    }
}

void consumer_task(void *arg) {
    sensor_data_t data;
    while (1) {
        if (xQueueReceive(data_queue, &data, pdMS_TO_TICKS(1000)) == pdTRUE) {
            process_data(&data);
        }
    }
}
```

### 7.3 Flag-driven架构（推荐物联网场景）

```c
/* 全局设备标志位 */
volatile device_flags_t g_device_flags = {
    .light = {OFF, OFF, OFF},
    .relay = {OFF, OFF, OFF},
    .servo = {SERVO_0, SERVO_0, SERVO_0}
};

/* ESP-NOW中断回调：只更新标志位 */
void esp_now_recv_cb(const uint8_t *mac, const uint8_t *data, int len) {
    iot_cmd_t *cmd = (iot_cmd_t *)data;
    if (cmd->type == CMD_SET_LIGHT) {
        g_device_flags.light[cmd->index] = cmd->value ? ON : OFF;
    }
}

/* 刷新任务：统一刷新GPIO */
void refresh_task(void *arg) {
    while (1) {
        for (int i = 0; i < LIGHT_COUNT; i++) {
            gpio_set_level(light_gpio[i], g_device_flags.light[i]);
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}
```

---

## 八、栈空间分配经验值

### 8.1 栈大小估算原则

```
实际需求 = 函数调用深度 × 最大局部变量 + 中断嵌套 × 中断栈需求 + 安全余量(30%)
```

### 8.2 典型任务栈需求

| 任务类型 | 最小栈 | 推荐栈 | 典型函数开销 |
|---------|:------:|:------:|-------------|
| Idle任务 | 256 | **512** | 几乎无 |
| 定时器回调 | 256 | **512** | printf开销大 |
| 简单传感器 | 1024 | **2048** | ADC/I2C读取 |
| 通信任务 | 2048 | **3072** | ESP-NOW/WiFi |
| GPIO刷新 | 2048 | **4096** | 循环打印 |
| 屏幕刷新 | 2048 | **4096** | LVGL需求大 |
| AI语音处理 | 4096 | **8192** | JSON解析 |
| UART事件 | 8192 | **16384** | cJSON + 队列 |

### 8.3 栈溢出检测

```c
/* 启用栈溢出检测（必须！） */
#define configCHECK_FOR_STACK_OVERFLOW    2  // 1=简单检测，2=详细检测

/* 栈溢出钩子 */
void vApplicationStackOverflowHook(TaskHandle_t xTask, char *pcTaskName) {
    ESP_LOGE(TAG, "Stack overflow in task: %s", pcTaskName);
    esp_restart();  // 严重错误，复位
}

/* 运行时栈水位查询 */
UBaseType_t uxTaskGetStackHighWaterMark(TaskHandle_t xTask);
```

**ESP32查看任务栈使用：**
```bash
# 在monitor中输入
freertos:stack
```

---

## 九、优先级分配经验公式

### 9.1 优先级计算公式

```
应用优先级 = configMAX_PRIORITIES - 1 - (任务重要性 × 10)
```

### 9.2 推荐优先级分配表

| 优先级 | 任务类型 | 典型周期 | 理由 |
|:------:|---------|:--------:|------|
| **0** | Idle任务 | - | 系统保留 |
| **1-2** | 系统任务 | - | TimerDaemon等 |
| **3** | 驱动刷新 | 50-100ms | GPIO刷新影响实时性 |
| **4** | 传感器采样 | 200-500ms | 实时性中等 |
| **5-6** | 通信任务 | 事件触发 | ESP-NOW/WiFi |
| **7-8** | 业务逻辑 | 可变 | 非关键 |
| **9-10** | 心跳日志 | 1-30s | 低优先级 |
| **10+** | 调试控制台 | 阻塞 | 人工响应 |

### 9.3 优先级反转问题

```c
/* 问题：高优先级任务等待低优先级任务持有的信号量 */
高优先级Task-A → 等待互斥量 → 低优先级Task-B持有互斥量

/* 解决方案：优先级继承 */
xSemaphoreCreateMutex();  // 互斥信号量自动实现优先级继承

/* 或者使用二分信号量（不推荐） */
```

---

## 十、实战问题排查

### 10.1 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| Stack overflow | 栈太小 | 增大栈空间，检查递归 |
| HardFault | 非法内存访问 | 启用栈检测，添加断言 |
| xTaskCreate失败 | 内存不足/参数错误 | 检查堆大小，验证参数 |
| 任务卡死 | 死锁/永久阻塞 | 使用看门狗，添加超时 |
| 优先级反转 | 互斥量使用不当 | 使用优先级继承 |

### 10.2 调试命令

```bash
# FreeRTOS任务列表
freertos:tasks

# 查看任务栈使用
freertos:stack

# 查看队列状态
freertos:queues

# 查看堆内存
heap:info
```

### 10.3 看门狗配置

```c
/* 任务看门狗（TWDT） */
#include "esp_task_wdt.h"

// 初始化TWDT
esp_task_wdt_init(5000, true);  // 5秒超时

// 添加任务到看门狗
esp_task_wdt_add(NULL);  // 添加当前任务

// 喂狗
esp_task_wdt_reset();
```

---

## 十一、ESP32项目模板

### 11.1 标准任务初始化

```c
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define TASK_STACK_DEPTH   4096
#define TASK_PRIORITY      3

void my_task(void *arg) {
    while (1) {
        // 任务逻辑
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

void app_main(void) {
    TaskHandle_t handle;
    BaseType_t ret = xTaskCreate(
        my_task,              // 任务函数
        "my_task",            // 任务名称
        TASK_STACK_DEPTH,     // 栈深度（字）
        NULL,                 // 参数
        TASK_PRIORITY,        // 优先级
        &handle               // 句柄
    );

    if (ret != pdPASS) {
        ESP_LOGE(TAG, "Task creation failed!");
    }
}
```

### 11.2 完整项目架构示例

```c
/* 任务清单 */
#define PRIORITY_DEVICE_REFRESH   3   // GPIO刷新（最高应用优先级）
#define PRIORITY_SENSOR           4   // 传感器采样
#define PRIORITY_COMM             5   // 通信任务
#define PRIORITY_HEARTBEAT        5   // 心跳（低优先级）
#define PRIORITY_CONSOLE          10  // 控制台（最低）

/* 栈大小 */
#define STACK_DEVICE_REFRESH      4096
#define STACK_SENSOR              4096
#define STACK_COMM                3072
#define STACK_HEARTBEAT           2048
#define STACK_CONSOLE             8192

/* 任务创建 */
void create_tasks(void) {
    xTaskCreatePinnedToCore(device_refresh_task, "dev_refresh",
                            STACK_DEVICE_REFRESH, NULL,
                            PRIORITY_DEVICE_REFRESH, NULL, 1);

    xTaskCreatePinnedToCore(sensor_task, "sensor",
                            STACK_SENSOR, NULL,
                            PRIORITY_SENSOR, NULL, 1);

    xTaskCreatePinnedToCore(heartbeat_task, "heartbeat",
                            STACK_HEARTBEAT, NULL,
                            PRIORITY_HEARTBEAT, NULL, 1);

    xTaskCreatePinnedToCore(console_task, "console",
                            STACK_CONSOLE, NULL,
                            PRIORITY_CONSOLE, NULL, 0);  // Core 0
}
```

---

## 十二、最佳实践清单

### 12.1 必须配置

```c
#define configCHECK_FOR_STACK_OVERFLOW    2    // 栈溢出检测
#define configUSE_MUTEXES                 1    // 互斥信号量
#define configUSE_RECURSIVE_MUTEXES        1    // 递归互斥
#define configQUEUE_REGISTRY_SIZE          10   // 队列注册
#define configENABLE_BACKWARD_COMPAT       1    // 兼容旧API
```

### 12.2 编码规范

1. **任务函数必须返回void**：`void task_func(void *arg)`
2. **任务循环必须使用vTaskDelay阻塞**
3. **中断中使用FromISR版本API**
4. **共享资源必须用互斥量保护**
5. **栈大小宁可大不可小**（至少预留30%余量）
6. **调试时启用栈水位检测**

### 12.3 性能优化

1. **高优先级任务尽量减少执行时间**
2. **避免在任务中执行阻塞操作**
3. **使用事件组代替轮询**
4. **合理使用任务通知代替队列**
5. **大内存使用静态分配**
