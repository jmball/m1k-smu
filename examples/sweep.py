"""Example using the m1k library to perform a voltage sweep."""

import matplotlib.pyplot as plt

from . import m1k


with m1k.smu() as smu:
    # connect all available devices
    smu.connect()

    # configure all outputs
    smu.configure_all_channels(
        nplc=0.2, settling_delay=0.005, auto_off=False, four_wire=True, v_range=5
    )

    # configure a sweep for channel 0
    smu.configure_sweep(
        start=0, stop=0.6, points=13, dual=True, source_mode="v", channel=0
    )

    # measure the sweep on channel 0, accouting for nplc and settling delay
    data = smu.measure(channel=0, process=True)

    # disconnect all devices
    smu.disconnect()

# extract processed and raw data for plotting
voltages_p = [v for v, i, t, s in data["processed"]]
currents_p = [i * 1000 for v, i, t, s in data["processed"]]

times_r = [t for v, i, t, s in data["raw"]]
voltages_r = [v for v, i, t, s in data["raw"]]
currents_r = [i * 1000 for v, i, t, s in data["raw"]]

# plot the processed data
fig, ax = plt.subplots()
ax.plot(voltages_p, currents_p)
ax.axhline(0, lw=0.5)
ax.tick_params(direction="in", top=True, right=True, labelsize="large")
ax.set_xlabel("Applied bias (V)", fontsize="large")
ax.set_ylabel("Current (mA)", fontsize="large")

fig.show()

# plot the raw data
fig, ax = plt.subplots()
ax.plot(voltages_p, currents_p)
ax.axhline(0, lw=0.5)
ax.tick_params(direction="in", top=True, right=True, labelsize="large")
ax.set_xlabel("Applied bias (V)", fontsize="large")
ax.set_ylabel("Current (mA)", fontsize="large")

fig.show()
