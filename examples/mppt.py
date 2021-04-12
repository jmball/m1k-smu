"""Example using the m1k library to perform max power point tracking on 1 channel."""

import time
import pathlib
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(1, str(pathlib.Path.cwd().parent))
import m1k.m1k as m1k


def mppt(smu, v_start=0.3, a=1, delay=0.5, t_end=30):
    """Run maximum power point tracking scans on all channels.

    Parameters
    ----------
    smu : m1k.smu()
        SMU object.
    v_start : float
        Start voltage for all trackers.
    a : float
        Learning rate.
    delay : float
        Time between updates.
    t_end : float
        Total tracking time in seconds.

    Returns
    -------
    data : list of tuples
        Maximum power point tracking data.
    """

    def calc_new_voltage(v_lat, v_old, p_lat, p_old, a):
        """Calculate next voltage for maximum power point tracker.

        Parameters
        ----------
        v_lat : float
            Latest voltage.
        v_old: float
            Last voltage
        p_lat : float
            Latest power.
        p_old : float
            Last power.
        a : float
            Learning rate.

        Returns
        -------
        v_new : float
            Next voltage.
        """
        dp = p_lat - p_old
        dv = v_lat - v_old
        dpdv = dp / dv

        v_step = a * dpdv

        v_min = 0.002
        v_max = 0.2

        # coerce min step
        if np.absolute(v_step) < v_min:
            v_step = np.sign(np.random.rand() - 0.5) * v_min

        # coerce max step
        if np.absolute(v_step) > v_max:
            v_step = v_max * np.sign(v_step)

        v_new = v_old - v_step

        return v_new

    # init container
    num_channels = smu.num_channels
    mppt_data = {}
    for ch in range(num_channels):
        mppt_data[ch] = []

    # init tracker
    v_starts = [v_start for ch in range(num_channels)]
    smu.configure_dc(v_starts)
    point_data = smu.measure("dc")
    for ch, ch_data in point_data.items():
        mppt_data[ch].extend(ch_data)

    v_nexts = [v_start + 0.01 for ch in range(num_channels)]
    smu.configure_dc(v_nexts)
    point_data = smu.measure("dc")
    for ch, ch_data in point_data.items():
        mppt_data[ch].extend(ch_data)

    v_news = []
    for ch, ch_data in mppt_data.items():
        v_old = ch_data[0][0]
        v_lat = ch_data[1][0]
        p_old = ch_data[0][0] * ch_data[0][1]
        p_lat = ch_data[1][0] * ch_data[1][1]
        v_news.append(calc_new_voltage(v_lat, v_old, p_lat, p_old, a))

    # continue mppt
    i = 2
    t_start = time.time()
    while time.time() - t_start < t_end:
        smu.configure_dc(v_news)
        point_data = smu.measure("dc")
        for ch, ch_data in point_data.items():
            mppt_data[ch].extend(ch_data)

        v_news = []
        for ch, ch_data in mppt_data.items():
            v_old = ch_data[i - 1][0]
            v_lat = ch_data[i][0]
            p_old = ch_data[i - 1][0] * ch_data[i - 1][1]
            p_lat = ch_data[i][0] * ch_data[i][1]
            v_news.append(calc_new_voltage(v_lat, v_old, p_lat, p_old, a))

        i += 1
        time.sleep(delay)

    return mppt_data


with m1k.smu() as smu:
    # connect all available devices
    smu.connect()

    # configure global settings
    smu.nplc = 1
    smu.settling_delay = 0.005

    # configure channel specific settings for all outputs
    smu.configure_channel_settings(auto_off=False, four_wire=True, v_range=5)

    print("\nRunning mppt...")

    # run mppt
    mppt_data = mppt(smu, v_start=0.1, a=20, delay=0.5, t_end=60)

    # disable output manually because auto-off is false
    smu.enable_output(False)

# plot the processed data
fig, ax = plt.subplots(1, 3)
ax1, ax2, ax3 = ax

for ch, ch_data in mppt_data.items():
    voltages = []
    currents = []
    times = []
    powers = []
    t0 = ch_data[0][2]
    for v, i, t, s in ch_data:
        voltages.append(abs(v))
        currents.append(abs(i * 1000))
        times.append(t - t0)
        powers.append(abs(v * i * 1000))
    ax1.scatter(times, voltages, label=f"channel {ch}")
    ax2.scatter(times, currents, label=f"channel {ch}")
    ax3.scatter(times, powers, label=f"channel {ch}")

ax1.tick_params(direction="in", top=True, right=True, labelsize="large")
ax1.set_xlabel("Time (s)", fontsize="large")
ax1.set_ylabel("|Voltage| (V)", fontsize="large")
ax1.legend()

ax2.tick_params(direction="in", top=True, right=True, labelsize="large")
ax2.set_xlabel("Time (s)", fontsize="large")
ax2.set_ylabel("|Current| (mA)", fontsize="large")
ax2.legend()

ax3.tick_params(direction="in", top=True, right=True, labelsize="large")
ax3.set_xlabel("Time (s)", fontsize="large")
ax3.set_ylabel("|Power| (mW)", fontsize="large")
ax3.legend()


fig.tight_layout()

plt.show()
