---
name: 嵌入式闭环调试
description: 嵌入式固件命令行闭环调试技能。用于用户要求 AI 使用本机 ESP-IDF、Keil5 命令行、J-Link CLI、串口、RTT、GDB/OpenOCD 完成编译、烧录、日志监视、崩溃诊断、寄存器/变量观测和连续修复迭代。遇到 ESP32、STM32、MSPM0、任意 MCU 项目、看门狗复位、串口/RTT 日志、烧录失败、外设初始化失败、协议联调、从机上线验证，或要求闭环调试直到目标达成时必须使用。
---

# 嵌入式闭环调试

这个技能让 AI 在用户电脑上像嵌入式调试工程师一样工作：读代码和原理、编译、烧录、监视日志、定位根因、修改代码、再次编译烧录，持续迭代到用户目标达成。

## 默认环境

- ESP-IDF 优先使用 `E:\MCU\esp32\.espressif\v5.5.3\esp-idf`
- ESP32 构建命令优先使用 PowerShell：
  ```powershell
  & 'E:\MCU\esp32\.espressif\v5.5.3\esp-idf\export.ps1'; idf.py build
  ```
- ESP32 烧录/监视需要 COM 口。若用户未明确给出端口，先枚举端口并询问用户；若用户已经给出或日志中已有端口，直接使用。
- STM32/MSPM0/其他 Keil 工程优先寻找 Keil5 `UV4.exe` 和 `.uvprojx`，仅从 PowerShell 调用 `UV4.exe -b` / `-f` 构建和下载。
- STM32/其他 J-Link 调试优先使用 `JLinkRTTLogger.exe`、`JLinkRTTClient.exe`、`JLinkGDBServerCL.exe`、`JLink.exe` / `JLinkExe` 等 CLI 工具。

## 先读哪些参考

- ESP32/ESP-IDF 闭环：读 `references/esp-idf-esp32.md`
- Keil5、STM32、J-Link、RTT：读 `references/keil-jlink.md`
- 不确定怎样组织迭代：读 `references/closed-loop-workflow.md`
- 看门狗、崩溃、内存、协议、外设初始化、上线验证：读 `references/diagnostic-playbook.md`

可直接运行的辅助脚本在 `scripts/`：

- `detect-env.ps1`：探测 ESP-IDF、Keil、J-Link、串口、常见工程文件。
- `espidf-cycle.ps1`：ESP-IDF 构建/烧录/串口采集一轮闭环。
- `serial-capture.py`：稳定采集串口日志到文件。
- `keil-cycle.ps1`：Keil5 构建/下载一轮闭环。
- `jlink-flash.ps1`：使用固定芯片、接口、速率和探针序列号烧录并校验固件。
- `jlink-rtt-capture.ps1`：使用 `JLinkRTTLogger.exe` 限时采集 RTT 日志到文件。
- `jlink-closed-loop.ps1`：通用 Keil/J-Link 闭环入口，参数化工程、固件、芯片、探针、RTT、测试钩子和日志验收规则；不得在此脚本中硬编码具体项目业务。
- `sync-install.ps1`：把本技能同步安装到 Codex 和 Claude skills 目录。

## 闭环纪律

### 命令行优先（强制）

- Keil5 编译、下载和构建日志必须通过 PowerShell 调用 `UV4.exe` 的命令行参数完成；不得打开或点击 µVision 桌面界面，也不得依赖其 Build/Flash/Watch 窗口。
- J-Link RTT 日志必须使用 `JLinkRTTLogger.exe` 或 `JLinkRTTClient.exe` 的命令行采集并落盘；不得使用 RTT Viewer、RTTView、Ozone 或其他桌面端查看器。
- 变量、寄存器和内存观测必须使用 `arm-none-eabi-gdb` + `JLinkGDBServerCL.exe`、`JLink.exe` / `JLinkExe` 或 OpenOCD 的命令行接口；不得通过 Keil Debug 桌面窗口完成。
- 所有命令都要显式提供芯片、接口、速率、下载器序列号（多下载器时）和输出文件路径，避免弹出选择或配置窗口。缺少这些参数时先探测或询问用户。

1. 明确目标和成功标准：例如“摄像头初始化成功且不再看门狗复位”“三块从机上线后 LVGL 显示 3/3 在线”“某个寄存器值符合预期”。
2. 先观察再修改：读日志、代码、配置、硬件说明；不要凭感觉大改。
3. 每轮只改最小必要范围：一次只验证一个假设，保留用户已有改动。
4. 每轮都留下证据：构建输出、烧录结果、关键日志、崩溃回溯、RTT 片段、变量/寄存器读数。
5. 发现端口、下载器、板卡复位方式不确定时，先探测；仍不确定就问用户。
6. 不使用破坏性操作：不要 `git reset --hard`、不要擦全片、不要覆盖用户配置，除非用户明确要求。
7. 闭环必须持续：编译失败就修编译；烧录失败就修端口/下载器；运行失败就抓日志；日志指向新根因就继续迭代。
8. 优先把已验证的命令固化为项目内脚本，参数化工程、固件、芯片、接口、速率、探针序列号和证据目录，避免下一轮重新拼命令。

## 运动机构真实性分级

电机、舵机等运动机构的“通过”必须说明负载边界，防止架空结果冒充整车结果：

1. 软件回归：算法、协议、超时和故障停车测试通过。
2. 架空台架：至少覆盖正反方向、多档阶跃、左右一致性、稳态误差、停止残留和多轮重复性；原始 RTT 与机器可读汇总都要落盘。
3. 低速落地：台架通过仅允许在可控场地做低速直线测试，验证静摩擦、载荷、电池压降和机械偏载。
4. 任务场景：完成转弯、循迹或实际负载重复测试后，才能声称场景可用。

对重复台架测试，至少报告完整通过轮数、每档误差、左右归一化差异、最差变异系数和停车残留。任何缺相、超时或故障都按整轮失败处理，不能只挑成功日志。

## 标准流程

1. 快速盘点：
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\detect-env.ps1 -ProjectPath <项目路径>
   ```
   同时查看 `git status`、工程类型、构建系统、串口/下载器。

2. 选择工具链：
   - `idf.py` / `sdkconfig` / `CMakeLists.txt` / ESP32 芯片：走 ESP-IDF。
   - `.uvprojx` / `MDK-ARM` / STM32/MSPM0：走 Keil5。
   - 有 RTT 日志、J-Link、裸机/RTOS 深调：接入 RTT/J-Link。

3. 构建：
   - ESP-IDF：先 `idf.py build`。
   - Keil：先 `UV4.exe -b xxx.uvprojx -j0 -o build.log`。
   - 部分 µVision 版本不会提供可靠的进程退出码；以构建日志中的错误/警告汇总和产物时间戳共同判定，不能只看 `$LASTEXITCODE`。
   构建失败时，先修最靠前、最根本的错误。

4. 烧录：
   - ESP32：确认 COM 口后 `idf.py -p COMx flash`。
   - Keil：确认下载器配置后 `UV4.exe -f xxx.uvprojx -o flash.log`。
   - J-Link：必要时使用 JLinkExe/GDBServer/OpenOCD 命令行，记录芯片型号、接口、速率。

5. 监视日志：
   - ESP32：优先串口日志，保存到文件再分析。
   - STM32/其他：优先通过 JLinkRTTLogger 采集 RTT 日志，必要时用 CLI SWO/UART/GDB 观察变量。
   - 日志至少覆盖启动、异常触发、用户目标路径。

6. 诊断：
   - 提取时间线：启动阶段、外设初始化、任务创建、网络/协议、异常点。
   - 分类问题：构建、烧录、启动、看门狗、内存、栈、外设、协议、UI、时序、电源。
   - 建立假设并给出能验证它的最小改动。

7. 修改并重复：
   - 修改代码/配置/资源。
   - 重新 build。
   - 重新 flash。
   - 重新 capture。
   - 对比上一轮证据，直到成功标准满足。

## ESP32 快捷命令

一轮构建、烧录、采集：

```powershell
powershell -ExecutionPolicy Bypass -File <技能目录>\scripts\espidf-cycle.ps1 `
  -ProjectPath <ESP-IDF项目路径> -Port COM28 -Flash -MonitorSeconds 90
```

仅构建：

```powershell
powershell -ExecutionPolicy Bypass -File <技能目录>\scripts\espidf-cycle.ps1 `
  -ProjectPath <ESP-IDF项目路径> -BuildOnly
```

若 COM 口未知，先运行 `detect-env.ps1`，再询问用户要使用哪个可用端口。不要猜测蓝牙串口或历史残留端口。

## Keil/J-Link 快捷命令

通用构建—烧录—RTT—测试—日志验收闭环：

```powershell
powershell -ExecutionPolicy Bypass -File <技能目录>\scripts\jlink-closed-loop.ps1 `
  -Action Cycle -ProjectPath <项目路径> -Uvprojx <工程.uvprojx> `
  -Firmware <固件.hex> -Device <芯片> -Interface SWD -Speed 4000 `
  -UsbSerial <J-Link序列号> -ConfirmOutputSafe -CaptureSeconds 30 `
  -TestCommand <可选测试入口> -TestArguments @(<参数>) `
  -RequiredLogPattern <成功正则> -ForbiddenLogPattern <故障正则>
```

通用入口只负责工具链和证据闭环。电机测试、网络指令、产测协议等项目业务通过 `TestCommand` 注入，不得复制进通用脚本。

Keil 构建：

```powershell
powershell -ExecutionPolicy Bypass -File <技能目录>\scripts\keil-cycle.ps1 `
  -ProjectPath <Keil项目目录> -Uvprojx <工程.uvprojx>
```

Keil 构建并下载：

```powershell
powershell -ExecutionPolicy Bypass -File <技能目录>\scripts\keil-cycle.ps1 `
  -ProjectPath <Keil项目目录> -Uvprojx <工程.uvprojx> -Flash
```

RTT 深调时，优先让固件输出结构化 RTT 日志；需要变量/寄存器时使用 J-Link/GDB/OpenOCD 读取，不要只靠猜。

RTT 命令行采集（采集期间保持当前 PowerShell 会话，不启动桌面程序）：

```powershell
powershell -ExecutionPolicy Bypass -File <技能目录>\scripts\jlink-rtt-capture.ps1 `
  -Device <芯片型号> -Interface SWD -Speed 4000 -Channel 0 -DurationSeconds 90 `
  -OutputPath <项目目录>\logs\rtt.log
```

J-Link CLI 烧录并校验（运动输出必须已处于安全状态）：

```powershell
powershell -ExecutionPolicy Bypass -File <技能目录>\scripts\jlink-flash.ps1 `
  -Firmware <固件.hex> -Device MSPM0G3507 -Interface SWD -Speed 1000 `
  -UsbSerial 69514110 -ConfirmOutputSafe -LogPath <项目目录>\logs\flash.log
```

## 自主调试增强

当日志不足以定位问题时，主动加入临时观测点，并在问题解决后决定是否保留：

- 启动阶段：打印版本、复位原因、时钟、分区/Flash/PSRAM、关键 GPIO 配置。
- FreeRTOS：打印任务栈高水位、队列积压、任务状态、看门狗订阅任务。
- 内存：打印 heap/PSRAM 最小剩余、最大连续块、失败分配大小和调用点。
- 协议：打印 topic/帧头/seq/ack/timeout/重试次数，避免打印大 payload。
- 外设：打印 init 参数、返回码、寄存器关键位、DMA buffer 地址和长度。
- UI/LVGL：打印资源尺寸、解码后内存、刷新耗时、页面切换耗时。
- STM32：使用 RTT 输出状态机、错误码、断言位置；必要时用 J-Link 读寄存器。

## 完成标准

只有同时满足以下条件才报告“完成”：

- 目标行为在真实硬件日志中出现。
- 构建通过，烧录成功，运行日志无新的致命错误。
- 看门狗/崩溃/异常不再复现，或已明确剩余风险和复现条件。
- 关键证据已告知用户：命令、端口、固件版本/commit、关键日志片段。
- 若用户要求提交，先确认暂存范围不包含无关文件，再 commit/push。
