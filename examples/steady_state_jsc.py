"""Example using the m1k library to perform Jsc tracking on all channels."""

import pathlib
import time
import sys

import matplotlib.pyplot as plt

sys.path.insert(1, str(pathlib.Path.cwd().parent.joinpath("src")))
import m1k.m1k as m1k


def steady_state_jsc(smu, delay=0.5, t_end=30):
    """Run Jsc tracking scans on all channels.

    Parameters
    ----------
    delay : float
        Time between measurements.
    t_end : float
        Total measurement time in seconds.

    Returns
    -------
    data : list of tuples
        Steady-state Voc data.
    """
    # init container
    num_channels = smu.num_channels
    jsc_data = {}
    for ch in range(num_channels):
        jsc_data[ch] = []

    # run steady-state jsc
    t_start = time.time()
    while time.time() - t_start < t_end:
        point_data = smu.measure(measurement="dc")
        for ch, ch_data in point_data.items():
            jsc_data[ch].extend(ch_data)

        time.sleep(delay)

    return jsc_data


with m1k.smu() as smu:
    # connect all available devices
    smu.connect()

    # configure global settings
    smu.nplc = 1
    smu.settling_delay = 0.005

    # configure channel specific settings for all outputs
    smu.configure_channel_settings(four_wire=False, v_range=5)

    print("\nRunning steady-state Jsc...")
    smu.enable_output(True)

    # enable outputs for short circuit
    smu.configure_dc(0, source_mode="v")

    # run mppt
    jsc_data = steady_state_jsc(smu, delay=0.5, t_end=15)

    # disable output manually because auto-off is false
    smu.enable_output(False)

# plot the processed data
fig, ax = plt.subplots()

max_jscs = []
for ch, ch_data in jsc_data.items():
    currents = []
    times = []
    t0 = ch_data[0][2]
    for v, i, t, s in ch_data:
        currents.append(abs(i) * 1000)
        times.append(t - t0)
    ax.scatter(times, currents, label=f"channel {ch}")
    max_jscs.append(max(currents))

ax.tick_params(direction="in", top=True, right=True, labelsize="large")
ax.set_xlabel("Time (s)", fontsize="large")
ax.set_ylabel("|Jsc| (mA)", fontsize="large")
ax.set_ylim((0, max(max_jscs) * 1.1))
ax.legend()

fig.tight_layout()

plt.show()
