---
created: 2026-04-22 13:44
updated: 2026-04-22 13:44
tags: [LVGL, GUI, 嵌入式，STM32, 教程]
categories: [嵌入式，图形界面]
status: draft
video_url: https://www.bilibili.com/video/BV1W5PGzKEkt?p=8
video_title: LVGL 核心流程 (第 8 集)
uploader: 尚硅谷
---

# LVGL 核心流程

## 📋 概述
本笔记记录尚硅谷 LVGL 教程第 8 集内容，讲解 LVGL 图形库的核心工作流程。LVGL 是一个轻量级、开源的嵌入式图形库，适用于资源受限的 MCU 平台。

## 🎯 核心要点
**LVGL 的核心工作流程**是理解整个图形库运作的基础，主要包括以下几个关键环节：

1. **初始化流程** - 系统启动时的图形库准备
2. **渲染循环** - 持续刷新屏幕显示
3. **事件处理** - 响应用户交互操作
4. **内存管理** - 高效利用有限资源

## 📚 详细内容

### 1. LVGL 初始化流程

#### 1.1 基础初始化步骤
```c
// 1. 初始化 LVGL 核心
lv_init();

// 2. 创建显示缓冲区 (重要！)
static lv_disp_buf_t disp_buf1;
static lv_color_t buf1_1[CONFIG_LV_DISP_BUF_SIZE];
lv_disp_buf_init(&disp_buf1, buf1_1, NULL, CONFIG_LV_DISP_BUF_SIZE);

// 3. 注册显示驱动
static lv_disp_drv_t disp_drv;
lv_disp_drv_init(&disp_drv);
disp_drv.flush_cb = my_disp_flush;
disp_drv.buffer = &disp_buf1;
lv_disp_drv_register(&disp_drv);

// 4. 注册输入设备驱动 (触摸屏/按键)
static lv_indev_drv_t indev_drv;
lv_indev_drv_init(&indev_drv);
indev_drv.type = LV_INDEV_TYPE_POINTER;
indev_drv.read_cb = my_touchpad_read;
lv_indev_drv_register(&indev_drv);
```

#### 1.2 关键配置参数
- **缓冲区大小**: 通常为屏幕像素数的 1/10 ~ 1/5
- **颜色格式**: RGB565 (16bit) 或 RGB888 (24bit)
- **双缓冲**: 推荐使用双缓冲避免闪烁

### 2. 渲染循环 (Refresh Loop)

#### 2.1 事件循环机制
LVGL 使用**事件驱动**的方式处理刷新：

```c
while(1) {
    // 1. 处理 LVGL 任务
    lv_timer_handler();  // 关键函数！
    
    // 2. 其他任务...
    
    // 3. 短暂延时
    vTaskDelay(pdMS_TO_TICKS(1));
}
```

#### 2.2 刷新策略
- **自动刷新**: LVGL 内部定时器自动触发
- **手动刷新**: 需要时调用 `lv_refr_now()`
- **部分刷新**: 只刷新变更区域 (性能优化)

### 3. 事件处理机制

#### 3.1 事件类型
- **点击事件**: `LV_EVENT_CLICKED`
- **长按事件**: `LV_EVENT_LONG_PRESSED`
- **值变化**: `LV_EVENT_VALUE_CHANGED`
- **释放**: `LV_EVENT_RELEASED`

#### 3.2 事件回调示例
```c
static void btn_event_cb(lv_event_t * e) {
    lv_event_code_t code = lv_event_get_code(e);
    lv_obj_t * btn = lv_event_get_target(e);
    
    if(code == LV_EVENT_CLICKED) {
        =="按钮被点击！"==
        // 执行点击后的逻辑
    } else if(code == LV_EVENT_LONG_PRESSED) {
        =="按钮被长按！"==
        // 执行长按后的逻辑
    }
}
```

### 4. 内存管理

#### 4.1 内存分配策略
LVGL 使用**内存池**管理：
- **静态分配**: 编译时确定大小
- **动态分配**: 运行时从内存池分配
- **内存碎片**: 定期整理避免碎片化

#### 4.2 性能优化技巧
- **对象复用**: 避免频繁创建/删除对象
- **批量操作**: 一次性设置多个属性
- **裁剪优化**: 只渲染可见区域

## 🔗 相关笔记
- [[LVGL 基础之模拟开发和移植]]
- [[LVGL 移植流程]]
- [[STM32 GUI 开发]]
- [[嵌入式图形库对比]]

## 📝 待办事项
- [ ] 实践 LVGL 初始化代码
- [ ] 配置显示缓冲区大小
- [ ] 实现触摸屏驱动
- [ ] 创建第一个 LVGL 界面
- [ ] 测试事件回调功能

## 💡 思考与总结

### 关键理解
1. **lv_timer_handler() 是核心**: 必须定期调用，否则界面不会刷新
2. **缓冲区大小很重要**: 太小影响性能，太大浪费内存
3. **事件驱动模式**: 避免阻塞，提高响应速度

### 注意事项
> [!WARNING] 常见问题
> - 忘记调用 `lv_timer_handler()` → 界面不刷新
> - 缓冲区设置过小 → 渲染闪烁
> - 内存不足 → 对象创建失败

### 下一步
- 学习如何创建基础 UI 组件
- 了解 LVGL 的样式系统
- 实践触摸屏交互开发

---

## 📊 视频信息
| 项目 | 内容 |
|------|------|
| 视频标题 | LVGL 的核心流程 |
| 集数 | 第 8 集 / 共 78 集 |
| 时长 | 29:50 |
| 发布时间 | 2026-03-03 |
| 播放量 | 8.7 万 + |
| 配套资料 | 关注公众号"尚硅谷教育"，回复"LVGL" |

---

## 🔄 变更记录
- `2026-04-22 13:44`: 创建笔记，记录视频核心内容