# ESP-IDF / ESP32 闭环

## 固定优先环境

```powershell
$IdfPath = 'E:\MCU\esp32\.espressif\v5.5.3\esp-idf'
& "$IdfPath\export.ps1"
idf.py build
```

如果这个路径不存在，再搜索 `C:\Espressif`、`%USERPROFILE%\esp`、`E:\MCU\esp32\.espressif`。

## 端口选择

先列端口：

```powershell
python -m serial.tools.list_ports -v
[System.IO.Ports.SerialPort]::GetPortNames()
Get-PnpDevice -Class Ports
```

判断规则：

- `VID_303A` 常见于 Espressif USB/JTAG/CDC。
- `CH340/CH343/CP210x/FTDI` 可能是外置 USB 串口。
- 蓝牙串口通常不是烧录口。
- 设备管理器有端口但 pyserial 看不到时，通常是驱动异常、端口残留或被占用。

端口未知时，询问用户；端口已知时，直接执行。

## 常用命令

```powershell
idf.py build
idf.py -p COM28 flash
idf.py -p COM28 monitor
idf.py -p COM28 flash monitor
idf.py fullclean
```

`fullclean` 只在 CMake/配置状态明显损坏时使用；不要把它当成默认第一步。

## 日志采集

优先保存完整日志文件，便于多轮对比：

```powershell
python <技能目录>\scripts\serial-capture.py --port COM28 --baud 115200 --seconds 90 --output logs\esp32_run.log
```

必要时提高波特率，例如 `921600`，但先尊重项目默认。

## ESP32 常见根因线索

- `Task watchdog got triggered`：任务长时间不 yield、死循环、锁等待、外设阻塞。
- `Guru Meditation`：解析 backtrace，确认 EXCVADDR、PC、任务名。
- `heap_caps_malloc failed`：看请求大小、capability、最大连续块。
- 摄像头帧分配失败：PSRAM 碎片、LVGL 解码缓存、大图片、DMA buffer 过大。
- `Brownout` 或随机复位：先考虑电源和 USB 线。
- `invalid header` / boot loop：分区、bootloader、flash mode/size/freq、烧录偏移。
- 外设 init 失败：GPIO 冲突、时钟、复位脚、电源使能、I2C/SPI 速率。

## 推荐临时观测点

```c
ESP_LOGI(TAG, "heap internal=%u psram=%u min=%u largest=%u",
         heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
         heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
         heap_caps_get_minimum_free_size(MALLOC_CAP_8BIT),
         heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM));
```

```c
ESP_LOGI(TAG, "task stack high water: %s=%u",
         pcTaskGetName(NULL), uxTaskGetStackHighWaterMark(NULL));
```

## 验证上线链路

对主从机/MQTT/ESP-NOW/串口协议，按顺序确认：

1. 从机启动成功。
2. 从机连上网络/总线。
3. 主机收到 announce/heartbeat。
4. 主机设备模型更新 online。
5. LVGL 收到 UI event 或刷新。
6. 控制命令发出。
7. 从机执行并回 ACK。
8. UI 状态与真实硬件一致。
