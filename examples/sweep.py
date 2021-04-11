"""Example using the m1k library to perform a voltage sweep."""

import pathlib
import sys

sys.path.insert(1, str(pathlib.Path.cwd().parent))

import matplotlib.pyplot as plt

import m1k.m1k as m1k


with m1k.smu() as smu:
    # connect all available devices
    smu.connect()

    # configure all outputs
    smu.configure_all_channels(
        nplc=1, settling_delay=0.005, auto_off=False, four_wire=True, v_range=5
    )

    # configure a sweep
    smu.configure_sweep(start=0, stop=0.6, points=13, dual=True, source_mode="v")

    # measure the sweep
    data = smu.measure("sweep")

    # disable output manually because auto-off is false
    smu.enable_output(False)

# extract data for plotting
voltages_p = [v for v, i, t, s in data[0]]
currents_p = [i * 1000 for v, i, t, s in data[0]]

# plot the processed data
fig, ax = plt.subplots()
ax.scatter(voltages_p, currents_p)
ax.axhline(0, lw=0.5)
ax.tick_params(direction="in", top=True, right=True, labelsize="large")
ax.set_xlabel("Applied bias (V)", fontsize="large")
ax.set_ylabel("Current (mA)", fontsize="large")

fig.show()
