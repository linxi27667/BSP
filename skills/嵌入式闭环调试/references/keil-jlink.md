# Keil5 / J-Link / RTT 闭环

## 强制命令行约束

- 只从 PowerShell 或终端执行 Keil5、J-Link 和 GDB；不得打开或点击 µVision、RTT Viewer、RTTView、Ozone 等桌面端界面。
- 每个命令都显式指定芯片、接口、速率和日志文件；连接多个 J-Link 时额外指定 `-USB <序列号>`。
- 不完整的连接参数可能触发选择窗口。先用 `detect-env.ps1` 探测；仍不确定时询问用户，不以 GUI 补全参数。

## Keil5 命令行

常见 Keil 路径：

- `C:\Keil_v5\UV4\UV4.exe`
- `C:\Keil\UV4\UV4.exe`
- `D:\Keil_v5\UV4\UV4.exe`

构建：

```powershell
& 'C:\Keil_v5\UV4\UV4.exe' -b .\Project.uvprojx -j0 -o build.log
```

下载：

```powershell
& 'C:\Keil_v5\UV4\UV4.exe' -f .\Project.uvprojx -o flash.log
```

若工程有多个 target，先读取 `.uvprojx` target 名称；不确定 target 时询问用户。

## J-Link / RTT

只查找以下命令行工具：

- `C:\Program Files\SEGGER\JLink\JLinkRTTLogger.exe`
- `C:\Program Files\SEGGER\JLink\JLinkRTTClient.exe`
- `C:\Program Files\SEGGER\JLink\JLink.exe`
- `C:\Program Files\SEGGER\JLink\JLinkGDBServerCL.exe`

RTT 调试策略：

1. 固件中启用 SEGGER RTT 或项目已有 RTT 输出。
2. 用 `JLinkRTTLogger.exe` 从命令行指定芯片、接口、速率、通道和输出文件。
3. 采集启动到故障的完整日志，超时后停止进程并保存文件。
4. 如日志不足，增加 RTT 观测点：状态机、错误码、断言、队列长度、栈水位。

```powershell
& 'C:\Program Files\SEGGER\JLink\JLinkRTTLogger.exe' `
  -Device STM32F407VG -If SWD -Speed 4000 -RTTChannel 0 .\logs\rtt.log
```

通过技能脚本进行可控的限时采集：

```powershell
powershell -ExecutionPolicy Bypass -File <技能目录>\scripts\jlink-rtt-capture.ps1 `
  -Device STM32F407VG -Interface SWD -Speed 4000 -Channel 0 -DurationSeconds 90 `
  -OutputPath .\logs\rtt.log
```

## J-Link 深度调试

需要变量/寄存器时只可选择：

- `JLinkGDBServerCL.exe` + `arm-none-eabi-gdb`。
- `JLink.exe` / `JLinkExe` 的命令文件读取内存/寄存器。
- OpenOCD + GDB（若项目已有配置）。

不要只靠断点猜测。每次深调都记录：

- 芯片型号。
- 接口：SWD/JTAG。
- 速率。
- 复位方式。
- ELF/AXF 路径。
- 观察到的变量/寄存器值。

## STM32/其他 MCU 常见根因线索

- HardFault：解析 stacked PC/LR/xPSR，定位 faulting instruction。
- 看门狗复位：区分 IWDG/WWDG，检查喂狗任务是否被高优先级阻塞。
- 外设无响应：先查 RCC 时钟、GPIO AF、复位脚、电源、总线速率。
- DMA 异常：检查 buffer 对齐、cache clean/invalidate、长度、传输完成中断。
- FreeRTOS 卡死：检查中断优先级是否违反 FreeRTOS API 规则。
- RTT 无输出：确认 `SEGGER_RTT_Init`、buffer、链接脚本、优化裁剪。

## 下载前安全检查

- 确认 target 芯片和工程一致。
- 确认 option bytes/fuses 不会被误改。
- 批量烧录前先烧一块验证。
- 对电机、继电器、高压输出，先断开负载或进入安全模式。
