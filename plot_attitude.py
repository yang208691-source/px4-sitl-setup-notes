#!/usr/bin/env python3
"""从 PX4 .ulg 日志画姿态与角速率曲线 -> 输出 PNG"""
import sys
import numpy as np
from pyulog import ULog
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def to_sec(ts, t0, name=''):
    """uint64 时间戳 -> 秒。显式转 int64，避免无符号回绕。"""
    out = (np.asarray(ts, dtype=np.int64) - np.int64(t0)) / 1e6
    if out.size and (out.min() < -1.0 or out.max() > 1e6):
        print(f"  !! {name} 时间范围异常: [{out.min():.3g}, {out.max():.3g}] s")
    return out


def get_quat(d, base='q'):
    """兼容 pyulog 两种字段命名：'q' 或 'q[0]'..'q[3]'"""
    if base in d:
        return np.asarray(d[base])
    keys = [f'{base}[{i}]' for i in range(4)]
    if all(k in d for k in keys):
        return np.column_stack([d[k] for k in keys])
    raise KeyError(f"找不到 {base}。可用字段: {sorted(d.keys())}")


def quat_to_euler(q):
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    roll = np.arctan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = np.arcsin(np.clip(2 * (w * y - z * x), -1.0, 1.0))
    yaw = np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return np.rad2deg(roll), np.rad2deg(pitch), np.rad2deg(yaw)


def main(path):
    ulg = ULog(path)
    data = {d.name: d for d in ulg.data_list}

    print("=== 日志中的话题 ===")
    for name in sorted(data.keys()):
        print("   ", name)

    att = data['vehicle_attitude']
    t0 = int(att.data['timestamp'][0])          # 统一时间基准
    t = to_sec(att.data['timestamp'], t0, 'vehicle_attitude')
    roll, pitch, yaw = quat_to_euler(get_quat(att.data))

    print(f"\n=== 姿态 ===\n时长 {t[-1]:.1f} s，采样 {len(t)} 点")
    for name, y_ in [('Roll', roll), ('Pitch', pitch), ('Yaw', yaw)]:
        print(f"  {name}: [{y_.min():.2f}, {y_.max():.2f}] deg")

    panels = []
    sp_ok = False

    # --- 姿态指令 ---
    if 'vehicle_attitude_setpoint' in data:
        sp = data['vehicle_attitude_setpoint']
        if all(k in sp.data for k in ('roll_body', 'pitch_body', 'yaw_body')):
            ts = to_sec(sp.data['timestamp'], t0, 'setpoint')
            for y_, key, label in [(roll, 'roll_body', 'Roll [deg]'),
                                   (pitch, 'pitch_body', 'Pitch [deg]'),
                                   (yaw, 'yaw_body', 'Yaw [deg]')]:
                panels.append((t, y_, label, (ts, sp.data[key], 'setpoint')))
            sp_ok = True
        else:
            print(f"  vehicle_attitude_setpoint 字段: {sorted(sp.data.keys())}")

    if not sp_ok:
        for y_, label in [(roll, 'Roll [deg]'), (pitch, 'Pitch [deg]'), (yaw, 'Yaw [deg]')]:
            panels.append((t, y_, label, None))
        print("  未找到姿态指令，只画实际值")

    # --- 真实角速率 ---
    if 'vehicle_angular_velocity' in data:
        av = data['vehicle_angular_velocity']
        tav = to_sec(av.data['timestamp'], t0, 'angular_velocity')
        print(f"  角速率时间范围: [{tav.min():.2f}, {tav.max():.2f}] s, 共 {len(tav)} 点")
        for i, label in enumerate(['Roll rate [deg/s]', 'Pitch rate [deg/s]', 'Yaw rate [deg/s]']):
            panels.append((tav, np.rad2deg(av.data[f'xyz[{i}]']), label, None))
    else:
        print("  !! 无 vehicle_angular_velocity，跳过角速率")

    # --- 画图 ---
    n = len(panels)
    fig, axes = plt.subplots(n, 1, figsize=(14, 2.2 * n), sharex=True, squeeze=False)
    for ax, (tx, y_, label, extra) in zip(axes[:, 0], panels):
        ax.plot(tx, y_, lw=0.8, label='actual')
        if extra is not None:
            ax.plot(extra[0], extra[1], lw=1.2, color='C1', alpha=0.8, label=extra[2])
            ax.legend(loc='upper right', fontsize=8)
        ax.set_ylabel(label, fontsize=9)
        ax.grid(True, alpha=0.3)
    axes[-1, 0].set_xlabel('Time [s]')

    fig.suptitle(f'Attitude - {path.split("/")[-1]}')
    fig.tight_layout()
    fig.savefig('attitude.png', dpi=120)
    print("\n已保存: attitude.png")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'log.ulg')
