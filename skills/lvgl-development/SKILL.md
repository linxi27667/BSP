# LVGL 开发专家

LVGL UI 开发全流程技能：XML 生成 → CLI 导出 → 分层架构 → 编译调试 → 视觉验证。

## 核心能力

| 能力 | 说明 |
|------|------|
| **XML UI 生成** | 根据需求生成 LVGL Pro XML 代码 |
| **CLI 代码导出** | 调用 lved-cli.js 导出 C 代码 |
| **分层架构设计** | MVP + PageManager 架构，Front/Pages/Components 三层解耦 |
| **项目移植** | 将生成代码集成到参考项目 |
| **编译调试** | CMake 构建 + 错误诊断 |
| **视觉验证** | MCP 无头模拟器渲染 + 截图调试闭环 |

## 工具路径

| 工具 | 路径 |
|------|------|
| **CLI 工具** | `E:\MCU\lvgl_tools\lvgl-cli\LVGL_Pro_CLI-1.1.2-windows\lved-cli.js` |
| **参考项目** | `E:\MCU\lvgl_tools\lv_port_pc_vscode\lv_port_pc_vscode` |
| **LVGL Pro 项目** | `E:\MCU\lvgl_editor` |
| **高昌项目** | `E:\MCU\gaochang\code\lvgl\lv_port_pc_vscode\lv_port_pc_vscode` |
| **智慧庭院** | `E:\MCU\esp32\xiaozhi1111111111111111111111111\garden\lvgl_sim` |

## 分层架构规范

### 推荐架构：MVP + PageManager（基于 X-TRACK 6.2K 星项目）

这是 LVGL 社区公认的架构标杆，采用 **MVP（Model-View-Presenter）+ PageManager** 模式。

```
main/UI/
├── Inc/                              ← 头文件层
│   ├── ui.h                          ← UI 总入口
│   ├── ui_front.h                    ← 前台/导航层
│   ├── ui_pages.h                    ← 页面管理器
│   └── ui_components.h               ← 组件声明
│
├── Src/                              ← 实现层
│   ├── ui.c                          ← UI 初始化、页面切换
│   ├── ui_front.c                    ← 前台导航、状态栏、底部栏
│   ├── PageManager/                  ← 页面管理框架（栈导航 + 动画）
│   │   ├── PageManager.h             ← 管理器核心
│   │   ├── PageBase.h                ← 页面基类（生命周期）
│   │   ├── PM_Router.c               ← 路由（push/pop）
│   │   └── PM_Anim.c                 ← 切换动画
│   ├── pages/                        ← 页面文件夹（MVP 三件套）
│   │   ├── ui_page_home/
│   │   │   ├── ui_page_home.h        ← Presenter（控制器）
│   │   │   ├── ui_page_home.c        ← 业务逻辑
│   │   │   └── ui_page_home_view.c   ← View（纯 UI 绘制）
│   │   ├── ui_page_settings/
│   │   │   ├── ui_page_settings.h
│   │   │   ├── ui_page_settings.c
│   │   │   └── ui_page_settings_view.c
│   │   └── ui_page_data/
│   │       ├── ui_page_data.h
│   │       ├── ui_page_data.c
│   │       └── ui_page_data_view.c
│   └── components/                   ← 可复用组件
│       ├── ui_comp_button.c          ← 按钮组件
│       ├── ui_comp_card.c            ← 卡片组件
│       └── ui_comp_slider.c          ← 滑块组件
│
└── generated/                        ← LVGL Pro 生成代码（只读）
    ├── ui_project_gen.c
    ├── ui_project_gen.h
    ├── screens/
    │   ├── screen_home_gen.c
    │   └── screen_settings_gen.c
    └── components/
        ├── comp_button_gen.c
        └── comp_card_gen.c
```

### 分层职责

| 层 | 职责 | 文件示例 |
|----|------|----------|
| **Front 前台层** | 导航栏、状态栏、全局 UI 元素 | `ui_front.c` |
| **Pages 页面层** | 各功能页面 MVP 三件套 | `pages/ui_page_*/` |
| **Components 组件层** | 可复用 UI 组件 | `components/ui_comp_*.c` |
| **Generated 生成层** | LVGL Pro 导出的代码（不修改） | `generated/*_gen.c` |
| **PageManager** | 页面栈管理、切换动画、生命周期 | `PageManager/` |

### MVP 模式说明

| 角色 | 职责 | 文件 |
|------|------|------|
| **Model** | 数据获取、业务逻辑 | `ui_page_xxx.c` |
| **View** | 纯 UI 绘制、不涉及业务 | `ui_page_xxx_view.c` |
| **Presenter** | 协调 Model 和 View | `ui_page_xxx.h` |

### 架构原则

1. **生成代码不修改**：`*_gen.c` 只读，重新导出会覆盖
2. **用户代码分离**：自定义逻辑写在 `ui_page_*.c` 中
3. **页面独立**：每个页面一个文件夹，互不依赖
4. **组件复用**：通用组件提取到 `components/`
5. **Front 层统一**：导航、状态栏等全局元素集中管理
6. **View 层纯净**：`*_view.c` 只负责 UI 绘制，不包含业务逻辑

## 工作流程

### 完整流程

```
1. AI 生成 XML → 保存到 E:\MCU\lvgl_editor\projects\xxx\
2. CLI 导出 C 代码 → lved-cli.js generate 项目路径
3. 移植到参考项目 → 复制 .c/.h 到 lv_port_pc_vscode\main\UI\
4. CMake 编译 → 启动 SDL 窗口预览
5. 视觉验证 → MCP 渲染 或 截图调试
6. 自动调试 → 分析编译错误 → 修复 → 重新编译
```

### CLI 命令

```bash
# 生成 C 代码
node "E:\MCU\lvgl_tools\lvgl-cli\LVGL_Pro_CLI-1.1.2-windows\lved-cli.js" generate "项目路径"

# 验证 XML
node "E:\MCU\lvgl_tools\lvgl-cli\LVGL_Pro_CLI-1.1.2-windows\lved-cli.js" validate "项目路径"

# 编译参考项目
cd E:\MCU\lvgl_tools\lv_port_pc_vscode\lv_port_pc_vscode\build
cmake ..
cmake --build .
```

## XML 生成规范

### 项目结构

```
project.xml          ← 项目配置（屏幕尺寸、LVGL 版本）
globals.xml          ← 全局样式、颜色、字体

screens/
├── screen_home.xml      ← 首页
├── screen_settings.xml  ← 设置页
└── screen_data.xml      ← 数据页

components/
├── button.xml           ← 可复用按钮组件
├── card.xml             ← 卡片组件
└── navbar.xml           ← 导航栏组件
```

### XML 示例

**项目配置**：
```xml
<project name="my_project">
    <targets>
        <target name="full_view">
            <display width="800" height="480" />
        </target>
    </targets>
</project>
```

**屏幕**：
```xml
<screen permanent="true">
    <view>
        <lv_label text="Hello World" align="center" />
        <lv_button align="bottom_mid">
            <lv_label text="Next" />
            <screen_create_event screen="screen_next" />
        </lv_button>
    </view>
</screen>
```

**组件**：
```xml
<component>
    <api>
        <prop name="label" type="string" default="Button" />
    </api>
    <view extends="lv_button">
        <lv_label text="$label" align="center" />
    </view>
</component>
```

## 页面切换模式

### 永久屏幕 vs 动态屏幕

| 类型 | 属性 | 说明 |
|------|------|------|
| **永久屏幕** | `permanent="true"` | 创建一次，不删除，状态保持 |
| **动态屏幕** | 默认 | 打开时创建，关闭时删除 |

### 切换事件

```xml
<!-- 加载已存在的永久屏幕 -->
<screen_load_event screen="screen_main" anim_type="move_top" duration="500" />

<!-- 创建新的动态屏幕 -->
<screen_create_event screen="screen_about" anim_type="move_top" duration="500" />
```

## CMake 集成

### 添加生成代码到 CMakeLists.txt

```cmake
# UI 生成代码
file(GLOB UI_GEN_SOURCES
    "${PROJECT_SOURCE_DIR}/main/UI/generated/*.c"
    "${PROJECT_SOURCE_DIR}/main/UI/generated/screens/*.c"
    "${PROJECT_SOURCE_DIR}/main/UI/generated/components/*.c"
)

# UI 用户代码
file(GLOB UI_SOURCES
    "${PROJECT_SOURCE_DIR}/main/UI/Src/*.c"
    "${PROJECT_SOURCE_DIR}/main/UI/Src/pages/*.c"
    "${PROJECT_SOURCE_DIR}/main/UI/Src/components/*.c"
)

target_sources(lvgl PRIVATE ${UI_GEN_SOURCES} ${UI_SOURCES})
```

## 视觉验证

### 方法 1：MCP 无头模拟器（快速预览，无需硬件）

**MCP 工具列表**：

| 类别 | 工具 | 功能 |
|------|------|------|
| **渲染** | `lvgl_render` | 渲染代码片段 + 错误诊断 + 样式分析 |
| | `lvgl_render_full` | 渲染完整 C 文件 |
| | `lvgl_render_multi` | 多分辨率预览（800x480, 1024x600, 480x320） |
| **分析** | `lvgl_analyze_styles` | 分析 widget 样式继承链 |
| | `lvgl_suggest_fix` | LVGL v9 API 错误修复建议 |
| **模板** | `lvgl_template_button` | 按钮模板（simple/gradient/icon/toggle） |
| | `lvgl_template_list` | 列表模板（simple/icon/card） |
| | `lvgl_template_card` | 卡片模板（basic/media/form） |
| | `lvgl_template_navigation` | 导航模板（top/bottom/sidebar） |
| **配置** | `lvgl_set_resolution` | 设置分辨率 |
| | `lvgl_get_config` | 查看完整配置 |
| | `lvgl_clear_cache` | 清除编译缓存 |
| | `lvgl_add_include_path` | 添加自定义 include 路径 |

**使用示例**：

```
# 直接渲染 UI 代码
lvgl_render with code="lv_obj_t *btn = lv_button_create(screen); lv_obj_set_size(btn, 120, 50); lv_obj_set_style_bg_color(btn, lv_color_hex(0x2196F3), 0);"

# 多分辨率预览
lvgl_render_multi with code="..."

# 获取 UI 模板
lvgl_template_button with variant="gradient" text="Submit"

# API 错误诊断
lvgl_suggest_fix with error_message="lv_btn_create undeclared"

# 样式分析
lvgl_analyze_styles with widget_id="btn1"
```

**MCP 配置**（添加到 settings.json）：

```json
{
  "mcpServers": {
    "lvgl-simulator": {
      "command": "npx",
      "args": ["lvgl-mcp-server"]
    }
  }
}
```

**前置条件**：
- Windows 10/11 x64
- Visual Studio Build Tools 2019+ (C/C++ workload)
- CMake 3.16+ (included with ESP-IDF)
- Ninja 1.10+ (included with ESP-IDF)
- Node.js 18+

**安装**：
```powershell
npm install -g lvgl-mcp-server
```

### 方法 2：截图调试闭环（项目已支持）

**工作流程**：
```
AI 修改代码 → 编译 → 运行 exe → 截图 → AI 查看截图 → 判断是否需要调整 → 循环
```

**前置条件**：
1. 项目已启用 `LV_USE_SNAPSHOT = 1`（已在 lv_conf.h 中配置）
2. 项目已添加 CLI 参数支持 `--export-screenshot=<path>`
3. 已添加 PNG 导出代码（使用 lodepng）

**使用方式**：

```bash
# 编译
cd E:\MCU\esp32\xiaozhi1111111111111111111111111\garden\lvgl_sim\build3
mingw32-make

# 运行并截图
.\garden_sim.exe --export-screenshot=output.png --timeout=100
```

**AI 调用流程**：
1. 修改 UI 代码
2. 编译: `cd build3 && mingw32-make`
3. 截图: 运行 exe 导出 PNG
4. 查看: 用 `look_at` 工具查看截图
5. 判断: 根据截图决定下一步修改

**需要添加的代码**：

SDL_main.c 添加截图参数支持：
```c
// 在 main() 开头添加参数解析
if (argc > 1 && strncmp(argv[1], "--export-screenshot=", 19) == 0) {
    const char *output_path = argv[1] + 19;
    int timeout_ms = 100;  // 默认等待 100ms 让 UI 渲染完成
    if (argc > 2 && strncmp(argv[2], "--timeout=", 10) == 0) {
        timeout_ms = atoi(argv[2] + 10);
    }
    
    // ... 创建 UI 后，等待渲染
    for (int i = 0; i < timeout_ms / 5; i++) {
        lv_timer_handler();
        usleep(5000);
    }
    
    // 截图导出
    ui_export_screenshot(output_path);
    return 0;  // 直接退出，不显示窗口
}
```

新建 ui_export.c（截图导出函数）：
```c
#include "lvgl/lvgl.h"
#include <stdio.h>
#include <stdlib.h>

// 使用 LVGL 内置的 lodepng
extern unsigned lodepng_encode32_file(const char *filename, 
    const unsigned char *image, unsigned w, unsigned h);

void ui_export_screenshot(const char *filename) {
    lv_obj_t *screen = lv_screen_active();
    lv_draw_buf_t *draw_buf = lv_snapshot_take(screen, LV_COLOR_FORMAT_ARGB8888);
    
    if (draw_buf == NULL) {
        printf("Screenshot failed!\n");
        return;
    }
    
    // 转换 ARGB 到 RGBA（lodepng 需要 RGBA）
    uint32_t w = draw_buf->header.w;
    uint32_t h = draw_buf->header.h;
    uint8_t *data = draw_buf->data;
    
    // 交换 R 和 B（ARGB -> RGBA）
    for (uint32_t i = 0; i < w * h; i++) {
        uint8_t a = data[i * 4 + 3];
        uint8_t r = data[i * 4 + 2];
        uint8_t g = data[i * 4 + 1];
        uint8_t b = data[i * 4 + 0];
        data[i * 4 + 0] = r;
        data[i * 4 + 1] = g;
        data[i * 4 + 2] = b;
        data[i * 4 + 3] = a;
    }
    
    lodepng_encode32_file(filename, data, w, h);
    lv_draw_buf_destroy(draw_buf);
    printf("Screenshot saved: %s\n", filename);
}
```

## 调试流程

### 编译错误诊断

1. 运行 CMake 构建
2. 捕获编译错误输出
3. 分析错误类型：
   - **头文件缺失**：检查 include 路径
   - **API 不兼容**：LVGL v8→v9 迁移
   - **链接错误**：检查 CMake 源文件列表
4. 修复后重新编译

### 运行时调试

1. 启动 SDL 窗口 或 MCP 渲染
2. 截图导出（如项目支持）
3. 使用 `look_at` 工具查看截图
4. 判断 UI 是否符合预期
5. 迭代修改

## LVGL v9 API 速查

| 旧 API (v8) | 新 API (v9) |
|------------|------------|
| `lv_btn_create` | `lv_button_create` |
| `lv_img_create` | `lv_image_create` |
| `lv_imgbtn_create` | `lv_imagebutton_create` |
| `lv_kb_create` | `lv_keyboard_create` |
| `lv_btnm_create` | `lv_buttonmatrix_create` |
| `lv_scr_load` | `lv_screen_load` |
| `lv_scr_load_anim` | `lv_screen_load_anim` |
| `lv_obj_set_style_local_*` | `lv_obj_set_style_*(obj, value, selector)` |

## 命名规范（LVGL 官方推荐）

| 类型 | 前缀 | 示例 |
|------|------|------|
| 图片 | `icon_` / `img_` | `icon_home`, `img_background` |
| 字体 | `font_<size>_<weight>` | `font_16_bold`, `font_roboto_14_regular` |
| 样式 | `style_` | `style_button`, `style_dark_button` |
| 主题 | `subject_` | `subject_settings`, `subject_home` |
| Widget | `wd_` | `wd_menu`, `wd_statusbar`, `wd_clock` |

## 参考项目结构

```
E:\MCU\lvgl_tools\lv_port_pc_vscode\lv_port_pc_vscode\
├── main/
│   ├── src/
│   │   └── SDL_main.c          ← 主程序入口
│   └── UI/
│       ├── Inc/
│       │   └── ui.h
│       └── Src/
│           └── ui.c
├── lvgl/                       ← LVGL 库
└── CMakeLists.txt
```

## 使用示例

### 场景：创建花园监控系统 UI

**用户输入**："帮我设计一个花园监控界面，包含温度、湿度、灯光控制"

**AI 执行**：

1. **生成 XML**：
   - `project.xml` - 项目配置
   - `screens/screen_garden.xml` - 花园主页
   - `components/comp_sensor_card.xml` - 传感器卡片组件

2. **保存文件**：
   ```
   E:\MCU\lvgl_editor\projects\garden_monitor\
   ├── project.xml
   ├── globals.xml
   ├── screens/
   │   └── screen_garden.xml
   └── components/
       └── comp_sensor_card.xml
   ```

3. **导出 C 代码**：
   ```bash
   node "E:\MCU\lvgl_tools\lvgl-cli\LVGL_Pro_CLI-1.1.2-windows\lved-cli.js" generate "E:\MCU\lvgl_editor\projects\garden_monitor"
   ```

4. **移植到参考项目**：
   - 复制 `*_gen.c/.h` 到 `main/UI/generated/`
   - 更新 `CMakeLists.txt`
   - 修改 `ui.c` 调用初始化函数

5. **编译验证**：
   ```bash
   cd E:\MCU\lvgl_tools\lv_port_pc_vscode\lv_port_pc_vscode\build
   cmake --build .
   ```

6. **视觉验证**：
   - 使用 MCP 渲染预览
   - 或截图调试闭环

7. **调试修复**：
   - 分析编译错误
   - 修复代码
   - 重新编译
