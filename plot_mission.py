#!/usr/bin/env python3
"""Mission flight analysis: trajectory, altitude, speed, attitude, thrust"""
import sys
import numpy as np
from pyulog import ULog
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
def to_sec(ts, t0):
    return (np.asarray(ts, dtype=np.int64) - np.int64(t0)) / 1e6
def quat_to_euler(q):
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    roll = np.arctan2(2*(w*x + y*z), 1 - 2*(x*x + y*y))
    pitch = np.arcsin(np.clip(2*(w*y - z*x), -1.0, 1.0))
    yaw = np.arctan2(2*(w*z + x*y), 1 - 2*(y*y + z*z))
    return np.rad2deg(roll), np.rad2deg(pitch), np.rad2deg(yaw)
def get_quat(d, base='q'):
    if base in d:
        return np.asarray(d[base])
    keys = [f'{base}[{i}]' for i in range(4)]
    if all(k in d for k in keys):
        return np.column_stack([d[k] for k in keys])
    raise KeyError(f"Cannot find {base}. Available: {sorted(d.keys())}")
def main(path):
    ulg = ULog(path)
    d = {x.name: x for x in ulg.data_list}
    print("=== Topics in log ===")
    for n in sorted(d.keys()):
        print("   ", n)
    lp = d['vehicle_local_position']
    t0 = int(lp.data['timestamp'][0])
    t = to_sec(lp.data['timestamp'], t0)
    x, y, z = lp.data['x'], lp.data['y'], lp.data['z']
    vx, vy, vz = lp.data['vx'], lp.data['vy'], lp.data['vz']
    vh = np.sqrt(vx**2 + vy**2)
    print(f"\n=== Flight Summary ({t[-1]:.1f} s) ===")
    print(f"  X (North): [{x.min():8.2f}, {x.max():8.2f}] m")
    print(f"  Y (East) : [{y.min():8.2f}, {y.max():8.2f}] m")
    print(f"  Altitude : [{-z.max():8.2f}, {-z.min():8.2f}] m")
    print(f"  Max horizontal speed: {vh.max():.2f} m/s")
    print("\n=== Position validity ===")
    for f in ['xy_valid', 'z_valid', 'v_xy_valid', 'v_z_valid']:
        if f in lp.data:
            v = np.asarray(lp.data[f])
            print(f"  {f}: {int(v.sum())}/{len(v)} valid")
    fig, axes = plt.subplots(2, 3, figsize=(18, 9))
    # 1 Horizontal trajectory
    ax = axes[0, 0]
    ax.plot(y, x, lw=1.2)
    ax.plot(y[0], x[0], 'go', ms=10, label='start')
    ax.plot(y[-1], x[-1], 'rs', ms=10, label='end')
    ax.set_xlabel('East [m]'); ax.set_ylabel('North [m]')
    ax.set_title('Horizontal Trajectory (top view)')
    ax.grid(True, alpha=0.3); ax.legend(fontsize=8)
    ax.set_aspect('equal', adjustable='datalim')
    # 2 Altitude
    ax = axes[0, 1]
    ax.plot(t, -z, lw=1.2, label='actual')
    if 'vehicle_local_position_setpoint' in d:
        sp = d['vehicle_local_position_setpoint']
        if 'z' in sp.data:
            ax.plot(to_sec(sp.data['timestamp'], t0), -sp.data['z'],
                    lw=1.2, color='C1', alpha=0.8, label='setpoint')
    ax.set_xlabel('Time [s]'); ax.set_ylabel('Altitude [m]')
    ax.set_title('Altitude'); ax.grid(True, alpha=0.3); ax.legend(fontsize=8)
    # 3 Speed
    ax = axes[0, 2]
    ax.plot(t, vh, lw=1.2, label='horizontal')
    ax.plot(t, -vz, lw=1.2, label='vertical (up)')
    ax.set_xlabel('Time [s]'); ax.set_ylabel('Speed [m/s]')
    ax.set_title('Speed'); ax.grid(True, alpha=0.3); ax.legend(fontsize=8)
    # 4 Attitude
    att = d['vehicle_attitude']
    ta = to_sec(att.data['timestamp'], t0)
    roll, pitch, yaw = quat_to_euler(get_quat(att.data))
    ax = axes[1, 0]
    ax.plot(ta, roll, lw=1.0, label='Roll')
    ax.plot(ta, pitch, lw=1.0, label='Pitch')
    ax.set_xlabel('Time [s]'); ax.set_ylabel('Angle [deg]')
    ax.set_title('Attitude'); ax.grid(True, alpha=0.3); ax.legend(fontsize=8)
    print(f"\n  Roll : [{roll.min():.2f}, {roll.max():.2f}] deg")
    print(f"  Pitch: [{pitch.min():.2f}, {pitch.max():.2f}] deg")
    # 5 Heading
    ax = axes[1, 1]
    ax.plot(ta, np.rad2deg(np.unwrap(np.deg2rad(yaw))), lw=1.0, color='C2')
    ax.set_xlabel('Time [s]'); ax.set_ylabel('Yaw [deg]')
    ax.set_title('Heading'); ax.grid(True, alpha=0.3)
    # 6 Thrust
    ax = axes[1, 2]
    if 'vehicle_thrust_setpoint' in d:
        th = d['vehicle_thrust_setpoint']
        thrust = -th.data['xyz[2]']
        ax.plot(to_sec(th.data['timestamp'], t0), thrust, lw=1.2, color='C3')
        print(f"  Thrust: [{thrust.min():.3f}, {thrust.max():.3f}]")
    ax.set_xlabel('Time [s]'); ax.set_ylabel('Thrust (norm)')
    ax.set_title('Thrust Setpoint'); ax.grid(True, alpha=0.3)
    fig.suptitle(f'Mission - {path.split("/")[-1]}')
    fig.tight_layout()
    fig.savefig('mission.png', dpi=120)
    print("\nSaved: mission.png")
if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'log.ulg')
    