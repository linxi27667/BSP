---
name: 资深嵌入式专家
description: 嵌入式系统架构设计、Flag-driven模式、ESP-NOW协议、GPIO/PWM/ADC驱动、Bug排查、FreeRTOS最佳实践。TRIGGER when: ESP32/STM32相关代码或嵌入式项目。
---
# 资深嵌入式系统专家 Skill

## 定位
本Skill是资深嵌入式系统专家的实战经验总结，具备大厂级系统思维，精通ESP32/STM32单片机开发、RTOS实时操作系统、无线通信协议。擅长通过日志分析、代码审查、对比实验等手段精准定位疑难Bug。能够从系统架构层面设计高质量、可维护的嵌入式代码。

---

## 一、嵌入式架构设计

### 1.1 混合分层架构（推荐）

```
┌─────────────────────────────────────────────────────────────────┐
│                     嵌入式系统分层架构                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              业务逻辑层 (Business Logic)                 │    │
│  │  iot_control.c / sys_fsm.c / ui_manager.c              │    │
│  │  - 业务流转、协议解析、状态机                             │    │
│  │  - 绝对禁止操作硬件寄存器                                 │    │
│  │  - 只调用硬件驱动层暴露的高级API                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │           硬件驱动层 (Hardware Driver - 双层)             │    │
│  │                                                         │    │
│  │  ┌─────────────────┐    ┌─────────────────────────┐   │    │
│  │  │  BSP层          │    │   APP_HW层 (硬件绑定)     │   │    │
│  │  │  bsp_xxx.h/c    │ →  │   app_xxx.h/c            │   │    │
│  │  │  - 纯逻辑抽象    │    │   - 物理引脚绑定         │   │    │
│  │  │  - 平台无关     │    │   - HAL/SDK调用          │   │    │
│  │  │  - 函数指针接口  │    │   - #include解禁区       │   │    │
│  │  └─────────────────┘    └─────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                   芯片层 (Chip)                         │    │
│  │  ESP-IDF / STM32 HAL / Arduino Core                   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 文件命名规范

| 类型 | 命名规则 | 示例 |
|------|----------|------|
| BSP抽象层 | `bsp_xxx.h/c` | `bsp_motor.h`, `bsp_sw_i2c.h` |
| 硬件绑定层 | `app_xxx.h/c` | `app_motor.h`, `app_mpu6050.h` |
| 业务逻辑层 | `iot_xxx.c` | `iot_control.c`, `iot_fsm.c` |
| 系统级 | `sys_xxx.c` | `sys_time.c`, `sys_event.c` |

### 1.3 函数命名规范

```c
/* 硬件底层函数：HW_ 前缀 */
static void HW_GPIO_Init(void);
static void HW_Timer_Init(void);
static void HW_UART_Send(uint8_t data);

/* BSP层抽象函数：大驼峰 */
void BSP_Motor_Set_Speed(motor_t *motor, int speed);
void BSP_LED_On(led_t *led);
void BSP_LED_Off(led_t *led);

/* 业务层函数：功能命名 */
void IoT_Control_Process_Cmd(const char *json);
void Sys_FSM_Transition(fsm_state_t new_state);
void UI_Display_Update(screen_t *screen);

/* 回调函数：_CB 后缀 */
static void UART_Rx_Callback(void *arg);
static void Timer_Overflow_Callback(void *arg);
```

---

## 二、Flag-driven 架构详解

### 2.1 核心思想

**通信与硬件操作完全解耦，通过全局标志位传递状态。**

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ ESP-NOW接收  │    │  按键输入   │    │  定时器触发  │
│   回调       │    │   任务      │    │    任务      │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                    │                    │
       ↓                    ↓                    ↓
┌─────────────────────────────────────────────────────────┐
│              g_device_flags (全局枚举标志位)               │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐ │
│  │ light[] │ │ relay[] │ │ servo[] │ │ fire_status │ │
│  └─────────┘ └─────────┘ └─────────┘ └─────────────┘ │
└─────────────────────────────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────┐
│              Device_Refresh_Task                          │
│  - 只读取标志位，不做判断                                 │
│  - 统一刷新GPIO输出                                      │
│  - 100ms周期执行                                         │
└─────────────────────────────────────────────────────────┘
                           │
                           ↓
              ┌─────────┐ ┌─────────┐ ┌─────────┐
              │ 灯光GPIO │ │继电器GPIO│ │ 舵机PWM │
              └─────────┘ └─────────┘ └─────────┘
```

### 2.2 枚举定义

```c
/* 设备状态枚举（安全、易读、可扩展） */
typedef enum {
    OFF = 0,
    ON  = 1
} device_onoff_enum_t;

typedef enum {
    LIGHT_OFF = 0,
    LIGHT_ON  = 1
} light_state_enum_t;

typedef enum {
    SERVO_0   = 0,
    SERVO_45  = 1,
    SERVO_90  = 2,
    SERVO_135 = 3,
    SERVO_180 = 4
} servo_angle_enum_t;

typedef enum {
    FIRE_STATUS_NORMAL    = 0,
    FIRE_STATUS_WARNING   = 1,
    FIRE_STATUS_CONFIRMED = 2
} fire_status_enum_t;

/* 全局设备标志位 */
typedef struct {
    device_onoff_enum_t light[3];
    device_onoff_enum_t relay[3];
    servo_angle_enum_t  servo[3];
    fire_status_enum_t  fire_status;
} device_flags_t;

volatile device_flags_t g_device_flags;
```

### 2.3 刷新任务实现

```c
/* 舵机角度映射表 */
static const int16_t g_servo_angle_map[5] = {
    [SERVO_0]   = 0,
    [SERVO_45]  = 45,
    [SERVO_90]  = 90,
    [SERVO_135] = 135,
    [SERVO_180] = 180
};

static void Device_Refresh_Task(void *arg) {
    while (1) {
        /* 刷新灯光 */
        for (int i = 0; i < 3; i++) {
            gpio_set_level(light_gpio[i], g_device_flags.light[i]);
        }

        /* 刷新继电器 */
        for (int i = 0; i < 3; i++) {
            gpio_set_level(relay_gpio[i], g_device_flags.relay[i]);
        }

        /* 刷新舵机 */
        for (int i = 0; i < 3; i++) {
            servo_set_angle(servo_channels[i],
                          g_servo_angle_map[g_device_flags.servo[i]]);
        }

        vTaskDelay(pdMS_TO_TICKS(100));
    }
}
```

---

## 三、通信协议设计

### 3.1 ESP-NOW 协议封装

```c
/* 协议包定义 */
typedef struct __attribute__((packed)) {
    uint8_t command;      /* 命令类型 */
    uint8_t device_id;    /* 设备ID */
    uint8_t gpio_index;   /* GPIO索引 */
    uint8_t value;        /* 值 */
    uint8_t reserved[4];  /* 保留 */
} iot_command_packet_t;

/* 命令枚举 */
typedef enum {
    IOT_CMD_SET_GPIO      = 0x01,
    IOT_CMD_GET_GPIO      = 0x02,
    IOT_CMD_SET_SERVO     = 0x10,
    IOT_CMD_HEARTBEAT     = 0x04,
    IOT_CMD_DISCOVER      = 0x06,
    IOT_CMD_FIRE_ALARM    = 0x20
} iot_command_enum_t;

/* 发送响应 */
static void Send_Response(const uint8_t *dest_mac,
                         uint8_t cmd,
                         uint8_t gpio_index,
                         uint8_t value) {
    iot_command_packet_t resp = {
        .command = cmd,
        .device_id = 0,
        .gpio_index = gpio_index,
        .value = value,
        .reserved = {0}
    };

    esp_now_send(dest_mac, (const uint8_t *)&resp, sizeof(resp));
}

/* 接收回调 */
static void EspNow_Recv_Callback(const uint8_t *mac,
                                 const uint8_t *data,
                                 int len) {
    if (len < sizeof(iot_command_packet_t)) {
        return;
    }

    iot_command_packet_t *cmd = (iot_command_packet_t *)data;

    switch (cmd->command) {
        case IOT_CMD_SET_GPIO:
            if (cmd->gpio_index < 3) {
                g_device_flags.light[cmd->gpio_index] =
                    cmd->value ? ON : OFF;
            }
            break;

        case IOT_CMD_SET_SERVO:
            if (cmd->gpio_index >= 6 && cmd->gpio_index < 9) {
                uint8_t servo_idx = cmd->gpio_index - 6;
                g_device_flags.servo[servo_idx] = cmd->value / 45;
            }
            break;

        case IOT_CMD_HEARTBEAT:
            Send_Response(mac, IOT_CMD_RESPONSE, 0, 1);
            break;
    }
}
```

### 3.2 心跳机制

```c
#define HEARTBEAT_INTERVAL_MS   30000

static void Heartbeat_Task(void *arg) {
    vTaskDelay(pdMS_TO_TICKS(5000));  /* 等待系统就绪 */

    while (1) {
        if (g_master_known) {
            iot_command_packet_t hb = {
                .command = IOT_CMD_HEARTBEAT,
                .device_id = 0,
                .gpio_index = 0,
                .value = 0
            };
            esp_now_send(g_master_mac, (const uint8_t *)&hb, sizeof(hb));
        }
        vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_INTERVAL_MS));
    }
}
```

---

## 四、GPIO 与外设驱动

### 4.1 GPIO 操作封装

```c
/* BSP层：纯逻辑抽象 */
typedef struct {
    gpio_num_t pin;
    void (*write)(gpio_num_t pin, uint8_t level);
    uint8_t (*read)(gpio_num_t pin);
} gpio_device_t;

void BSP_GPIO_Init(gpio_device_t *dev, gpio_num_t pin);
void BSP_GPIO_Write(gpio_device_t *dev, uint8_t level);
uint8_t BSP_GPIO_Read(gpio_device_t *dev);

/* APP_HW层：硬件绑定 */
static void HW_GPIO_Write(gpio_num_t pin, uint8_t level) {
    gpio_set_level(pin, level);
}

gpio_device_t led = {
    .pin = GPIO_NUM_2,
    .write = HW_GPIO_Write
};
```

### 4.2 PWM 舵机控制

```c
#define SERVO_MIN_PULSEWIDTH_US  500
#define SERVO_MAX_PULSEWIDTH_US  2500
#define SERVO_MAX_ANGLE          180
#define SERVO_PWM_FREQUENCY      50

void BSP_Servo_Init(gpio_num_t gpio, ledc_channel_t channel) {
    ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .timer_num = LEDC_TIMER_0,
        .duty_resolution = LEDC_TIMER_14_BIT,
        .freq_hz = SERVO_PWM_FREQUENCY,
        .clk_cfg = LEDC_AUTO_CLK
    };
    ledc_timer_config(&timer);

    ledc_channel_config_t ch = {
        .gpio_num = gpio,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = channel,
        .timer_sel = LEDC_TIMER_0,
        .duty = 0
    };
    ledc_channel_config(&ch);
}

void BSP_Servo_Set_Angle(ledc_channel_t channel, int16_t angle) {
    angle = (angle > 180) ? 180 : (angle < 0) ? 0 : angle;

    float pulse_width = SERVO_MIN_PULSEWIDTH_US +
        (float)angle * (SERVO_MAX_PULSEWIDTH_US - SERVO_MIN_PULSEWIDTH_US) / SERVO_MAX_ANGLE;

    uint32_t duty = (uint32_t)((pulse_width * 16384) / 20000);

    ledc_set_duty(LEDC_LOW_SPEED_MODE, channel, duty);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, channel);
}
```

### 4.3 ADC 采样

```c
#define ADC_SAMPLE_INTERVAL_MS   500
#define ADC_TRIGGER_COUNT        3

static void ADC_Sensor_Task(void *arg) {
    adc1_config_width(ADC_WIDTH_BIT_12);
    adc1_config_channel_atten(ADC1_CHANNEL_0, ADC_ATTEN_DB_11);

    int exceed_count = 0;

    while (1) {
        int adc_raw = adc1_get_raw(ADC1_CHANNEL_0);
        int voltage_mv = (adc_raw * 1100) / 4095;

        if (voltage_mv > FIRE_THRESHOLD_MV) {
            if (++exceed_count >= ADC_TRIGGER_COUNT) {
                g_device_flags.fire_status = FIRE_STATUS_CONFIRMED;
                exceed_count = 0;
            }
        } else {
            exceed_count = 0;
            g_device_flags.fire_status = FIRE_STATUS_NORMAL;
        }

#if DEBUG_MODE == 1
        static uint32_t last_log = 0;
        uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;
        if (now - last_log >= 3000) {
            ESP_LOGI(TAG, "ADC: %d mV", voltage_mv);
            last_log = now;
        }
#endif

        vTaskDelay(pdMS_TO_TICKS(ADC_SAMPLE_INTERVAL_MS));
    }
}
```

---

## 五、Bug 排查指南

### 5.1 常见错误分析

| 错误现象 | 根本原因 | 解决方案 |
|---------|---------|---------|
| HardFault | 内存越界、栈溢出、非法指针 | 启用栈检测、检查数组边界 |
| L6200E多重定义 | 头文件中定义变量 | 头文件用extern，.c中定义 |
| 任务创建失败 | 堆内存不足、参数错误 | 检查剩余堆大小、验证参数 |
| GPIO不响应 | 引脚模式错误、IO口冲突 | 检查GPIO配置、复用功能 |
| 通信丢包 | 信号干扰、缓冲区不足 | 增加重传机制、增大队列 |

### 5.2 调试技巧

```c
/* 1. 栈溢出检测 */
#define configCHECK_FOR_STACK_OVERFLOW    2

void vApplicationStackOverflowHook(TaskHandle_t xTask, char *pcTaskName) {
    ESP_LOGE(TAG, "Stack overflow in %s", pcTaskName);
}

/* 2. 运行时栈水位查询 */
void debug_task(void *arg) {
    while (1) {
        UBaseType_t watermark = uxTaskGetStackHighWaterMark(NULL);
        ESP_LOGI(TAG, "Stack high water mark: %lu", watermark);
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

/* 3. 内存统计 */
void memory_debug_task(void *arg) {
    while (1) {
        multi_heap_info_t info;
        heap_caps_get_info(&info, MALLOC_CAP_8BIT);
        ESP_LOGI(TAG, "Free heap: %lu, alloc: %lu, free_internal: %lu",
                 info.total_free_bytes,
                 info.total_allocated_bytes,
                 info.total_free_bytes - info.total_allocated_bytes);
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}
```

### 5.3 日志分析

```c
/* 分级日志 */
#define ESP_LOGE(tag, format, ...)  // 错误
#define ESP_LOGW(tag, format, ...)  // 警告
#define ESP_LOGI(tag, format, ...)  // 信息
#define ESP_LOGD(tag, format, ...)  // 调试
#define ESP_LOGV(tag, format, ...)  // 详细

/* 条件日志（DEBUG_MODE控制） */
#if DEBUG_MODE == 1
    #define DEBUG_LOG(fmt, ...) ESP_LOGI(TAG, "[DEBUG] " fmt, ##__VA_ARGS__)
#else
    #define DEBUG_LOG(fmt, ...)
#endif

/* HEXdump调试 */
void esp_log_buffer_hex(const char *tag, const void *buffer, size_t len);
```

---

## 六、FreeRTOS 最佳实践

### 6.1 任务优先级分配

| 优先级 | 任务 | 理由 |
|:------:|------|------|
| 中断 | ESP-NOW/UART回调 | 最高实时性 |
| 3 | Device_Refresh | GPIO刷新影响用户体验 |
| 4 | Sensor/ADC | 传感器采样，中等实时性 |
| 5 | 通信任务 | ESP-NOW/WiFi |
| 10 | 心跳/日志 | 低优先级，人工响应 |

### 6.2 互斥保护

```c
/* 保护UART输出 */
static SemaphoreHandle_t uart_mutex;

void safe_printf(const char *fmt, ...) {
    xSemaphoreTake(uart_mutex, portMAX_DELAY);
    va_list args;
    va_start(args, fmt);
    vprintf(fmt, args);
    va_end(args);
    xSemaphoreGive(uart_mutex);
}

/* 保护共享数据结构 */
static SemaphoreHandle_t data_mutex;

void update_shared_data(data_t *data, uint8_t value) {
    xSemaphoreTake(data_mutex, portMAX_DELAY);
    data->value = value;
    data->timestamp = xTaskGetTickCount();
    xSemaphoreGive(data_mutex);
}
```

### 6.3 队列设计

```c
/* 生产者-消费者队列 */
QueueHandle_t sensor_queue;

void sensor_producer(void *arg) {
    sensor_data_t data;
    while (1) {
        read_sensor(&data);
        if (xQueueSend(sensor_queue, &data, pdMS_TO_TICKS(100)) != pdTRUE) {
            ESP_LOGW(TAG, "Queue full, data dropped");
        }
    }
}

void data_consumer(void *arg) {
    sensor_data_t data;
    while (1) {
        if (xQueueReceive(sensor_queue, &data, pdMS_TO_TICKS(1000)) == pdTRUE) {
            process_sensor_data(&data);
        }
    }
}
```

---

## 七、代码模板

### 7.1 标准任务模板

```c
/**
 * @file    xxx_task.c
 * @brief   XXXX任务
 */
#include "xxx_task.h"

static const char *TAG = "XXX_TASK";

#define XXX_TASK_STACK_SIZE    4096
#define XXX_TASK_PRIORITY      4
#define XXX_TASK_INTERVAL_MS   500

static void XXX_Task(void *arg) {
    /* 初始化 */
    ESP_LOGI(TAG, "Task started");

    while (1) {
        /* 任务逻辑 */

        vTaskDelay(pdMS_TO_TICKS(XXX_TASK_INTERVAL_MS));
    }
}

void XXX_Task_Init(void) {
    BaseType_t ret = xTaskCreate(
        XXX_Task,
        "xxx_task",
        XXX_TASK_STACK_SIZE,
        NULL,
        XXX_TASK_PRIORITY,
        NULL
    );

    if (ret != pdPASS) {
        ESP_LOGE(TAG, "Task creation failed!");
    }
}
```

### 7.2 中断回调模板

```c
/* 中断处理（不调用FreeRTOS API） */
static void IRAM_ATTR gpio_isr_handler(void *arg) {
    uint32_t gpio_num = (uint32_t)arg;
    BaseType_t higher_priority_woken = pdFALSE;

    /* 更新标志位（原子操作） */
    g_gpio_intr_flags |= (1 << gpio_num);

    /* 发送信号量通知任务 */
    xTaskNotifyFromISR(task_handle,
                       gpio_num,
                       eSetBits,
                       &higher_priority_woken);

    portYIELD_FROM_ISR(higher_priority_woken);
}
```

### 7.3 状态机模板

```c
typedef enum {
    STATE_IDLE = 0,
    STATE_WORKING,
    STATE_ERROR,
    STATE_RECOVERY
} system_state_enum_t;

static system_state_enum_t g_system_state = STATE_IDLE;

void Sys_FSM_Process(system_event_enum_t event) {
    system_state_enum_t prev_state = g_system_state;

    switch (g_system_state) {
        case STATE_IDLE:
            if (event == EVENT_START) {
                g_system_state = STATE_WORKING;
            }
            break;

        case STATE_WORKING:
            if (event == EVENT_ERROR) {
                g_system_state = STATE_ERROR;
            } else if (event == EVENT_STOP) {
                g_system_state = STATE_IDLE;
            }
            break;

        case STATE_ERROR:
            if (event == EVENT_RECOVER) {
                g_system_state = STATE_RECOVERY;
            }
            break;

        case STATE_RECOVERY:
            if (event == EVENT_RECOVERY_DONE) {
                g_system_state = STATE_IDLE;
            }
            break;
    }

    if (prev_state != g_system_state) {
        ESP_LOGI(TAG, "State: %d -> %d", prev_state, g_system_state);
    }
}
```

---

## 八、架构优势总结

| 原则 | 说明 |
|------|------|
| **高内聚** | 每个模块职责单一，代码高度内聚 |
| **低耦合** | 模块间通过API通信，依赖最小化 |
| **可测试** | 业务逻辑与硬件解耦，便于单元测试 |
| **可扩展** | 新增功能只需添加模块，不影响现有代码 |
| **可维护** | Flag-driven架构使状态管理清晰明了 |
| **高性能** | 中断回调直接更新标志位，最小延迟 |

---

## 九、经验清单

### 9.1 必须掌握

- [ ] FreeRTOS任务创建、删除、优先级管理
- [ ] 队列、信号量、互斥量、任务通知
- [ ] ESP-NOW协议封装与回调处理
- [ ] GPIO、PWM、ADC外设驱动
- [ ] Flag-driven架构设计与实现
- [ ] 中断与任务的同步机制
- [ ] 栈溢出检测与内存管理

### 9.2 高级技能

- [ ] 双核调度与核心亲和性
- [ ] 复杂状态机设计
- [ ] 低功耗设计（Tickless）
- [ ] OTA升级实现
- [ ] 加密通信（TLS/MQTT）
- [ ] 多协议网关设计

### 9.3 调试能力

- [ ] 日志分级与条件编译
- [ ] 栈水位监控
- [ ] 内存泄漏检测
- [ ] 性能分析（trace）
- [ ] HardFault快速定位
