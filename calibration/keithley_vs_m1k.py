"""Compare devices measurements from Keithley 2400 with a calibrated M1K."""

import pathlib
import time
import sys

import matplotlib.pyplot as plt
import numpy as np
import pyvisa
import yaml

sys.path.insert(1, str(pathlib.Path.cwd().parent))
import m1k.m1k as m1k


cwd = pathlib.Path.cwd()
cal_data_folder = cwd.joinpath("data")
save_file = cal_data_folder.joinpath(f"k_vs_m_{time.time()}.yaml")

# connect to keithley 2400
print("\nConnecting to Keithley 2400...")
address = "ASRL3::INSTR"
baud = 19200
flow_control = 1
term_char = "\n"

rm = pyvisa.ResourceManager()

keithley2400 = rm.open_resource(
    address,
    baud_rate=baud,
    flow_control=flow_control,
    write_termination=term_char,
    read_termination=term_char,
)
print(f"Keithley ID: {keithley2400.query('*IDN?')}")
print("Connected!")

# connect to smu
print("\nConnecting to ADALM1000...")
# add all with default settings
smu = m1k.smu()
smu.connect()
print(f"ADALM1000 ID: {smu.get_channel_id(0)}")

# load external calibration
ext_cal_file = cal_data_folder.joinpath(
    "cal_1617792611_2032205054325238313130333030323_v2.yaml"
)
with open(ext_cal_file, "r") as f:
    ext_cal = yaml.load(f, Loader=yaml.FullLoader)
ext_cal = ext_cal["2032205054325238313130333030323"]
smu.use_external_calibration(0, ext_cal)

print("Connected!")

# set global measurement parameters
nplc = 1
settling_delay = 0.005
plf = 50  # power line frequency in Hz

# set m1k measurement paramters
smu.nplc = nplc
smu.settling_delay = settling_delay

# define sweep
start_v = 0
stop_v = 0.6
v_points = 20

# define steady-state measurements
ss_delay = 1
ss_points = 10

# setup keithley
print("\nConfiguring Keithley 2400...")
# reset
keithley2400.write("*RST")
# Disable the output
keithley2400.write(":OUTP OFF")
# Disable beeper
keithley2400.write(":SYST:BEEP:STAT OFF")
# Set front terminals
keithley2400.write(":ROUT:TERM FRONT")
# Enable 4-wire sense
keithley2400.write(":SYST:RSEN 1")
# Don't auto-off source after measurement
keithley2400.write(":SOUR:CLE:AUTO OFF")
# Set output-off mode to high impedance
keithley2400.write(":OUTP:SMOD HIMP")
# Make sure output never goes above 20 V
keithley2400.write(":SOUR:VOLT:PROT 20")
# Enable and set concurrent measurements
keithley2400.write(":SENS:FUNC:CONC ON")
keithley2400.write(':SENS:FUNC "CURR", "VOLT"')
# Set read format
keithley2400.write(":FORM:ELEM TIME,VOLT,CURR,STAT")
# Set the integration filter (applies globally for all measurement types)
keithley2400.write(f":SENS:CURR:NPLC {nplc}")
# Set the delay
keithley2400.write(f":SOUR:DEL {settling_delay}")
# Disable autozero
keithley2400.write(":SYST:AZER OFF")
print("Keithley configuration complete!")


def m1k_sweep(start, stop, points):
    """Perform voltage sweep using ADALM1000."""
    print("\nPerforming m1k voltage sweep measurement...")

    # configure a sweep
    smu.configure_sweep(
        start=start, stop=stop, points=points, dual=False, source_mode="v"
    )

    # measure the sweep
    data = smu.measure("sweep")

    # disable output manually because auto-off is false
    smu.enable_output(False)

    print("m1k voltage sweep complete!")

    return data


def keithley_sweep(start, stop, points):
    """Perform voltage sweep using Keithley 2400."""
    print("\nPerforming keithley voltage sweep measurement...")

    sweep_voltages = np.linspace(start, stop, points)

    # Autorange keithley source votlage and measure current
    keithley2400.write(":SOUR:FUNC VOLT")
    keithley2400.write(":SENS:FUNC 'CURR'")
    keithley2400.write(":SOUR:VOLT:RANG:AUTO ON")
    keithley2400.write(":SENS:CURR:RANG:AUTO ON")

    # set keithley to source zero volts and enable output
    keithley2400.write(":SOUR:VOLT 0")
    keithley2400.write(":OUTP ON")
    keithley2400.write(":SYST:AZER ONCE")

    data = []
    for v in sweep_voltages:
        keithley2400.write(f":SOUR:VOLT {v}")
        data.append(keithley2400.query_ascii_values(":READ?"))

    # turn off smu outputs
    keithley2400.write(":SOUR:VOLT 0")
    keithley2400.write(":OUTP OFF")

    print("Keithley voltage sweep complete!")

    return data


def m1k_voc(delay, points):
    """Perform Voc measurement using m1k."""
    print("\nPerforming m1k Voc measurement...")

    # init container
    num_channels = smu.num_channels
    voc_data = {}
    for ch in range(num_channels):
        voc_data[ch] = []

    # run steady-state voc
    for point in range(points):
        smu.configure_dc(0, source_mode="i")
        point_data = smu.measure("dc")
        for ch, ch_data in point_data.items():
            voc_data[ch].extend(ch_data)

        time.sleep(delay)

    smu.enable_output(False)

    print("m1k voc measurement complete!")

    return voc_data


def keithley_voc(delay, points):
    """Perform keithley voc measurement."""
    print("\nPerforming keithley voc measurement...")

    # Autorange keithley source votlage and measure current
    keithley2400.write(":SOUR:FUNC CURR")
    keithley2400.write(":SENS:FUNC 'VOLT'")
    keithley2400.write(":SOUR:CURR:RANG:AUTO ON")
    keithley2400.write(":SENS:VOLT:RANG:AUTO ON")

    # set keithley to source zero volts and enable output
    keithley2400.write(":SOUR:CURR 0")
    keithley2400.write(":OUTP ON")
    keithley2400.write(":SYST:AZER ONCE")

    # run steady-state voc
    data = []
    for point in range(points):
        data.append(keithley2400.query_ascii_values(":READ?"))
        time.sleep(delay)

    keithley2400.write(":OUTP OFF")

    print("Keithley voc measurement complete!")

    return data


def m1k_jsc(delay, points):
    """Perform jsc measurement using m1k."""
    print("\nPerforming m1k jsc measurement...")

    # init container
    num_channels = smu.num_channels
    jsc_data = {}
    for ch in range(num_channels):
        jsc_data[ch] = []

    # run steady-state jsc
    for point in range(points):
        smu.configure_dc(0, source_mode="v")
        point_data = smu.measure("dc")
        for ch, ch_data in point_data.items():
            jsc_data[ch].extend(ch_data)

        time.sleep(delay)

    smu.enable_output(False)

    print("m1k jsc measurement complete!")

    return jsc_data


def keithley_jsc(delay, points):
    """Perform keithley jsc measurement."""
    print("\nPerforming keithley jsc measurement...")

    # Autorange keithley source votlage and measure current
    keithley2400.write(":SOUR:FUNC VOLT")
    keithley2400.write(":SENS:FUNC 'CURR'")
    keithley2400.write(":SOUR:VOLT:RANG:AUTO ON")
    keithley2400.write(":SENS:CURR:RANG:AUTO ON")

    # set keithley to source zero volts and enable output
    keithley2400.write(":SOUR:VOLT 0")
    keithley2400.write(":OUTP ON")
    keithley2400.write(":SYST:AZER ONCE")

    # run steady-state jsc
    data = []
    for point in range(points):
        data.append(keithley2400.query_ascii_values(":READ?"))
        time.sleep(delay)

    keithley2400.write(":OUTP OFF")

    print("Keithley jsc measurement complete!")

    return data


# perform measurements
input("\nConnect device to keithley 2400 then press [Enter] to run measurements...")
keithley_voc_data = keithley_voc(ss_delay, ss_points)
keithley_sweep_data = keithley_sweep(start_v, stop_v, v_points)
keithley_jsc_data = keithley_jsc(ss_delay, ss_points)

input("\nConnect device to M1k then press [Enter] to run measurements...")
m1k_voc_data = m1k_voc(ss_delay, ss_points)[0]
m1k_sweep_data = m1k_sweep(start_v, stop_v, v_points)[0]
m1k_jsc_data = m1k_jsc(ss_delay, ss_points)[0]

# save measurement data
data_dict = {
    "m1k": {"sweep": m1k_sweep_data, "voc": m1k_voc_data, "jsc": m1k_jsc_data},
    "keithley": {
        "sweep": keithley_sweep_data,
        "voc": keithley_voc_data,
        "jsc": keithley_jsc_data,
    },
}
with open(save_file, "w") as f:
    yaml.dump(data_dict, f)

# plot voc
fig, ax = plt.subplots()

for data, sm in zip([keithley_voc_data, m1k_voc_data], ["keithley", "m1k"]):
    voltages = []
    times = []
    t0 = data[0][2]
    for v, i, t, s in data:
        voltages.append(v)
        times.append(t - t0)
    ax.scatter(times, voltages, label=f"{sm}")

ax.tick_params(direction="in", top=True, right=True, labelsize="large")
ax.set_xlabel("Time (s)", fontsize="large")
ax.set_ylabel("Voc (V)", fontsize="large")
ax.legend()

fig.tight_layout()

plt.show()

# plot sweeps
fig, ax = plt.subplots()

for data, sm in zip([keithley_sweep_data, m1k_sweep_data], ["keithley", "m1k"]):
    voltages = []
    currents = []
    for v, i, t, s in data:
        voltages.append(v)
        currents.append(i * 1000)
    ax.scatter(voltages, currents, label=f"{sm}")

ax.tick_params(direction="in", top=True, right=True, labelsize="large")
ax.set_xlabel("Applied bias (V)", fontsize="large")
ax.set_ylabel("Current (mA)", fontsize="large")
ax.legend()

fig.tight_layout()

plt.show()

# plot jsc
fig, ax = plt.subplots()

for data, sm in zip([keithley_jsc_data, m1k_jsc_data], ["keithley", "m1k"]):
    currents = []
    times = []
    t0 = data[0][2]
    for v, i, t, s in data:
        currents.append(i * 1000)
        times.append(t - t0)
    ax.scatter(times, currents, label=f"{sm}")

ax.tick_params(direction="in", top=True, right=True, labelsize="large")
ax.set_xlabel("Time (s)", fontsize="large")
ax.set_ylabel("Jsc (mA)", fontsize="large")
ax.legend()

fig.tight_layout()

plt.show()