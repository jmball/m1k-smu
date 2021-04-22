"""Example using the m1k library to perform Voc tracking on all channels."""

import time
import pathlib
import sys

import matplotlib.pyplot as plt

sys.path.insert(1, str(pathlib.Path.cwd().parent))
import m1k.m1k as m1k


def steady_state_voc(smu, delay=0.5, t_end=30):
    """Run Voc tracking scans on all channels.

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
    voc_data = {}
    for ch in range(num_channels):
        voc_data[ch] = []

    # run steady-state voc
    t_start = time.time()
    while time.time() - t_start < t_end:
        smu.configure_dc(0, source_mode="i")
        point_data = smu.measure("dc")
        for ch, ch_data in point_data.items():
            voc_data[ch].extend(ch_data)

        time.sleep(delay)

    return voc_data


with m1k.smu() as smu:
    # connect all available devices
    smu.connect()

    # configure global settings
    smu.nplc = 1
    smu.settling_delay = 0.005

    # configure channel specific settings for all outputs
    smu.configure_channel_settings(auto_off=False, four_wire=True, v_range=5)

    print("\nRunning steady-state Voc...")

    # run mppt
    voc_data = steady_state_voc(smu, delay=0.5, t_end=15)

    # disable output manually because auto-off is false
    smu.enable_output(False)

# plot the processed data
fig, ax = plt.subplots()

max_vocs = []
for ch, ch_data in voc_data.items():
    voltages = []
    times = []
    t0 = ch_data[0][2]
    for v, i, t, s in ch_data:
        voltages.append(abs(v))
        times.append(t - t0)
    ax.scatter(times, voltages, label=f"channel {ch}")
    max_vocs.append(max(voltages))

ax.tick_params(direction="in", top=True, right=True, labelsize="large")
ax.set_xlabel("Time (s)", fontsize="large")
ax.set_ylabel("|V_oc| (V)", fontsize="large")
ax.set_ylim((0, max(max_vocs) * 1.1))
ax.legend()

fig.tight_layout()

plt.show()
