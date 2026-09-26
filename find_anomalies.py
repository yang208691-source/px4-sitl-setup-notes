#!/usr/bin/env python3
import sys
import numpy as np
from pyulog import ULog
topic = sys.argv[2] if len(sys.argv) > 2 else 'vehicle_attitude'
ulg = ULog(sys.argv[1])
d = {x.name: x for x in ulg.data_list}
ts = np.asarray(d[topic].data['timestamp'], dtype=np.int64)
dt = np.diff(ts)
idx = np.where(dt != 4000)[0]
print(f"总间隔: {len(dt)}    异常间隔: {len(idx)}")
print()
for i in idx:
    where = "开头" if i < 100 else ("结尾" if i > len(dt) - 100 else "★中间")
    print(f"  第 {i:7d} 个（{where}）: ts {ts[i]} -> {ts[i+1]}   dt={dt[i]} us")


    