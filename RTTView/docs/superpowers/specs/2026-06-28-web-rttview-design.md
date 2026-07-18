# Web RTTView 设计文档

## 概述

将 PyQt5 桌面版 RTTView 完整迁移到网页端，采用**单 Python 文件 + 内嵌 HTML**架构。

**目标**：
- 零功能阉割，所有 11 个功能全部迁移
- 支持 JLink / DAPLink / STLink 三种探针
- 中文日志完美显示（自动检测 + 手动切换编码）
- VS Code 暗色主题
- 用户只需 `python web_rttview.py` 即可使用

## 架构

```
web_rttview.py (单文件，~3500 行)
├── Python 后端
│   ├── Flask HTTP 服务 (GET / 返回 HTML)
│   ├── Flask-SocketIO (WebSocket 实时通信)
│   ├── 探针管理 (复用 probes/ 模块)
│   ├── 数据采集线程 (RTT/SWO/示波器/寄存器)
│   └── 文件处理 (SVD/ELF/固件上传解析)
│
└── 内嵌前端 (HTML + JS + CSS)
    ├── VS Code 暗色主题
    ├── 9 个功能 Tab
    ├── Chart.js (内嵌 minified) 波形绘制
    ├── ANSI 256 色渲染
    └── WebSocket 客户端
```

**依赖**：
```
pip install flask flask-socketio pylink-square pyusb hidapi chardet
```

## 功能清单

### 1. RTT 终端
- SEGGER RTT 实时文本输出/输入
- ANSI 256 色 HTML 渲染
- 编码支持：自动检测 / UTF-8 / GBK / GB2312 / ASCII
- 时间戳显示
- 自动滚动
- 文件保存
- 自动重连（MCU 复位后）
- 发送历史

### 2. RTT 波形显示
- 从 RTT 数据流解析 1-4 通道曲线
- Chart.js 实时绘制
- 可配置点数

### 3. 寄存器示波器
- 读取任意 MCU 内存地址，100Hz 采样
- 最多 8 通道
- 可配置地址/类型(uint32/int32/float/uint16/int16)/缩放
- 时基选择 (1ms-10s/div)
- 触发模式：自由运行/上升沿/下降沿
- 单次捕获
- 自动缩放 Y 轴
- 频率/Vpp/Vmin/Vmax 测量

### 4. SWO/ITM 追踪
- **SWO 控制台**：ITM 端口 0 实时文本输出
- **CPU 分析器**：DWT PC 采样，函数级 CPU% 统计，ELF 符号解析
- **异常追踪**：IRQ 进入/退出日志

### 5. RTOS 任务查看器
- FreeRTOS v10.x 任务列表
- 名称、状态（颜色编码）、优先级、栈使用率（进度条）、栈大小、TCB 地址
- 1 秒自动刷新

### 6. 崩溃分析器
- 读取所有 ARM 核心寄存器 (R0-R15, xPSR)
- 故障寄存器 (CFSR, HFSR, MMFAR, BFAR, AFSR, DHCSR)
- CFSR 位域解码 (MemManage/BusFault/UsageFault)
- xPSR 解码 (异常号、Thumb 位、NZCV 标志)
- 启发式栈回溯
- ELF 符号解析

### 7. Flash 烧录器
- 支持 BIN / Intel HEX / ELF 格式
- MCU 复位 (AIRCR SYSRESETREQ)
- 256 字节分块烧录 + 进度条
- 回读校验

### 8. SVD 外设寄存器查看器
- 加载 CMSIS-SVD 文件
- 树形视图：外设 → 寄存器 → 位域
- 实时读取寄存器值 (200ms)
- 变化值红色高亮
- 位域详情面板

### 9. 核心寄存器查看器
- ARM Cortex-M (R0-R15, xPSR, MSP, PSP)
- RISC-V (x0-x31, pc, mstatus, mcause, mtval)
- xPSR 字段解码 (异常号、Thumb、NZCVQ)
- RISC-V mstatus 字段解码
- 100ms 自动刷新
- 变化值红色高亮

### 10. 内存查看器
- 读取最多 4096 字节
- 颜色编码十六进制转储 (Flash=青, SRAM=绿, 外设=橙)
- ASCII 侧栏
- 快速跳转按钮
- 500ms 自动刷新

### 11. J-Scope HSS 模式
- 从 ELF 文件读取变量地址
- 直接从 MCU 内存读取变量值
- 实时波形显示

## 前端 UI 布局

```
┌─────────────────────────────────────────────────────────────┐
│  探针: [JLink ▼]  模式: [SWD ▼]  速率: [4MHz ▼]  [连接]    │
│  地址: [0x20000000]  通道: [0]  编码: [自动检测 ▼]           │
├─────────────────────────────────────────────────────────────┤
│ [RTT终端] [波形] [示波器] [SWO] [RTOS] [崩溃] [Flash] [寄存器] [内存] │
├─────────────────────────────────────────────────────────────┤
│                      ← 功能区域 →                            │
├─────────────────────────────────────────────────────────────┤
│  状态: ●已连接  吞吐: ↑1.2KB/s ↓45.3KB/s                   │
└─────────────────────────────────────────────────────────────┘
```

## 色板 (VS Code Dark)

| 用途 | 颜色 |
|------|------|
| 主背景 | `#1e1e1e` |
| 面板背景 | `#252526` |
| 输入框背景 | `#2d2d2d` |
| 边框 | `#3e3e3e` |
| 主文本 | `#d4d4d4` |
| 次要文本 | `#808080` |
| 蓝色强调 | `#569cd6` |
| 青色 | `#4ec9b0` |
| 黄色 | `#dcdcaa` |
| 绿色(成功) | `#4caf50` |
| 红色(错误) | `#f44336` |
| 橙色(警告) | `#ff9800` |

## 中文编码处理

```
MCU 输出字节流 → 后端解码 → WebSocket UTF-8 → 前端显示
                    ↓
              策略：
              1. 尝试 UTF-8
              2. 失败尝试 GBK
              3. 都失败 errors='replace'
              4. 用户可手动切换
```

- 后端使用 chardet 或启发式检测
- 前端编码下拉框：自动/UTF-8/GBK/GB2312/ASCII
- RTT 终端和 SWO 控制台均支持中文

## WebSocket API

### 客户端 → 服务端

| 事件 | 数据 | 说明 |
|------|------|------|
| `probe_detect` | `{}` | 检测可用探针 |
| `probe_connect` | `{type, mode, speed, address, channel}` | 连接探针 |
| `probe_disconnect` | `{}` | 断开连接 |
| `rtt_start` | `{encoding}` | 开始 RTT 采集 |
| `rtt_stop` | `{}` | 停止 RTT |
| `rtt_send` | `{data, encoding}` | 发送数据到 MCU |
| `mem_read` | `{addr, size}` | 读内存 |
| `mem_write` | `{addr, data}` | 写内存 |
| `reg_read` | `{reg}` | 读寄存器 |
| `regs_read` | `{}` | 读所有核心寄存器 |
| `swo_start` | `{}` | 开始 SWO |
| `swo_stop` | `{}` | 停止 SWO |
| `flash_file` | `{file_id, addr}` | 烧录固件 |
| `svd_load` | `{file_id}` | 加载 SVD 文件 |
| `svd_read` | `{peripheral, register}` | 读 SVD 寄存器 |
| `rtos_tasks` | `{}` | 获取任务列表 |
| `crash_analyze` | `{}` | 崩溃分析 |
| `osc_start` | `{channels, interval}` | 开始示波器 |
| `osc_stop` | `{}` | 停止示波器 |
| `wave_start` | `{ncurve, npoint}` | 开始波形 |
| `wave_stop` | `{}` | 停止波形 |

### 服务端 → 客户端

| 事件 | 数据 | 说明 |
|------|------|------|
| `probe_list` | `{probes: [...]}` | 可用探针列表 |
| `connected` | `{probe_type, core_type}` | 连接成功 |
| `disconnected` | `{}` | 断开连接 |
| `rtt_data` | `{text, color_segments}` | RTT 文本 (带颜色) |
| `mem_data` | `{addr, hex, ascii}` | 内存数据 |
| `reg_data` | `{registers: {...}}` | 寄存器数据 |
| `swo_data` | `{type, data}` | SWO 数据 |
| `flash_progress` | `{percent, status}` | 烧录进度 |
| `svd_data` | `{tree, values}` | SVD 数据 |
| `rtos_data` | `{tasks: [...]}` | RTOS 任务列表 |
| `crash_data` | `{registers, faults, stack}` | 崩溃分析结果 |
| `osc_data` | `{channels: [...]}` | 示波器数据 |
| `wave_data` | `{curves: [...]}` | 波形数据 |
| `error` | `{message}` | 错误信息 |
| `status` | `{throughput_up, throughput_down}` | 状态栏 |

## 实时数据流

```
探针 USB ←→ 后端线程 ←→ WebSocket ←→ 前端渲染

RTT终端:  10ms 轮询 ring buffer → 推送文本
示波器:   10ms 读内存 → 推送数值数组
SWO:      10ms 读 SWO buffer → 推送 ITM/PC/异常
RTOS:     1000ms 遍历 TCB → 推送任务列表
寄存器:   200ms 读寄存器 → 推送值变化
内存:     500ms 读内存块 → 推送 hex 数据
```

## 文件上传

- SVD/ELF/固件文件通过 `<input type="file">` 选择
- 上传到 `/upload` 端点
- 后端存储到临时目录
- 返回 file_id 供后续引用

## 错误处理

- 探针连接失败：显示错误信息，不影响 UI
- USB 断开：自动检测，状态栏变红，提示重连
- 内存读取失败：显示 "???"，不崩溃
- 文件格式错误：显示具体错误信息
- WebSocket 断开：前端自动重连

## 启动流程

```
python web_rttview.py
  ↓
启动 Flask + SocketIO (端口 5000)
  ↓
自动打开浏览器 http://localhost:5000
  ↓
前端加载 → WebSocket 连接 → 检测探针 → 就绪
```

## 安全注意事项

- 仅监听 localhost，不暴露到网络
- 上传文件大小限制 50MB
- 临时文件会话结束自动清理
