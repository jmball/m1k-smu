"""Example using the m1k library to perform voltage sweeps on all connected devices."""

import csv
import pathlib
import time
import sys

import yaml
import matplotlib.pyplot as plt

sys.path.insert(1, str(pathlib.Path.cwd().parent.joinpath("src")))
import m1k.m1k as m1k


with m1k.smu(plf=50, ch_per_board=2) as smu:
    # connect all available devices
    smu.connect()

    print("Loading calibration data...")
    # load calibration data
    cal_data_folder = pathlib.Path.cwd().joinpath("calibration").joinpath("data")
    cal_data = {}
    for board, serial in enumerate(smu.serials):
        # get list of cal files for given serial
        fs = [f for f in cal_data_folder.glob(f"cal_*_{serial}.yaml")]

        # pick latest one
        fs.reverse()
        cf = fs[0]
        print(f"Found calibration file {cf} for device {serial}.")

        # load cal data
        with open(cf, "r") as f:
            data = yaml.load(f, Loader=yaml.SafeLoader)

        # add data to cal dict
        if smu.ch_per_board == 1:
            cal_data[board] = data
        elif smu.ch_per_board == 2:
            cal_data[2 * board] = data
            cal_data[2 * board + 1] = data

    # configure global settings
    smu.nplc = 1
    smu.settling_delay = 0.005

    # configure channel specific settings for all outputs
    smu.configure_channel_settings(auto_off=False, four_wire=False, v_range=5)

    # configure a sweep
    smu.configure_sweep(start=0, stop=1, points=21, dual=False, source_mode="v")

    # measure the sweep with internal calibration
    t0 = time.time()
    data_int = smu.measure("sweep")
    print(f"Sweep time with internal calibration: {time.time() - t0} s")

    # measure the sweep with external calibraiton
    smu.use_external_calibration(0, cal_data[0])
    smu.use_external_calibration(1, cal_data[1])
    t0 = time.time()
    data_ext = smu.measure("sweep")
    print(f"Sweep time with external calibration: {time.time() - t0} s")

    # disable output manually because auto-off is false
    smu.enable_output(False)

# plot the i, v data
fig, ax = plt.subplots()

voltages_int = [v for v, i, t, s in data_int[0]]
currents_int = [i * 1000 for v, i, t, s in data_int[0]]
ax.scatter(voltages_int, currents_int, label=f"channel {0} int")

voltages_ext = [v for v, i, t, s in data_ext[0]]
currents_ext = [i * 1000 for v, i, t, s in data_ext[0]]
ax.scatter(voltages_ext, currents_ext, label=f"channel {0} ext")

ax.axhline(0, lw=0.5, c="black")
ax.tick_params(direction="in", top=True, right=True, labelsize="large")
ax.set_xlabel("Applied bias (V)", fontsize="large")
ax.set_ylabel("Current (mA)", fontsize="large")
ax.legend()

plt.show()

# plot the R, v data
fig, ax = plt.subplots()

resistances_int = [v / (i / 1000) for v, i in zip(voltages_int, currents_int)]
print(f"R@maxV with internal cal = {resistances_int[-1]} Ohms")
ax.scatter(voltages_int, resistances_int, label=f"channel {0} int")

resistances_ext = [v / (i / 1000) for v, i in zip(voltages_ext, currents_ext)]
print(f"R@maxV with external cal = {resistances_ext[-1]} Ohms")
ax.scatter(voltages_ext, resistances_ext, label=f"channel {0} ext")

ax.axhline(0, lw=0.5, c="black")
ax.tick_params(direction="in", top=True, right=True, labelsize="large")
ax.set_xlabel("Applied bias (V)", fontsize="large")
ax.set_ylabel("Resistance (Ohms)", fontsize="large")
ax.legend()

plt.show()

data_folder = pathlib.Path("data")
save_file_int = data_folder.joinpath(f"sweep_{int(time.time())}_int.tsv")
save_file_ext = data_folder.joinpath(f"sweep_{int(time.time())}_ext.tsv")

with open(save_file_int, "w", newline="\n") as f:
    writer = csv.writer(f, delimiter="\t")
    for row in data_int[0]:
        writer.writerow(row)

with open(save_file_ext, "w", newline="\n") as f:
    writer = csv.writer(f, delimiter="\t")
    for row in data_ext[0]:
        writer.writerow(row)
