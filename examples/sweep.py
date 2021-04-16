"""Example using the m1k library to perform voltage sweeps on all connected devices."""

import pathlib
import sys

import matplotlib.pyplot as plt

sys.path.insert(1, str(pathlib.Path.cwd().parent))
import m1k.m1k as m1k


with m1k.smu() as smu:
    # connect all available devices
    smu.connect()

    # configure global settings
    smu.nplc = 1
    smu.settling_delay = 0.005

    # configure channel specific settings for all outputs
    smu.configure_channel_settings(auto_off=False, four_wire=True, v_range=5)


# plot the data
fig, ax = plt.subplots()
for ch, ch_data in data.items():
    voltages = [v for v, i, t, s in ch_data]
    currents = [i * 1000 for v, i, t, s in ch_data]
    ax.scatter(voltages, currents, label=f"channel {ch}")
ax.axhline(0, lw=0.5, c="black")
ax.tick_params(direction="in", top=True, right=True, labelsize="large")
ax.set_xlabel("Applied bias (V)", fontsize="large")
ax.set_ylabel("Current (mA)", fontsize="large")
ax.legend()

plt.show()
