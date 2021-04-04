"""Calibrate the M1K with a Keithley 2400."""

import pathlib
import time

import numpy as np
import pysmu
import pyvisa


# connect to keithley 2400
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
    read_termination=term_char
)

# connect to M1k
session = pysmu.Session() # add all with default settings, make sure only one is connected
mk1 = session.devices[0]
mk1chA = mk1.channels["A"]
mk1chB = mk1.channels["B"]

# save calibration file in same folder
cwd = pathlib.Path.cwd()
save_file = cwd.joinpath(f"cal_{int(time.time())}_{mk1.serial}.txt")

# set global measurement parameters
nplc = 1
settling_delay = 0.005
plf = 50 # power line frequency in Hz

# set mk1 measurement paramters
mk1_nplc = (nplc / plf) * session.sample_rate # number of samples
mk1_settling_delay = settling_delay * session.sample_rate # number of samples
mk1_samples = mk1_nplc + mk1_settling_delay

# set measurement data using logarithmic spacing
_log_points = np.logspace(1, 4, 25)
cal_voltages = _log_points * 5 / 10000
cal_voltages = [f"{v:6.4f}" for v in cal_voltages]

cal_currents_0 = _log_points * 2 / 100000
cal_currents_0 = [f"{i:6.4f}" for i in cal_currents_0]
cal_currents_1 = [f"{i:6.4f}" for i in -cal_currents_0]
cal_currents = ["0.0000"] + cal_currents_0 + cal_currents_1

# setup keithley
# reset
keithley2400.write('*RST')
# Disable the output
keithley2400.write('OUTP OFF')
# Set front terminals
keithley2400.write(':ROUT:TERM FRONT')
# Enable 4-wire sense
keithley2400.write(':SYST:RSEN 1')
# Don't auto-off source after measurement
keithley2400.write(':SOUR:CLE:AUTO OFF')
# Set output-off mode to high impedance
keithley2400.write(':OUTP:SMOD HIMP')
# Make sure output never goes above 20 V
keithley2400.write(':SOUR:VOLT:PROT 20')
# Enable and set concurrent measurements
keithley2400.write(':SENS:FUNC:CONC ON')
keithley2400.write(':SENS:FUNC "CURR", "VOLT"')
# Set read format
keithley2400.write(':FORM:ELEM TIME,VOLT,CURR,STAT')
# Set the integration filter (applies globally for all measurement types)
keithley2400.write(f':SENS:CURR:NPLC {nplc}')
# Set the delay
keithley2400.write(f':SOUR:DEL {settling_delay}')
# Disable autozero
keithley2400.write(':SYST:AZER OFF')


### perform CHA measure voltage calibration

# Autorange keithley source votlage and measure current
keithley2400.write(f':SOUR:VOLT:AUTO ON')
keithley2400.write(f':SENS:CURR:AUTO ON')

# set mk1 to source current measure voltage and set current to 0
mk1chA.mode = pysmu.Mode.SIMV
mk1chA.constant(0)

# set keithley to source zero volts and enable output
keithley2400.write(':SOUR:VOLT 0')
keithley2400.write('OUTP ON')
keithley2400.write(':SYST:AZER ONCE')

# measure and save
with open(save_file, "w") as f:
    f.write(f"# Channel A, measure V\n")
    f.wrtie("</>\n")
    # run through the list of voltages
    for v in cal_voltages:
        keithley2400.write(f':SOUR:VOLT {v}')
        time.sleep(0.1)
        keithley_data = keithley2400.query_ascii_values(':READ?')
        mk1_data = mk1chA.get_samples(mk1_samples)
        mk1_vs = [v for v, i in mk1_data[mk1_settling_delay:]]
        mk1_v = sum(mk1_vs) / len(mk1_vs)
        f.write(f"<{keithley_data[1]:6.4f}, {mk1_v:7.5f}>\n")
    
    f.write(r"<\>\n\n")


# perform CHA measure current calibration

# perform CHA source voltage calibration

# perform CHA source current calibration

# perform CHB measure voltage calibration

# perform CHB measure current calibration

# perform CHB source voltage calibration

# perform CHB source current calibration

