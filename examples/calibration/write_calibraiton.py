"""Write a formatted calibration file to an ADALM1000."""

import pysmu


calibration_file = ""

# connect to M1k
print("\nConnecting to ADALM1000...")
# add all with default settings
session = pysmu.Session()

# make sure only one is connected
if len(session.devices) > 1:
    raise ValueError(
        f"Too many ADALM1000's connected: {len(session.devices)}. Disconnect all "
        + "except the one to be calibrated."
    )
elif len(session.devices) == 0:
    raise ValueError("Device not found. Check connections and try again.")

# setup
m1k = session.devices[0]
print(f"ADALM1000 ID: {m1k.serial}")
m1kchA = m1k.channels["A"]
m1kchB = m1k.channels["B"]
m1kchA.mode = pysmu.Mode.HI_Z
m1kchB.mode = pysmu.Mode.HI_Z
m1k.set_led(2)
print("Connected!")

m1k.write_calibraiton(str(calibration_file))

print(
    "\nNew calibration was written to the device! Power cycle the device to "
    + "ensure calibration is properly stored."
)
