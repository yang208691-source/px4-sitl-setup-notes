# PX4 二次开发日志 01：写出第一个自定义模块，并建立观测能力

> **日期**：2026-09-25
> **环境**：Windows 11 + WSL2 Ubuntu 24.04 + PX4 **v1.15.4** + Gazebo Harmonic 8.15.0
> **前置**：环境搭建见 [`PX4-SITL-setup-log.md`](./PX4-SITL-setup-log.md)
> **结果**：从"能跑仿真"到"能改飞控"，跑通完整开发闭环
> **性质**：本文记录 **6 个新坑** + PX4 模块机制 + **控制链路频率地图** + 排故方法论

---

## 关于这份记录

**作者是飞控领域的初学者** —— 刚毕业入职，从零开始学 PX4 二次开发，没有师兄带，也没有既有技术积累可接手。

**这不是一份权威教程，而是一个新人边踩坑边学习的真实过程。**

读的时候请注意：

| 标记 | 含义 |
|---|---|
| ✅ | **实测数据和复现步骤是可靠的** —— 每条都实际跑过，有终端输出佐证 |
| ⚠️ | **原理性解释可能有理解偏差** —— 我尽力了，但受限于当前水平，欢迎指正 |
| 📌 | **版本敏感** —— 所有内容基于 PX4 **v1.15.4**，其他版本可能不同 |

**如果发现错误，欢迎提 Issue 或 PR** —— 这对我是很有价值的反馈。

---

## 读之前：本篇的定位

环境搭建那篇讲的是**"让 PX4 跑起来"**——坑 90% 在网络和构建系统。

本篇讲的是**"开始改 PX4"**——坑全在**飞控开发本身**：模块机制、uORB、日志格式、数据类型、平台差异。

**这是从「用 PX4」到「改 PX4」的分界线。**

---

## 写给谁看

如果你正在做 PX4 二次开发，并且遇到下面任意一条，这篇就是给你写的：

- 想加自己的模块，但**不知道文件放哪、怎么注册进构建系统**
- 编译报 `'_EXPORT' does not name a type` 或类似的符号错误
- 飞完了想分析日志，`ls *.ulg` 却**什么也找不到**
- 用 pyulog 画图报 `KeyError: 'q'`
- 画出来的曲线 **X 轴是 1.75e11 秒**（五千年）
- 在 SITL 里敲 `top` 报 `Invalid command`
- **不知道 PX4 的控制器跑在什么频率上，各模块怎么串联**

---

## 本篇成果速查

| 能力 | 状态 |
|---|---|
| 打通"改代码 → 编译 → 进仿真 → 看到效果"闭环 | ✅ |
| 写出并运行自定义 PX4 模块（订阅真实 uORB 数据） | ✅ |
| 理解 PX4 的 Kconfig 模块注册机制 | ✅ |
| 日志记录 → `.ulg` → pyulog → 曲线 → 判读 | ✅ |
| **看懂 PX4 多旋翼的完整控制链路与频率分层** | ✅ |
| 掌握运行时调试命令（跨平台注意事项） | ✅ |

---

# 一、PX4 模块机制

## 1.1 Kconfig 驱动的构建体系（v1.15.4）

**关键发现**：v1.15.4 已经使用 **Kconfig** 体系，`src/modules/CMakeLists.txt` **不存在**。

```
src/examples/Kconfig          内容：rsource "*/Kconfig"
        │
        │  自动扫描所有子目录的 Kconfig
        ▼
   ┌─────────────┬──────────────┐
   │ hello/      │ px4_hello/   │   ← 每个模块"自包含"
   │  Kconfig    │  Kconfig     │      自己的编译规则 + 自己的启用开关
   │  CMakeLists │  CMakeLists  │
   └─────────────┴──────────────┘
        │
        ▼
boards/px4/sitl/default.px4board
   CONFIG_EXAMPLES_HELLO=y
   CONFIG_EXAMPLES_PX4_HELLO=y      ← 只有写了 =y，才会被编进固件
```

### 加一个模块 = 三件事，全是"新增"不是"改写"

1. 建目录
2. 放 `CMakeLists.txt` + `Kconfig` + 源码
3. 在 `boards/px4/sitl/default.px4board` 加一行 `CONFIG_xxx=y`

> **全项目唯一需要修改的既有文件就是 `default.px4board`。** 因为上级 Kconfig 里的 `rsource "*/Kconfig"` 会自动发现新目录。

## 1.2 模块的三层结构

PX4 官方 `hello` 示例是三个文件，各司其职：

| 文件 | 职责 |
|---|---|
| `hello_start.cpp` | 定义 `hello_main(argc, argv)` —— **pxh 里敲命令时被调用的函数**，处理 `start`/`stop`/`status` |
| `hello_main.cpp` | 定义 `PX4_MAIN` —— **任务真正执行的入口** |
| `hello_example.cpp/.h` | 业务逻辑本体 |

调用链：

```
pxh> hello start
   │
   ├─ hello_main(argc, argv)              [hello_start.cpp]  ← Shell 命令层
   │     └─ px4_task_spawn_cmd(...)       创建独立任务
   │
   └─ PX4_MAIN                            [hello_main.cpp]    ← 任务入口层
         └─ HelloExample::main()          [hello_example.cpp] ← 业务逻辑层
```

> **这个三层拆分是历史包袱**——为了同时兼容 NuttX 和 POSIX 两种平台。现代 PX4 模块用**单文件 + `start`/`stop`/`status`** 就够了，更清晰、出错点更少。

## 1.3 完整可复现的模板：`px4_hello`

**目录**：`src/examples/px4_hello/`

### `CMakeLists.txt`

```cmake
px4_add_module(
	MODULE examples__px4_hello
	MAIN px4_hello
	STACK_MAIN 2048
	SRCS
		px4_hello.cpp
	DEPENDS
		uORB
	)
```

| 字段 | 说明 |
|---|---|
| `MODULE examples__px4_hello` | 模块名必须**全局唯一**，重名会链接冲突 |
| `MAIN px4_hello` | 决定生成哪个入口函数（`px4_hello_main`） |
| `STACK_MAIN 2048` | 栈大小。**SITL 上无所谓，NuttX 真机上栈溢出直接死机**，习惯要养好 |
| `DEPENDS uORB` | **关键**：不声明会链接不过（用 `uORB::Subscription` 时必须加） |

### `Kconfig` ⚠️ 必须用 **Tab** 缩进

```kconfig
menuconfig EXAMPLES_PX4_HELLO
	bool "px4_hello"
	default n
	---help---
		Enable support for px4_hello, a custom uORB subscription demo
```

> **验证缩进的方法是 `cat -A Kconfig`**，看到 `^I` 才是 Tab。空格会让 Kconfig 解析失败。
> **建议用 heredoc 创建**（`cat > Kconfig << 'EOF'`），粘贴到终端时 Tab 原样保留，比在编辑器里手打可靠。

### `px4_hello.cpp`

```cpp
#include <px4_platform_common/module.h>
#include <px4_platform_common/log.h>
#include <px4_platform_common/tasks.h>
#include <px4_platform_common/posix.h>
#include <px4_platform_common/px4_config.h>
#include <string.h>

#include <uORB/Subscription.hpp>
#include <uORB/topics/vehicle_attitude.h>

extern "C" __EXPORT int px4_hello_main(int argc, char *argv[]);

static int daemon_task = -1;
static volatile bool task_should_exit = false;

static int px4_hello_task(int argc, char *argv[])
{
	PX4_INFO("=== px4_hello started, built %s %s ===", __DATE__, __TIME__);

	// 订阅姿态话题：机体坐标系，四元数 q = [w, x, y, z]
	uORB::Subscription attitude_sub{ORB_ID(vehicle_attitude)};
	vehicle_attitude_s attitude{};

	for (int i = 0; i < 20 && !task_should_exit; ++i) {
		if (attitude_sub.copy(&attitude)) {
			PX4_INFO("q=[%.4f %.4f %.4f %.4f]  ts=%llu us",
				 (double)attitude.q[0], (double)attitude.q[1],
				 (double)attitude.q[2], (double)attitude.q[3],
				 (unsigned long long)attitude.timestamp);

		} else {
			PX4_WARN("no vehicle_attitude yet (i=%d)", i);
		}

		px4_usleep(500000);   // 500 ms
	}

	daemon_task = -1;
	PX4_INFO("=== px4_hello done ===");
	return 0;
}

int px4_hello_main(int argc, char *argv[])
{
	if (argc < 2) {
		PX4_WARN("usage: px4_hello {start|stop|status}");
		return 1;
	}

	if (!strcmp(argv[1], "start")) {
		if (daemon_task > 0) {
			PX4_WARN("already running");
			return 0;
		}

		task_should_exit = false;
		daemon_task = px4_task_spawn_cmd("px4_hello",
						 SCHED_DEFAULT,
						 SCHED_PRIORITY_MAX - 5,
						 2048,
						 px4_hello_task,
						 (char *const *)argv);

		if (daemon_task < 0) {
			PX4_ERR("failed to spawn task");
			return 1;
		}

		return 0;
	}

	if (!strcmp(argv[1], "stop")) {
		if (daemon_task > 0) {
			task_should_exit = true;
			PX4_INFO("stopping");
		} else {
			PX4_WARN("not running");
		}

		return 0;
	}

	if (!strcmp(argv[1], "status")) {
		// 如实反映任务真实状态：任务自己退出时会把 daemon_task 置回 -1
		if (daemon_task > 0) {
			PX4_INFO("running");
		} else {
			PX4_INFO("not running");
		}

		return 0;
	}

	PX4_WARN("usage: px4_hello {start|stop|status}");
	return 1;
}
```

### 运行验证

```bash
cd ~/PX4-Autopilot
HEADLESS=1 make px4_sitl gz_x500
```

```
pxh> px4_hello start
pxh> px4_hello status
```

**预期**：打印编译时间戳 → 20 行 `q=[...]`（`ts` 每次 +500000 us）→ `=== px4_hello done ===`。

> **做了个修正**：官方 `hello` 示例有个状态 bug —— 任务退出后 `hello status` 仍报 `is running`，因为 `HelloExample::main()` 返回前没清标志位。
> **`px4_hello` 里用 `daemon_task` 本身作为状态**（任务退出时置回 -1），`status` 就如实了。
> **教训：`status` 的输出不一定可信。** 试飞前的检查流程依赖它，一个小小的状态标志写错，可能让你在关键时刻判断失误。

---

# 二、6 个新坑

## 坑 1：VS Code 装错扩展 —— Dev Containers ≠ Remote-WSL

### 现象

VS Code 连 WSL 失败，日志爆出：

```
Dev Containers 0.469.0 in VS Code 1.137.0
Host server: Error: spawn docker ENOENT
curl: (35) Recv failure: Connection reset by peer
Err: https://download.docker.com/... NO_PUBKEY 7EA0A9C3F273FCD8
E: The repository 'https://download.docker.com/linux/ubuntu noble InRelease' is not signed.
Exit code 100
```

### 根因

装的是 **Dev Containers**（远程容器），不是 **Remote - WSL**。前者需要 Docker，于是它自动开始装 Docker，然后在受限网络下一路失败。

**为什么会被带偏**：PX4 仓库里有 `.devcontainer/devcontainer.json`，VS Code 打开时右下角会弹 **"Reopen in Container"**，点了就掉进这条路。

### 解法

| 扩展 | 作用 | 需要吗 |
|---|---|---|
| `Remote - WSL`（`ms-vscode-remote.remote-wsl`） | 直接连 WSL 写代码 | ✅ **这个** |
| `Dev Containers` | 在 Docker 容器里写代码 | ❌ 不需要 |

**最可靠的连接方式**：别用欢迎界面，直接在 WSL 终端里

```bash
cd ~/PX4-Autopilot
code .
```

左下角显示 `WSL: Ubuntu-24.04` = 成功；显示 `Dev Container: ...` = 错了。

### 遗留清理（**必做**）

Dev Containers 用 **root 权限**写了一个坏的 apt 源。不删的话，以后**每次 `apt update` 都会报错**：

```bash
sudo rm -f /etc/apt/sources.list.d/docker.list /etc/apt/trusted.gpg.d/docker.asc
sudo apt update
```

### 教训

> **看官方文档要先判断"这段是针对哪个场景写的"。**
> PX4 文档讲 VS Code 有**两套方案**：原生 WSL 和 devcontainer。前者给"已经有 Linux 环境"的人，后者给"什么都不想装"的人。
> **已经有跑通的 WSL 环境，再套一层 Docker 是纯粹的自找麻烦**——尤其在网络受限的情况下。

---

## 坑 2：`_EXPORT` 少一个下划线

### 现象

```
px4_hello.cpp:9:12: error: '_EXPORT' does not name a type
    9 | extern "C" _EXPORT int px4_hello_main(int argc, char *argv[])
       |            ^~~~~~~
compilation terminated due to -Wfatal-errors.
```

### 根因

正确写法是 **`__EXPORT`（两个下划线）**。

看编译命令行里的两个关键选项：

```
-fvisibility=hidden  -include visibility.h
```

- `-fvisibility=hidden`：所有符号**默认对外隐藏**
- `__EXPORT`：展开成 `__attribute__((visibility("default")))`，把符号**显式导出**
- `-include visibility.h`：强制包含定义它的头文件

**符号不导出 → pxh 的 shell 找不到 `px4_hello_main` → 敲 `px4_hello start` 报 `command not found`。**

### 教训

> 嵌入式里**"默认全藏、只导出必须暴露的接口"**是常见模式：减少符号表、避免命名冲突、加快加载。
> 写模块时**入口函数必须加 `__EXPORT`**，这是 PX4 的惯例。

### 附带：怎么读 PX4 的编译输出

第一次看会被吓到，其实**大部分是历史遗留警告，和你的错误无关**：

| 输出 | 要不要管 |
|---|---|
| `Policy CMP0148 is not set` | ❌ CMake 策略警告，官方自己的问题 |
| `CMake Deprecation Warning ... lockstep_scheduler` | ❌ 同上 |
| `Error while finding module specification for 'symforce.symbolic'` | ❌ 缺 Python 包，可选项用不到 |
| `Could NOT find Java` | ❌ 同上 |
| `SyntaxWarning: invalid escape sequence '\s'` | ❌ PX4 自己 Python 脚本的问题 |
| **`FAILED:` / `error:`** | ✅ **只有这个要找** |

> **排故时只盯 `error:` 和 `FAILED:`，其余一概略过。** 不然会被淹没在噪音里。

---

## 坑 3：日志不在当前目录，按日期分子目录

### 现象

```bash
cd ~/PX4-Autopilot/build/px4_sitl_default/rootfs/log/
LATEST=$(ls -t *.ulg | head -1)
ls: cannot access '*.ulg': No such file or directory     ← 真正的信息
最新日志:                                                ← $LATEST 是空的
FileNotFoundError: ... No such file or directory: ''     ← 空文件名导致的二次报错
```

### 根因

`logger` 按日期分目录：**`log/YYYY-MM-DD/HH_MM_SS.ulg`**

```bash
$ ls
2026-09-19  2026-09-20  2026-09-25
```

`*.ulg` 只扫当前层，没进子目录。

### 解法

```bash
# 跨所有日期目录按时间取最新
LATEST=$(ls -t */*.ulg | head -1)
```

### 教训

> **看懂 log 的提示**：PX4 启动时会打印日志文件的完整路径 —— `INFO [logger] [logger] ./log/2026-09-25/17_00_53.ulg`。
> **不要猜路径，先看程序自己说了什么。**
>
> **读日志的铁律：从最早的一条异常往下读，不要盯着最后那条报错。**
> 最后那条通常只是前面失败的连锁反应。这次 `ls: cannot access` 出现在 `FileNotFoundError` 的**上面三行**，它才是起点。

---

## 坑 4：pyulog 里数组字段是**展开**的

### 现象

```python
KeyError: 'q'
  File "plot_attitude.py", line 26, in main
    roll, pitch, yaw = quat_to_euler(att.data['q'])
```

### 根因

`q` 在 PX4 里是 `float[4]` 数组。**ULog 文件格式把定长数组拆成独立字段存储**，pyulog 读出来的键名是：

```
q[0]  q[1]  q[2]  q[3]      ← 而不是一个 'q'
```

### 解法

写一个兼容两种命名的读取函数：

```python
def get_quat(d, base='q'):
    """兼容 pyulog 两种字段命名：'q' 或 'q[0]'..'q[3]'"""
    if base in d:
        return np.asarray(d[base])
    keys = [f'{base}[{i}]' for i in range(4)]
    if all(k in d for k in keys):
        return np.column_stack([d[k] for k in keys])
    raise KeyError(f"找不到 {base}。可用字段: {sorted(d.keys())}")
```

### 教训（**比解法本身更重要**）

> 注意 `raise` 那句：**报错时把诊断信息一并抛出来**。
>
> **「与其猜，不如让代码把可选项打给你看」。** 你在 PX4 上会反复遇到"名字对不上"的问题（参数名、话题名、字段名），这个习惯能省掉大量试错。
>
> **通用动作：任何话题，先 dump 出它的字段和取值范围，再谈分析。不要凭字段名猜含义。**
>
> ```python
> from pyulog import ULog
> ulg = ULog("xxx.ulg")
> d = {x.name: x for x in ulg.data_list}
> for k in sorted(d['vehicle_attitude_setpoint'].data.keys()):
>     v = d['vehicle_attitude_setpoint'].data[k]
>     print(f"  {k:24s} 范围=[{v.min():.4f}, {v.max():.4f}]")
> ```

---

## 坑 5：uint64 时间戳回绕 —— 图变成五千年

### 现象

画出来的曲线 **X 轴是 0 ~ 1.75e11 秒（约 5549 年）**，所有曲线被挤成一根竖线。

**Y 轴（角度）完全正常，只有 X 轴崩了。**

### 根因

```python
tav = (av.data['timestamp'] - t0) / 1e6      # t0 来自 vehicle_attitude
```

链条：

1. **`vehicle_angular_velocity` 由传感器模块发布，比 `vehicle_attitude`（EKF 输出）启动更早**
2. 所以 `av.timestamp[0] < att.timestamp[0]`，相减得到**负数**
3. PX4 的 timestamp 是 **`uint64`**（无符号 64 位）
4. **uint64 做减法得到负数会回绕**：`0 - 1 = 18446744073709551615`
5. 除以 `1e6` 后变成 1e13 量级的"秒数"

**它不报错，只是给你一个看起来"正常"的巨大数字。**

### 解法

```python
def to_sec(ts, t0, name=''):
    """uint64 时间戳 -> 秒。显式转 int64，避免无符号回绕。"""
    out = (np.asarray(ts, dtype=np.int64) - np.int64(t0)) / 1e6
    if out.size and (out.min() < -1.0 or out.max() > 1e6):
        print(f"  !! {name} 时间范围异常: [{out.min():.3g}, {out.max():.3g}] s")
    return out
```

### 教训

> **PX4 里所有 `timestamp` 都是 `uint64`。任何时间戳相减之前，先显式转成有符号类型。**
> 这是嵌入式/飞控代码里最常见的**静默 bug** 之一——它不报错，只是给你一个看似合理的错数。
>
> **另外**：修 bug 时顺手加上自检（上面那个 `if out.min() < -1.0`）。**下次遇到同类问题，代码自己会告诉你。**

---

## 坑 6：`top` 是 NuttX 独有命令，SITL 上没有

### 现象

```
pxh> top
Invalid command: top
Invalid command: Invalid        ← 这行也很怪
type 'help' for a list of commands
```

### 根因

**PX4 有两套运行环境，命令集不完全一样。**

| | **SITL / POSIX** | **真机 / NuttX** |
|---|---|---|
| 本质 | 一个 **Linux 多线程进程** | **RTOS** 上的独立任务 |
| 系统命令 | 用 Linux 的（`top`/`htop`/`gdb`） | 用 NuttX 的（`top`/`free`/`ps`） |
| PX4 的 `top` | ❌ 不存在 | ✅ 存在 |

### 解法：SITL 上用 Linux 原生工具看线程

```bash
# 开另一个终端
pgrep -af px4
top -H -p $(pgrep -f "bin/px4" | head -1)     # -H 显示线程
# 或
htop -p $(pgrep -f "bin/px4" | head -1)
```

> PX4 在 SITL 里每个"任务"就是一个**线程**。`top -H` 能看到 `mc_att_control`、`ekf2`、`navigator` 各自的 CPU 占用 —— **这正是 NuttX 上 `top` 给你的信息**，只是换了个工具。

### 教训（**必须记住**）

> ### ⚠️ SITL 上学到的命令，上真机前要重新确认一遍
>
> **反着也会踩坑**：真机 NuttX 上 `htop`/`gdb`/`strace` 全都没有，**只有 `top`** —— 真机上的调试手段反而更少。

### 另一个必须记住的平台差异

| | SITL | 真机 NuttX |
|---|---|---|
| 任务间内存 | 共享地址空间，**越界不会立刻崩** | 每个任务独立栈，**栈溢出直接死机** |
| 调试 | GDB 随便断点 | 只能靠日志和 `dmesg` |
| 时序 | 不严格（有 lockstep 但仍是仿真） | **硬实时**，超时就是故障 |

> 所以 `CMakeLists.txt` 里的 `STACK_MAIN 2048` 不是装饰 —— **上真机时栈溢出是头号杀手之一。**

### 附带：`Invalid command: Invalid` 这行

PX4 的 shell 在第一次失败后，又把 `Invalid` 这个词当命令解析了一遍。**这是 pxh 的一个小瑕疵**，它本该只报一次。

**记住这个模式**：shell 的报错输出本身也可能有噪音。**以第一条异常为准。**

---

# 三、控制链路频率地图（核心数据）

**这份数据是理解 PX4 控制器的坐标系**。不知道谁在多少 Hz 上跑，就看不懂控制器为什么那么设计。

采集方式（SITL 的 `pxh>` 里）：

```
pxh> uorb top -1
pxh> work_queue status
```

## 3.1 完整控制链路

| 层级 | 模块 | 输出话题 | 频率 |
|---|---|---|---|
| **轨迹层** | `navigator` / `flight_mode_manager` | `trajectory_setpoint` | **50 Hz** |
| ↓ | | `position_setpoint_triplet` | 22 Hz |
| **位置环** | `mc_pos_control` | `vehicle_attitude_setpoint` | **125 Hz** |
| ↓ | | `vehicle_local_position_setpoint` | 125 Hz |
| **姿态环** | **`mc_att_control`** | `vehicle_rates_setpoint` | **250 Hz** |
| ↓ | | | |
| **角速率环** | `mc_rate_control` | `vehicle_torque_setpoint` / `vehicle_thrust_setpoint` | **250 Hz** |
| ↓ | | | |
| **混控** | `control_allocator` | `actuator_motors` | **250 Hz** |
| ↓ | | | |
| **执行器** | `gz_bridge-actuators-esc` | 电机 | 250 Hz |

## 3.2 为什么是这个频率比例

| 环 | 频率 | 带宽需求 |
|---|---|---|
| 位置环 | 125 Hz | 管慢动态（飞过去、悬停），不需要快 |
| 姿态环 | 250 Hz | 管中等动态（姿态跟踪） |
| 角速率环 | **250 Hz** | **管最快动态（抗风、抗振）** |

> **规律：内环必须比外环快 2–5 倍。** 这里 250 / 125 = 2，符合。
>
> **为什么？** 外环的输出是内环的输入。内环不够快，外环的指令还没执行完就被新指令覆盖 —— 控制器会"追不上自己"。
>
> **这是设计控制律时必须遵守的约束。** 想改内环频率？先确认外环跟得上。

### ⚠️ 一个必须记住的前提

**250 Hz 是 `IMU_INTEG_RATE` 参数的默认值，SITL 和真机可能不同。**

```
pxh> param show IMU_INTEG_RATE
```

> **控制器的所有增益都是在这个频率下调好的。** 换了频率不重新整定，轻则性能下降，重则直接振荡。
> **这是新手换平台时最常见的翻车原因。**

## 3.3 work_queue 的分组不是随意的

| 队列 | 装了什么 | 为什么单独分组 |
|---|---|---|
| **`wq:rate_ctrl`** | `mc_rate_control`、`control_allocator`、`vehicle_angular_velocity` | **最内环 + 混控**。保命的环路，被阻塞 = 直接失控 |
| **`wq:INS0`** | `ekf2`、`vehicle_imu` | **状态估计**。估计器滞后，控制器就拿到过期数据 |
| `wq:nav_and_controllers` | `mc_pos_control`、`mc_att_control`、`sensors` | 外环，可以容忍稍大抖动 |
| `wq:hp_default` | 电池、GPS 仿真、`tone_alarm` | 杂项，慢一点无所谓 |
| `wq:lp_default` | `gyro_calibration`、`load_mon`、`parameters` | 最低优先级 |

> **设计逻辑：越靠近执行器的环，优先级越高、越不能被阻塞。**
> 这也解释了为什么 `mc_rate_control` 不和 `mc_att_control` 放一起 —— 虽然相邻，但内环要独立保证时序。

### 实时性体检方法

看 `work_queue status` 里**括号中的期望值**：

```
|__ 2) gz_bridge         83.3 Hz    12003 us
|__ 5) gz_bridge-actuators-servo   3.3 Hz  299776 us (300000 us)
                                              ↑ 实际     ↑ 期望
```

**实际值接近期望值 = 健康。** 实际间隔**明显大于**期望值，说明任务在排队等待 —— **这是实时性退化的第一信号**。

> **注意噪音**：`tone_alarm` 显示 `58745780 us` 是异常值，但它 `0.0 Hz` —— 说明这任务几乎从不运行，那个数字是"上次运行到现在的间隔"。**不是 bug，别被骗。**

## 3.4 意外收获：PX4 自带振动频谱分析

```
|__ 2) gyro_fft    62.5 Hz    16000 us
```

**`gyro_fft` 模块在对陀螺仪数据做实时 FFT**，输出到 `sensor_gyro_fft` 话题。**不需要自己写 FFT 脚本。**

| 用途 | 怎么看 |
|---|---|
| **检测机架共振** | 频谱上的尖峰频率对应机架/桨的共振点 |
| **配置陷波滤波器** | 找到共振频率后，用 `IMU_GYRO_NF0_FRQ` 滤掉 |
| **判断振荡来源** | 振荡频率 ≈ 共振频率 → 机械问题；≈ 控制带宽 → 参数问题 |

## 3.5 其他关键基线数据

| 项目 | 值 |
|---|---|
| 话题总数 | 110 |
| 总发布率 | 6446 次/秒 |
| 数据速率 | **524.3 kB/s** |
| `vehicle_attitude` 订阅者 | 15 |
| `vehicle_local_position` 订阅者 | **40** |
| 悬停归一化推力 | **≈ 0.77**（`thrust_body[2] = -0.7711`） |

> **悬停油门 0.77 会天天用到** —— 任何改变推力的算法（比如变载重自适应），最终都是在动这个数。

## 3.6 数据格式知识点

从 `vehicle_attitude_setpoint` 的 dump 里学到：

```
thrust_body[0]  范围=[0.0000,  0.0000]     ← 机体系 x
thrust_body[1]  范围=[0.0000,  0.0000]     ← 机体系 y
thrust_body[2]  范围=[-0.7711, -0.0010]    ← 机体系 z
q_d[0]          范围=[0.6968, 1.0000]      ← 四元数 w
yaw_body        范围=[-0.0000, 1.5997]     ← 欧拉角（弧度）
fw_control_yaw_wheel  范围=[0.0000, 0.0000]  ← 固定翼专用，恒 0
```

| 知识点 | 说明 |
|---|---|
| **姿态与推力是两条独立通路** | 多旋翼推力方向由姿态决定，但控制器分别生成"朝向"和"大小" |
| **`thrust_body` 是三维向量** | x/y 恒 0（推力只沿机体 z），z 为负 → 机体系是 **FRD**（z 指向机腹） |
| **`q_d` 和欧拉角并存** | 同一姿态两种表示。四元数用于内部计算（无奇异点），欧拉角用于人看。**记住 `yaw_body` 单位是弧度**，1.5997 rad = 91.66° |
| **`fw_` 前缀 = 固定翼专用** | 多旋翼永远不碰。**看到范围 `[0, 0]` 的字段直接跳过** |

> **读数据的一个技巧**：PX4 的 msg 是**多机型共用**的，很多字段对你这台多旋翼没有意义。看范围就能筛掉。

---

# 四、排故方法论沉淀

**这一节和飞控无关，但比任何具体命令都值钱。**

## 4.1 判断"代码有没有被改过"：用 git，不用文件时间戳

`hello_start.cpp` 的时间戳和其他文件差了 5 小时，看起来像被改过。实际上：

```bash
$ git diff --stat HEAD -- src/examples/hello/
（空）
```

**空输出 = 文件内容没有任何改动。** 时间戳差异是切换分支时 git 重写文件造成的。

> **判断代码有没有被改动，永远用 `git status` / `git diff`，不要用文件时间戳。**
> 时间戳会被 checkout、编译、编辑器、甚至系统时钟影响，**它不可信**。

## 4.2 "先观测，后动手" —— 恢复铁律

```
改坏了 → ① 先 git status 看现状
       → ② 再 git diff 看具体内容
       → ③ 最后精确还原（精确到文件路径）
        └────── 三步顺序不能颠倒 ──────┘
```

### ⚠️ 三条绝对不要敲的命令

| 危险命令 | 后果 |
|---|---|
| `git clean -fd` | 删掉**所有**未跟踪文件 |
| `git checkout .` | 丢掉**全部**已跟踪文件的改动，范围远超你想要的 |
| `git reset --hard` | 更狠，连暂存区一起清 |

> **恢复铁律：精确到文件路径，一次还原一个。永远不用通配符做批量还原** —— 这是新手把小事搞成大事的头号原因。

## 4.3 建立基线快照

```bash
mkdir -p ~/PX4-notes/baseline
cd ~/PX4-Autopilot
git log -1 --oneline > ~/PX4-notes/baseline/baseline.txt
git status --short >> ~/PX4-notes/baseline/baseline.txt
```

以后 `git status` 出现**这份快照里没有的条目**，那就是你自己造成的，责任清晰。

> **排故的本质就是"找出变化量"。** 基线不清晰，排故就是无底洞。
> 同理，调参前先 `param show` 存一份参数基线 —— 等你调乱了再想找"原来是什么样"，就晚了。

## 4.4 用**独立数据源**交叉验证结论

从日志里发现 Yaw 在 5s 处从 0 跳到 90°。有两种可能：

| 假设 | 验证方法 | 结果 |
|---|---|---|
| 飞机真的转了 90°？ | 看**真实陀螺仪**数据 `vehicle_angular_velocity` 的 yaw rate | 该时刻为 **0** ❌ 排除 |
| EKF 估计器复位？ | 姿态跳变但陀螺仪无响应 | ✅ **成立** |

**一个现象、两条独立数据、互相印证。**

> 反面教材：第一版脚本用 `np.diff(yaw)/dt` 从四元数**差分**估算角速率，在跳变点算出了 >20000 deg/s 的假尖峰。
> **永远不要用姿态差分反推角速率** —— 它会放大噪声、在跳变点产生虚假尖峰。飞控里本来就有真实测得的角速率。

## 4.5 有现象再找解释，比先啃代码有效

学习路径的排序建议：

```
先让飞机"动起来"看到动态响应  →  再回去读代码
```

**带着"我看到的这个现象是怎么产生的"去读代码，比漫无目的地啃源码快得多。**

## 4.6 区分 IDE 噪音和真问题

VS Code 报告 14 个问题，全部是蓝色 ⓘ + `cSpell`（拼写检查）—— **零个真问题**。

| 来源 | 是什么 | 要不要管 |
|---|---|---|
| **`cSpell`** | 拼写检查 | ❌ **基本全是误报**（`pyulog`/`arctan`/`figsize` 当然不在英文词典里） |
| `Pylance` / `python` | Python 语法、类型 | ✅ **要管** |
| `C/C++` | C++ 编译、语法 | ✅ **要管** |
| `markdownlint` | Markdown 风格 | ❌ 多半是个人偏好 |

**图标颜色**：蓝色 ⓘ 信息 < 黄色 ⚠ 警告 < 红色 ⊗ 错误。

> **排故心态：IDE 报 100 个问题 ≠ 代码有 100 个毛病。**
> **先按来源过滤，再按颜色排序，最后才看内容。** 这个顺序能省掉大量无效焦虑。
> **看 PX4 编译输出也是同一个道理**（见坑 2）。

## 4.7 工程目录组织

**仓库只放要提交给 PX4 的代码；个人工具和笔记放仓库外。**

| 放 `~/PX4-Autopilot/` 里 | 放 `~/PX4-notes/` |
|---|---|
| 污染 `git status` | 完全隔离 |
| 容易误提交 | 不会进版本控制 |
| 切分支/还原时可能被卷进去 | 不受影响 |

**这样任何时候 `git status` 看到的都是"我真的改了项目文件"，一眼分明。**

---

# 五、当前进度与下一步

## 已完成（Week 1–2）

- [x] 打通"改代码 → 编译 → 进仿真 → 验证"闭环
- [x] 写出并运行自定义模块 `px4_hello`，订阅真实 uORB 数据
- [x] 建立日志分析链路：`.ulg` → pyulog → matplotlib → PNG
- [x] 看懂 PX4 多旋翼完整控制链路与频率分层
- [x] 掌握运行时调试命令与跨平台差异

## 未完成 / 已知局限

- [ ] **动态性能分析**（超调量、响应时间）—— 需要一次**阶跃激励**实验（用 MAVSDK 发姿态/位置指令）
- [ ] **频谱分析**练手 —— `gyro_fft` 已内置，但还没实际用过
- [ ] 悬停时的 ±1° 姿态波动，是**噪声**还是**固定频率振荡**？待频谱判定
- [ ] "最低驱动认知"清单（传感器链路 / 执行器链路 / 从日志判断硬件问题 vs 算法问题）

## 下一步路线

```
Week 3–4   精读 mc_att_control / mc_pos_control，画出完整信号流图
Week 5–8   第一次自己改控制律（旁路 rate 环）
Week 9–12  按产品方向分支
```

**建议的顺序**：

1. **先做激励实验**（补上动态性能分析）
2. **再回来读代码** —— 有现象再找解释

---

## 一句话总结

> **二次开发的第一步不是改控制律，是建立"可观测的闭环"。**
>
> 没有观测，改任何参数都是盲调；没有闭环，学再多都不算数。
> 而这两样东西的地基是：**知道代码怎么进固件、知道数据怎么流、知道用什么命令看** ——
> **以及一条贯穿始终的纪律：先观测，后动手；要对照，看数据。**

---

## 关联文档

- [`PX4-SITL-setup-log.md`](./PX4-SITL-setup-log.md) —— 环境搭建，13 个坑
- `plot_attitude.py` —— 从 `.ulg` 画姿态/角速率曲线的脚本

## 许可

随意取用、修改、转发。
