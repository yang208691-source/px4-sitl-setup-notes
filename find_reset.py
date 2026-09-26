#!/usr/bin/env python3
import sys
import numpy as np
from pyulog import ULog

ulg = ULog(sys.argv[1])
d = {x.name: x for x in ulg.data_list}
att = d['vehicle_attitude'].data
ts = np.asarray(att['timestamp'], dtype=np.int64)

print("vehicle_attitude 的字段:")
for k in sorted(att.keys()):
    print("   ", k)

if 'quat_reset_counter' in att:
    qrc = np.asarray(att['quat_reset_counter'], dtype=np.int64)
    changes = np.where(np.diff(qrc) != 0)[0]
    print(f"\nquat_reset_counter 变化 {len(changes)} 次:")
    for i in changes:
        print(f"  ts {ts[i]} -> {ts[i+1]}   counter {qrc[i]} -> {qrc[i+1]}")
