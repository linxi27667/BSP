# RTTView

SEGGER-RTT / 多探针嵌入式调试上位机（桌面 + Web）。

支持 **J-Link · ST-Link · DAPLink(pyOCD) · OpenOCD**，Web 端可局域网/服务器部署。

## 依赖

```shell
pip install PyQt5 PyQtChart pyusb hidapi six pyelftools
pip install -r requirements-web.txt   # flask, flask-socketio, pylink-square, pyserial, ...
```

### ST-Link（Windows 推荐）

官方 ST 驱动下 pyusb 常报 `Access denied`。本项目在 Windows 上**自动走 ST-LINK_CLI**：

1. 安装 [STM32 ST-LINK Utility](https://www.st.com/en/development-tools/stsw-link004.html)（提供 `ST-LINK_CLI.exe`）
2. 或设置环境变量 `STLINK_CLI=C:\path\to\ST-LINK_CLI.exe`
3. 关闭 Keil / CubeProgrammer / 其它占用 ST-Link 的软件

可选：用 Zadig 把 ST-Link 绑到 WinUSB 后可走原生 pyusb 路径（更快）。

## 运行

```shell
# 桌面
python RTTView.py

# Web（本机）
python web_rttview.py

# Web（服务器 / 局域网，探针插在服务器 USB）
python web_rttview.py --host 0.0.0.0 --port 5000 --no-browser
# 或 RTTVIEW_HOST=0.0.0.0 RTTVIEW_PORT=5000
```

## Web 使用

1. Probe 选 **J-Link / ST-Link / DAPLink / OpenOCD**
2. Mode = **ARM SWD**，RTT = **auto**（自动搜 `_SEGGER_RTT`）
3. **连接** → 找到 RTT 后自动刷 log；顶栏可 **复位 MCU / 复位+Halt**
4. 页签：RTT、波形、示波器、SWO、RTOS、崩溃、核心寄存器、调试、SWD 烧录、串口烧录、SVD、内存

### 探针能力

| 能力 | J-Link | ST-Link | DAPLink | OpenOCD |
|------|--------|---------|---------|---------|
| 自动搜 RTT / 终端 | ✓ | ✓（CLI 或 USB） | ✓ | ✓ |
| 内存 / 寄存器 / 复位 | ✓ | ✓ | ✓ | ✓ |
| SWO | ✓ | ✗ | ✗ | ✗ |
| SWD 烧录 | `flash_file` | ST-LINK_CLI `-P` | 有限 | 视配置 |
| 串口烧录 | 共用 UART 页（pyserial / STM32 ISP） |  |  |  |

### 三种入口（顶栏「入口」）

| 入口 | 探针在哪 | 怎么连 |
|------|----------|--------|
| **浏览器直连 (WebUSB)** | 插在**你打开网页的电脑** | 点「连接」→ Chrome/Edge 弹出选 ST-Link → 自动 RTT |
| **本机 USB (服务器)** | 插在跑 `web_rttview` 的机器 | 扫描 → 选探针 → 连接 |
| **远程代理 (Agent)** | 插在另一台工位 | 工位跑 `probe_agent.py`，页面填 Agent 地址后扫描连接 |

**WebUSB 注意（最省事、一点就连）：**
- 仅 Chrome / Edge；探针必须在**浏览器所在电脑** USB 上
- Windows 默认 ST 驱动常拦 WebUSB → 用 [Zadig](https://zadig.akeo.ie/) 把 ST-Link 绑成 **WinUSB**（之后官方 ST-LINK Utility 可能暂不可用，可换回驱动）
- 也可不换驱动：工位跑 Agent，入口选「远程代理」

**服务器部署示例：**
```shell
# 服务器
python web_rttview.py --host 0.0.0.0 --port 5000 --no-browser
# 你在自己电脑浏览器打开 http://服务器:5000
# 入口选「浏览器直连」→ 连接（USB 在你电脑上）
```

## 真机测试

```shell
# J-Link
python tests/hw_jlink_smoke.py

# ST-Link（需 ST-LINK_CLI）
python tests/hw_stlink_closed_loop.py
python tests/hw_stlink_web_loop.py   # 需先启动 web_rttview.py

# 单元
python tests/test_probes.py
python tests/test_web_rtt_helpers.py
```

## 目录

```
RTTView/
├── RTTView.py / web_rttview.py
├── core/          # xlink, SVD, SWO, RTOS
├── probes/        # jlink / stlink(+CLI) / daplink / openocd
├── widgets/       # Qt 面板
├── tests/
├── requirements-web.txt
└── libusb-1.0.24/ # Windows pyusb 辅助
```

## Wave 数据格式

- 1 路: `11, 22, 33,`
- 2 路: `11 22, 33 44,`
- 3/4 路同理（空格分通道，逗号分采样）
