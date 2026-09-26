#!/usr/bin/env python3
"""分析话题的发布周期分布 —— 看平均值掩盖了什么"""
import sys
import numpy as np
from pyulog import ULog
topic = sys.argv[2] if len(sys.argv) > 2 else 'vehicle_attitude'
ulg = ULog(sys.argv[1])
d = {x.name: x for x in ulg.data_list}
ts = np.asarray(d[topic].data['timestamp'], dtype=np.int64)
dt = np.diff(ts)
print(f"话题: {topic}")
print(f"样本数: {len(ts)}")
print(f"平均周期: {dt.mean():.1f} us  →  平均频率 {1e6/dt.mean():.2f} Hz")
print(f"最小 / 最大: {dt.min()} / {dt.max()} us")
print(f"标准差: {dt.std():.1f} us")
print()
print("周期分布（占比 > 0.1% 的）:")
vals, counts = np.unique(dt, return_counts=True)
for v, c in zip(vals, counts):
    pct = 100 * c / len(dt)
    if pct > 0.1:
        bar = '#' * int(pct / 2)
        print(f"  {v:8d} us : {c:7d} 次 ({pct:5.2f}%) {bar}")

        