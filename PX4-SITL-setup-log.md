# PX4 SITL 开发环境搭建实录：从零到仿真起飞，我踩过的 13 个坑

> **日期**：2026-09-19
> **环境**：Windows 11 + WSL2 Ubuntu 24.04 + Gazebo Harmonic 8.15.0 + PX4 v1.15.4
> **结果**：从零到 SITL 仿真起飞成功
> **性质**：本文档记录踩过的 13 个坑、根因、解法，以及一套可复用的排故方法

## 文档定位（别搞混）

工作目录里有一整套 PX4 文档，三份分工不同：

- **`PX4环境配置指导.md`** —— **计划 / 官方依据**。基于 docs.px4.io 逐条核对写成的安装指导。本文的修正已回填进那份文档（见其附录 B）。
- **本文（`PX4-SITL-setup-log.md`）** —— **实战排故记录**。实际走完流程后，哪些地方和计划不一样、踩了什么坑、怎么定位的。
- **`fix-wsl-nat.ps1`** —— WSL NAT 修复脚本（2026-09-11），针对"无法配置网络"那类 VirtioProxy 回退。

> **先读哪份？**
> - 要**装环境** → 先读 `PX4环境配置指导.md`（已含实测修正）
> - **卡住了** → 在本文按现象检索关键词
> - 看到 `VirtioProxy` 回退 → 先分清是**代理注入失败**（本文坑 2）还是**NAT 配置失败**（`fix-wsl-nat.ps1`），两者排查方向完全不同

## 写给谁看

如果你正在 **Windows + WSL2** 里搭 PX4 开发环境，并且遇到下面任意一条，这篇就是给你写的：

- `git clone` 子模块被墙、`curl 56 GnuTLS recv error`
- WSL 里 `127.0.0.1:7897` 连不上，Clash 开了没效果
- 每次启动 WSL 都提示 `检测到 localhost 代理配置，但未镜像到 WSL`
- Gazebo 装完了但 `make px4_sitl gz_x500` 还报 `dependencies not found`
- **SITL 跑起来了，但无人机在 Gazebo 里一动都不动**
- QGC 显示 `Takeoff detected`，高度却一直是 0.0 m

**这里的每一个坑我都实际踩过，都给出了根因和可复制的解法，不是"网上抄来的偏方"。**

最后两节（**排故方法论**、**如何写一份能被上游接受的 bug report**）是本文最想传递的东西 —— **它们和飞控无关，但比任何具体命令都值钱。**

---

## 一、最终环境画像（速查表）

**重装或排故时，先对照这张表。**

### 网络与代理

| 项目 | 值 | 备注 |
|---|---|---|
| `.wslconfig` 网络模式 | **`networkingMode=nat`** | `mirrored` 在本机静默失效，**永远不要改回去** |
| `wslinfo --networking-mode` | 报 `virtioproxy` | 这是 `nat` 的实现名，**别看名字，看行为** |
| **代理地址** | **`http://127.0.0.1:7897`** | 绝不要用 `ip route` 的网关 IP |
| `ip route` 的网关 | `192.168.88.1` = **手机**，不是 Windows | 用它连代理必然失败 |
| WSL 接口 | `enP16346p0s0` / `enP43673p0s0`（名字会变） | IP 与 Windows USB 网卡相同 |
| TUN 模式 | **关闭** | 不需要，开着反而添乱 |
| 出口 | 手机 USB 共享（RNDIS，标称 10 Mbps） | 长下载容易掉线 |

### `.wslconfig` 完整内容

```ini
[wsl2]
processors=6
memory=10GB
swap=8GB
defaultVhdSize=100GB

networkingMode=nat
dnsTunneling=true
autoProxy=false
firewall=true

[experimental]
hostAddressLoopback=true
```

> ⚠️ **容量值必须带单位**。裸数字按**字节**解析 —— `memory=12288` 会被当成 12 KB（详见坑 3）。

### 代理配置的三处落地

```bash
# ① ~/.bashrc —— 环境变量（探测端口，探不到就不设）
if timeout 1 bash -c "</dev/tcp/127.0.0.1/7897" 2>/dev/null; then
    export http_proxy="http://127.0.0.1:7897"
    export https_proxy="http://127.0.0.1:7897"
    export no_proxy="localhost,127.0.0.1,::1"
fi

# ② git —— 配死，不依赖环境变量
git config --global http.proxy  http://127.0.0.1:7897
git config --global https.proxy http://127.0.0.1:7897
git config --global http.version HTTP/1.1

# ③ apt —— 只给 OSRF 走代理（/etc/apt/apt.conf.d/99px4-proxy）
Acquire::http::Proxy::packages.osrfoundation.org "http://127.0.0.1:7897";
Acquire::https::Proxy::packages.osrfoundation.org "http://127.0.0.1:7897";
Acquire::Retries "5";
```

### 软件版本

| 组件 | 版本 | 位置/命令 |
|---|---|---|
| WSL | 2.7.13.0 | `wsl --version` |
| Ubuntu | 24.04 | — |
| PX4 | **v1.15.4**（稳定版） | `~/PX4-Autopilot` |
| Gazebo | **Harmonic 8.15.0** | `gz sim --version` |
| gz-sim8 | 8.15.0-1~noble | OSRF 源 |
| 编译产物 | `build/px4_sitl_default/bin/px4`（56 MB） | — |

### 日常启动

```bash
cd ~/PX4-Autopilot
HEADLESS=1 make px4_sitl gz_x500      # 无界面（推荐）
make px4_sitl gz_x500                  # 带 Gazebo 界面
```

---

## 二、踩坑全记录

### 坑 1｜WSL 里 `127.0.0.1:7897` 连不上

**现象**
```
curl: (7) Failed to connect to 127.0.0.1 port 7897 after 0 ms
```
`0 ms` = 立即被拒（不是超时）。

**根因**
`.wslconfig` 是 `networkingMode=nat` + `autoProxy=true` —— **最差的组合**。NAT 模式下 WSL 有独立网络命名空间，`127.0.0.1` 指向 WSL 自己；而 `autoProxy` 照样把 Windows 的 localhost 代理注入进来，注入的是个死地址。

`0 ms` 拒绝的原因：包发到 WSL 自己的 loopback，没人监听 7897。

**判读要点**

| 报错 | 含义 |
|---|---|
| `after 0 ms` + `Couldn't connect` | 立即拒绝 = 对端没监听 / 无路由 |
| `after 8000 ms` + `timed out` | 包发出去了没人应答 = 防火墙丢包 |
| `Could not resolve host` | DNS 问题 |

**解法**：见坑 2。

---

### 坑 2｜`mirrored` 模式静默失效

**现象**
`ip -brief addr` **只有 `lo`**，无默认路由，`/etc/resolv.conf` 不生成，DNS 解析失败。等了 2 分钟仍然如此。

**排查结果**：基础服务全部健康 —— `hns` Running、`WslService` Running、Windows 防火墙三个 profile 都 Enabled、Hyper-V 防火墙 VM 设置 `Enabled=True`。**mirrored 要求的硬性前提一个不缺，但它就是不给接口。** dmesg 里连一条网络接口创建记录都没有。

**根因**：mirrored 模式要镜像 Windows 的**每一块网卡**，本机有 Clash 的 wintun 虚拟网卡 / VPN 组件 / 手机 RNDIS，镜像过程静默失败。

### 那条"神秘提示"的真相

如果你的 WSL 每次启动都打印这句话：

```
wsl: 检测到 localhost 代理配置，但未镜像到 WSL (networkingMode Nat)，
     因此回退到 networkingMode VirtioProxy。
```

**它不是错误，但它是"你的 WSL 里代理用不了"的准确预告。**

翻译成大白话：

| 原文 | 含义 |
|---|---|
| 检测到 localhost 代理配置 | Windows 注册表里设了 `ProxyServer=127.0.0.1:xxxx`（Clash 开的系统代理） |
| 但未镜像到 WSL (networkingMode Nat) | NAT 模式下 WSL 有独立网络命名空间，`127.0.0.1` 指向它自己 |
| 因此回退到 networkingMode VirtioProxy | WSL 换用了内部实现 —— **这就是 `wslinfo --networking-mode` 报 `virtioproxy` 的原因** |

**两个直接推论：**

1. **`wslinfo --networking-mode` 报 `virtioproxy` 是正常的** —— 它是 NAT 模式在"检测到 localhost 代理"时的内部回退实现名，不代表配置错了。
2. **这条提示出现时，`autoProxy` 注入的 `127.0.0.1:7897` 一定是死的** —— 因为 NAT 下那个地址是 WSL 自己。

**解法**：

```ini
# .wslconfig
networkingMode=nat
autoProxy=false          ; ← 关键：别让 WSL 注入连不上的地址
```

然后**手动**设代理。用 `nat` 时 `wslinfo` 仍报 `virtioproxy`，但**行为上提供 loopback 共享**（`127.0.0.1` 直通 Windows），所以代理写 `127.0.0.1:7897`。

> **关键教训**：`wslinfo --networking-mode` 的名字**不可信，要看行为**。

**判断模式的行为判据（5 条，30 秒出结论）**

| 判据 | NAT 模式 | mirrored 模式 |
|---|---|---|
| 接口名 | `eth0` | Windows 网卡名 |
| 接口 IP | `172.x.x.x` | **与 Windows 完全相同** |
| 默认网关 | `172.x.x.1` | 物理网关 |
| `127.0.0.1:7897` | ❌ 不通 | ✅ 通 |
| `loopback0` 接口 | 不存在 | 存在 |

---

### 坑 3｜`.wslconfig` 的 `memory` 单位（用户发现）

**现象**：`memory=8589934592` 和 `memory=12288`，哪个对？

**实测推导**
```
Windows 物理内存:  16,371,568,640 B = 15.25 GiB
WSL 内 free -m:    Mem 7942 MiB,  Swap 8192 MiB

8589934592 / 1024 / 1024 = 8192 MiB  ← 和实测 Swap 完全一致
```
WSL 的 swap 默认是内存的 25%。若 `8589934592` 按 MB 解析，swap 会被回退成默认值 ≈1950 MiB，**不可能是 8192**。

**结论：裸数字按字节解析。**

```
memory=12288  →  12288 字节 = 12 KiB  →  非法值，静默失效或起不来
```

**解法：容量值一律带单位。**
```ini
memory=10GB
swap=8GB
defaultVhdSize=100GB
```

> **教训**：数值配置先确认**单位和量纲**，再看数值。PX4 参数同理（`MPC_XY_VEL_MAX` 是 m/s，有人按 cm/s 填，参数系统照收不误）。

---

### 坑 4｜镜像里的 `17 not upgraded`

**现象**：`apt` 输出 `0 upgraded, 0 newly installed, 0 to remove and 17 not upgraded.`

**根因**：脚本执行的是 `apt-get install <指定包>`，**不是** `apt upgrade`。apt 在总结行里顺带汇报"系统里还有 17 个包有更新，但你没让我动它们"。**纯信息性提示。**

**排除分阶段更新的方法**：
```bash
apt-get -s upgrade | tail -3     # 模拟升级，看它是否计划升级这些包
```
计划里有 → 不是 phased updates，只是没人让它升。

**结论**：不用管。与 PX4 环境无关（那 17 个是 krb5 / perl / netplan / polkit / sqlite）。

---

### 坑 5｜子模块克隆 `curl 56 GnuTLS recv error (-9)`

**现象**
```
error: RPC failed; curl 56 GnuTLS recv error (-9): Error decoding the received TLS packet.
error: 545 bytes of body are still expected
fatal: early EOF
```

**判读**：`545 bytes short` = **数据几乎全下来了，收尾时被切断**。性质是**代理链路质量 / 节点不稳**，不是配置错误。

**解法（三件套）**
```bash
git config --global http.version HTTP/1.1     # ← 最有效
# 并发降到 1（手机共享 + 代理，同时开 4 条连接会互相挤爆）
git submodule update --init --recursive --depth 1 --jobs 1
# 换 Clash 节点：避开"中转/隧道"类，它们对长连接不友好
```

**多轮重试模板**
```bash
cd ~/PX4-Autopilot
for round in $(seq 1 20); do
    missing=$(git submodule status --recursive | grep -c '^-')
    echo "===== 第 $round 轮 | 剩余: $missing ====="
    [ "$missing" -eq 0 ] && { echo ">>> 全部完成"; break; }
    git submodule update --init --recursive --depth 1 --jobs 1 || true
    sleep 3
done
```

**顺带纠正一个流传很广的偏方**：`git config --global http.postBuffer 524288000` 对 clone/fetch **基本无效** —— 它控制的是 push 的 POST 请求体大小。

---

### 坑 6｜`git submodule update` 无输出 = 成功

**现象**：敲完命令，**什么都没打印**，直接回到提示符。

**含义**：`git submodule update` 是**幂等**的，无事可做时**沉默退出**。这是设计如此。

| 输出 | 含义 |
|---|---|
| **什么都没打印** | ✅ 全部已就绪 |
| `Cloning into '...'` | 正在拉取 |
| `Submodule path '...': checked out` | 切换提交 |
| `error:` / `fatal:` | ❌ 失败 |

**唯一可信的判据（以后反复用到）**
```bash
git submodule status --recursive | grep '^-'    # 空 = 齐了
```

**本次结果**：42 个子模块，0 个未初始化，0 个版本不符。

---

### 坑 7｜OSRF 源「80 通、443 断」

**现象**
```
apt 下载 854 MB   → established 到 52.52.171.73:80   ✅
sudo wget https:// → SYN-SENT 到 52.52.171.73:443    ❌ 挂死
```

**根因**：同一台机器，**80 端口（HTTP）畅通，443 端口（HTTPS）被丢包** —— 典型的针对 HTTPS/SNI 的干扰。

**解法**：给走 HTTPS 的 `wget` 单独配代理。
```bash
sudo tee -a /etc/wgetrc > /dev/null <<'EOF'

use_proxy = on
http_proxy = http://127.0.0.1:7897
https_proxy = http://127.0.0.1:7897
no_proxy = localhost,127.0.0.1
EOF
```

**注意**：`sudo` 默认清空环境变量，所以 `~/.bashrc` 里的 `http_proxy` **传不进 `sudo wget`**。`/etc/wgetrc` 是全局配置，`sudo` 也会读 —— 这就绕开了这个问题。

---

### 坑 8｜CMake 缓存住了「未找到」（**最经典**）

**现象**：Gazebo 明明装好了（`gz sim --version` → 8.15.0，107 个 `libgz-*` 包，`/usr/lib/x86_64-linux-gnu/cmake/gz-sim8/` 配置文件齐全），但 `make px4_sitl gz_x500` 仍然报：
```
-- Could NOT find gz-sim (missing: gz-sim_DIR)
ERROR: Gazebo simulation dependencies not found!
```

**根因**：`build/px4_sitl_default/CMakeCache.txt` 里锁着第一次配置时的结果：
```
gz-sim_DIR:PATH=gz-sim_DIR-NOTFOUND
gz-transport_DIR:PATH=gz-transport_DIR-NOTFOUND
gz-sensors_DIR:PATH=gz-sensors_DIR-NOTFOUND
gz-plugin_DIR:PATH=gz-plugin_DIR-NOTFOUND
```
CMake 把"没找到"**缓存**了，重新构建时不会自动重新搜索。

**解法**
```bash
rm -rf build/px4_sitl_default
make px4_sitl gz_x500
```

**成功标志**：配置阶段出现 `-- Found gz-sim: ... (version 8.15.0)`，而不是 `-- Could NOT find`。

> **条件反射**：换工具链、换 SDK、装新库之后，**先清 build 目录再编译**。

---

### 坑 9｜`commander arm` 后 10 秒自动上锁

**现象**
```
INFO  [commander] Armed by internal command              ← 解锁成功
INFO  [commander] Disarmed by auto preflight disarming   ← 又锁上了
```

**根因**：PX4 的「起飞前自动上锁」机制（`COM_DISARM_PRFLT`，默认 **10 秒**）。解锁后如果没起飞，自动上锁。

**真实场景还原**：解锁 → 去看 `listener` / `param show`（花了几十秒）→ 回头想让它飞时，已经锁上了 → 以为"解锁失败"。

**解法：直接用 `commander takeoff`** —— 它会自动解锁并起飞到 2.5 m，一条指令走完，不留"解完锁又忘了飞"的空档。

> **这是安全设计，不是 bug。** 真机上误触解锁后，不会一直保持解锁状态等你误碰油门。**真机上标准动作：解锁 → 立刻推油门，中间不停顿。**

---

### 坑 10｜SITL 里不需要（也没法）做磁力计校准

**现象**：QGC 打开罗盘校准向导，要求"连续旋转飞机"，但仿真里转不动载具。

**根因**：QGC 的罗盘校准靠"你转动载具 → 磁力计采集不同姿态数据 → 解算硬磁/软磁偏差"。仿真里载具姿态由物理引擎控制。

**先确认到底需不需要**（别瞎做）：
```
commander arm            # PX4 会直接说拒绝原因
param show CAL_MAG0_ID   # 0 = 未校准，非 0 = 已校准
```
本次实测 `CAL_MAG0_ID = 197388` —— **早就校准好了，根本不用做**。

**如果确实需要，用参数法写入恒等变换**（仿真磁力计理想无干扰）：
```
param set CAL_MAG0_ID <device_id>   # 从 listener sensor_mag 里取
param set CAL_MAG0_ROT 0
param set CAL_MAG0_XSCALE 1.0
param set CAL_MAG0_YSCALE 1.0
param set CAL_MAG0_ZSCALE 1.0
param set CAL_MAG0_XOFF 0.0
param set CAL_MAG0_YOFF 0.0
param set CAL_MAG0_ZOFF 0.0
```

---

### 坑 11｜载具在仿真里完全不动（**核心坑**）

**现象**
```
QGC:  Armed by 内部指令 → Takeoff detected，但高度显示 0.0 m，速度 0.0 m/s
日志: z 范围只有 ±0.13 m 以内（7 次飞行，没有一次超过 13 cm）
```

**排查路径（这是本文档最有价值的部分）**

```
现象：飞机不动
  ↓
① 查飞控状态  → armed？电机有输出吗？
  ↓ 全部正常
② 查 Gazebo 真实状态 → groundtruth 动没动？
  ↓ 完全静止（378 秒，18619 个采样，位置姿态全恒定）
③ 查数据流方向 → 传感器通吗？执行器通吗？
  ↓ 传感器通、执行器断
④ 读源码      → 发布条件是什么？为什么没进？
  ↓
⑤ 定位到具体环节
```

**关键测量结果**

| 检查项 | 结果 |
|---|---|
| `actuator_armed.armed` | `1`（已解锁） |
| `actuator_motors` 末尾采样 | `control[0]=0.62, control[1]=0.35`（持续输出） |
| `SIM_GZ_EC_FUNC1~4` | `101/102/103/104`（**配置正确**） |
| `gz topic -i` | publisher + 4 个 subscriber 均已注册 |
| **`gz topic -e` 抓 10 秒** | **0 字节** |
| 同条件 IMU topic 抓 8 秒 | **1,852,594 字节**（对照组） |
| `vehicle_local_position_groundtruth` | x/y/z/四元数 **378 秒全部恒定** |

**结论**：电机指令没有到达 Gazebo。

**解法**：`git checkout v1.15.4` → 同一测试 **119,560 字节** ✅

**根因判断（60% 可信度）**：PX4 `main` 分支的开发版（`v1.18.0-beta1-700`）与 Gazebo 8.15.0 之间存在接口问题，**失败方式是完全静默的**。

> ⚠️ **可信度说明**：换版本时同时改变了 5 个变量（PX4 代码 / gz 模型定义 / build 缓存 / rootfs 参数 / world 文件），**没有做变量隔离**。所以只能说"换版本修复了它"，不能断定是哪一个原因。详见第五节。

---

### 坑 12｜排查中的方法论错误（值得单列）

**本次诊断中，连续 4 次得出错误结论：**

| 错误结论 | 实际 | 错因 |
|---|---|---|
| "磁力计未校准导致无法解锁" | 解锁一直是好的 | 没看 `commander arm` 的输出就下结论 |
| "`heading_good_for_control` 是根因" | 它不影响解锁 | 只看一个标志位就推断 |
| "`SIM_GZ_EC_FUNC*` 没配置" | 配置完全正确 | 读源码后推测，没实测 |
| "mirrored 接口创建失败"（早期） | 是启动窗口期 | 观察窗口太短 |

**共同模式：在数据不全时，倾向于"给出一个听起来合理的解释"，而不是"承认不知道、再测一步"。**

**铁律**：**先让系统自己说话，再动手。** 任何 `commander arm` / `dmesg` / `apt` 能直接告诉你的答案，都不要靠推断。

---

### 坑 13｜别用 main 分支开发版做开发

**本次最大的时间浪费来源。**

```
PX4_GIT_TAG: v1.18.0-beta1-700-gc4e4ef98e9
```
比 `v1.18.0-beta1` 还多 700 个提交 —— 正在开发中的代码。

**开发版的问题**：
- 和外部依赖（Gazebo）的接口可能对不上
- **失败方式是静默的**，不报错、不打日志
- 网上教程 / 文档对不上
- 你分不清是 bug 还是自己改的

**该换路而不是继续查的信号**：

| 继续查 | 换路 |
|---|---|
| 配置项可疑，能通过参数解决 | 配置全对、代码正常、就是不工作 |
| 有明确的错误信息 | 静默失败，查了 3 层还没头绪 |
| 用的是发布版本 | **用的是 main 分支开发版** |

**"换稳定版"只要 30 分钟，"继续查"可能再花 3 小时还无果。**

---

## 三、排故方法论（通用，可迁移到真机）

### 1. 分层隔离

```
传感器 → 估计器 → 控制器 → 执行器 → 被控对象
```
**一次只切一刀**，切开后看哪边是好的。

### 2. `*_groundtruth` 是上帝视角

PX4 SITL 的 ulog 里有 `vehicle_local_position_groundtruth`、`vehicle_attitude_groundtruth` —— **这是仿真世界里的真相，不受估计器和控制器干扰。**

**有它就能一刀切开"是飞控的问题"还是"是物理世界的问题"。**

### 3. 对照实验

**别只测"怀疑的那条路"，同时测一条"确定应该通的路"。**

本次做法：同时 echo `motor_speed`（怀疑）和 `IMU`（确定通）。
- IMU 有数据 → 证明工具没问题
- motor 没数据 → 证明是链路问题

**没有对照组，你分不清"是故障"还是"我方法不对"。**

### 4. 数字说话

`0 字节` vs `1,852,594 字节` —— **比任何形容词都有力。**

**警惕测量陷阱**：`gz topic -e | head` 走管道时是块缓冲的，小消息可能填不满缓冲区就被 timeout 掐掉。**改用文件重定向 + `wc -c`**：
```bash
timeout 10 gz topic -e -t <topic> > /tmp/out.txt; wc -c < /tmp/out.txt
```

### 5. 读源码把黑盒变白盒

**不要猜"它应该会发"，去读"什么条件下才发"。**

本次找到：
```cpp
// GZMixingInterfaceESC::updateOutputs()
if (active_output_count > 0) { Publish(...); }
return false;                     // ← 否则静默什么都不做
```
**看到 early-return，就知道要往哪个方向查。**

### 6. 推断必须标注可信度

| 层次 | 评分 |
|---|---|
| 直接测量 + 对照组 | 90~99 |
| 从代码反推 | 70~80 |
| 换变量后现象消失 | **60**（没隔离，只是相关） |

**报给上游时，只有 90+ 的部分能写成"结论"，其余必须标注为"推测"。**

---

## 四、命令速查

### SITL 操作

```bash
HEADLESS=1 make px4_sitl gz_x500     # 启动（无界面）
commander takeoff                     # 解锁+起飞到 2.5 m
commander land                        # 降落
commander arm                         # 只解锁（10 秒不起飞会自动上锁）
commander status                      # 看状态
listener vehicle_local_position       # 位置/速度/EKF 有效性
listener vehicle_attitude             # 姿态
listener estimator_status_flags       # EKF 全量标志
param show SIM_GZ*                    # 查参数（支持通配）
param set <NAME> <VALUE>              # 改参数
```

### ulog 日志分析（离线）

日志位置：`build/px4_sitl_default/rootfs/fs/log/<日期>/*.ulg`（v1.18）
或 `build/px4_sitl_default/rootfs/log/<日期>/*.ulg`（v1.15）

```bash
ulog_info  <file.ulg>                # 概览
ulog2csv   <file.ulg>                # 转 CSV
```
或用 Python（`pyulog` 已随 PX4 依赖装好）：
```python
from pyulog import ULog
u = ULog("<file.ulg>")
for d in u.data_list:
    if d.name == "vehicle_local_position":
        z = d.data["z"]; print("z:", z.min(), z.max())
```

### Gazebo topic 诊断

```bash
gz topic -l                          # 列出所有 topic
gz topic -i -t <topic>               # 看谁在发、谁在收 ★关键
gz topic -e -t <topic> > /tmp/o.txt  # 抓数据（必须重定向，别用管道）
gz sim --version                     # 版本
```

### git 子模块

```bash
git submodule status --recursive | grep '^-'    # 唯一可信的完整性判据
git submodule foreach --recursive 'git fetch --unshallow || true'   # 补全历史（费流量）
```

---

## 五、遗留问题（待办）

- [ ] **变量隔离实验**：切回 v1.18 + 干净会话，确认坑 11 能否复现
  - 能复现 → 是真 bug，按第六节整理成 issue
  - 不能复现 → 是陈旧会话问题，根因可信度从 60% 降到 40%
- [ ] 补全 36 个 shallow 子模块的历史（`--unshallow`，约 1~2 GB，等有宽带再做）
- [ ] 考虑切换到更长期的稳定 tag（当前 v1.15.4）
- [ ] 装 QGroundControl（已装）→ 熟悉参数页 / 曲线页 / MAVLink Inspector

---

## 六、如果要报 upstream issue

**当前草稿约 55 分，会被打回。缺失项：**

```
□ 完整 commit hash（git rev-parse HEAD）
□ wsl --version 输出
□ gz sim --versions 完整输出
□ 精确复现命令
□ 完整启动日志（不截断）
□ ulog 附件
□ gz topic -i 完整输出
□ 干净会话的复现结果          ← 最关键
□ 是否在最新 main 上复现过    ← 次关键
```

**三个硬伤：**

1. **结论把推断写成了事实** —— "`updateOutputs()` 未调用 `Publish`" 没有插桩证据。
   而且它**与代码逻辑矛盾**（`SIM_GZ_EC_FUNC1~4` 正确 → `active_output_count=4` → 应该 Publish）。
   应改为："topic 上零消息，断点在 gz_bridge 发布环节，具体环节未定位"。

2. **WSL2 是 PX4 官方不支持的环境** —— 维护者第一反应是 "reproduce on native Ubuntu"。
   绕过：用 Docker，或主动说明并在需要时补验证。

3. **报的是 main 分支的中间 commit** —— 维护者标准回复 "retest on latest main"。
   **必须在最新 main 上仍能复现，才值得报。**

**核心原则**：报告里每一句话都要能回答"**你怎么知道的**"。回答不上来的，降级成"推测"并明确标注。

---

## 七、一句话总结

> **环境搭建的坑 90% 在网络和构建系统，不在飞控本身。**
> **排故的核心不是聪明，是纪律：分层切、要对照、看数据、标注可信度。**
> **以及最难的一条：知道什么时候该停止排查、换条路走。**
