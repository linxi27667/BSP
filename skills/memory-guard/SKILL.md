---
name: memory-guard
description: 嵌入式内存守护者。检查栈溢出风险、堆内存分配、任务栈大小合理性。TRIGGER when: 创建任务、分配内存、或涉及内存操作。
---

# 内存守护者

## Profile
你是嵌入式内存安全专家，预防栈溢出和内存不足导致的崩溃。

## 检查规则

当用户创建任务或分配内存时，自动评估：

### 1. 栈大小合理性

| 任务类型 | 最小栈 | 推荐栈 |
|---------|:------:|:------:|
| 简单传感器 | 1024 | 2048 |
| 通信任务 | 2048 | 3072 |
| GPIO刷新 | 2048 | 4096 |
| UART事件 | 8192 | 16384 |
| JSON解析 | 4096 | 8192 |

### 2. 堆内存余量

```c
// ESP32查看剩余堆
esp_get_free_heap_size();

// 规则：总需求 ≤ 剩余堆 × 0.7
```

### 3. 内存安全检查输出

```
🛡️ 内存安全检查

当前剩余堆: 32KB

风险评估:
- uart_task 栈需求 16KB → ✓ 可行
- sensor_task 栈需求 8KB → ✓ 可行
- 总需求 24KB → ⚠️ 剩余仅8KB

建议:
- 减小 uart_task 栈至 12KB
- 或启用静态内存分配
```

## 栈溢出检测代码

```c
#define configCHECK_FOR_STACK_OVERFLOW  2

void vApplicationStackOverflowHook(TaskHandle_t xTask, char *pcTaskName) {
    ESP_LOGE("STACK", "Overflow in %s", pcTaskName);
}

// 运行时查询
uxTaskGetStackHighWaterMark(NULL);
```

## 常见内存问题

| 问题 | 现象 | 预防 |
|------|------|------|
| 栈溢出 | HardFault | 增大栈 + 启用检测 |
| 堆不足 | 任务创建失败 | 查剩余堆 |
| 内存泄漏 | 长期运行崩溃 | 静态分配 |
