"""Example using the m1k library to perform max power point tracking on 1 channel."""

import time
import pathlib
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(1, str(pathlib.Path.cwd().parent))
import m1k.m1k as m1k


def mppt(smu, v_start=0.3, a=0.1, delay=0.5, t_end=15):
    """Run a maximum power point tracking scan on the first channel.

    Parameters
    ----------
    smu : m1k.smu()
        SMU object.
    v_start : float
        Start voltage for tracker.
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

    # init tracker
    data = []
    smu.configure_dc(v_start)
    data.extend(smu.measure("dc")[0])
    smu.configure_dc(v_start + 0.01)
    data.extend(smu.measure("dc")[0])
    v_old = data[0][0]
    v_lat = data[1][0]
    p_old = data[0][0] * data[0][1]
    p_lat = data[1][0] * data[1][1]
    v_new = calc_new_voltage(v_lat, v_old, p_lat, p_old, a)

    # continue mppt
    i = 2
    t_start = time.time()
    while time.time() - t_start < t_end:
        data.extend(smu.measure(v_new)[0])
        v_old = data[i - 1][0]
        v_lat = data[i][0]
        p_old = data[i - 1][0] * data[i - 1][1]
        p_lat = data[i][0] * data[i][1]
        v_new = calc_new_voltage(v_lat, v_old, p_lat, p_old, a)
        i += 1
        time.sleep(delay)

    return data


with m1k.smu() as smu:
    # connect all available devices
    smu.connect()

    # configure all outputs
    smu.configure_all_channels(
        nplc=1, settling_delay=0.005, auto_off=False, four_wire=True, v_range=5
    )

    print("\nRunning mppt...")

    # run mppt
    data = mppt(smu, v_start=0.3, a=0.1, delay=0.5, t_end=15)

    # disable output manually because auto-off is false
    smu.enable_output(False)

# extract data for plotting
times = []
voltages = []
currents = []
powers = []
for v, i, t, s in data:
    times.append(t)
    voltages.append(abs(v))
    currents.append(abs(i * 1000))
    powers.append(abs(i * v * 1000))

# plot the processed data
fig, ax = plt.subplots(1, 3)
ax1, ax2, ax3 = ax
ax1.scatter(times, voltages)
ax1.tick_params(direction="in", top=True, right=True, labelsize="large")
ax1.set_xlabel("Time (s)", fontsize="large")
ax1.set_ylabel("|Voltage| (V)", fontsize="large")

ax2.scatter(times, currents)
ax2.tick_params(direction="in", top=True, right=True, labelsize="large")
ax2.set_xlabel("Time (s)", fontsize="large")
ax2.set_ylabel("|Current| (mA)", fontsize="large")

ax3.scatter(times, powers)
ax3.tick_params(direction="in", top=True, right=True, labelsize="large")
ax3.set_xlabel("Time (s)", fontsize="large")
ax3.set_ylabel("|Power| (mW)", fontsize="large")

fig.show()
