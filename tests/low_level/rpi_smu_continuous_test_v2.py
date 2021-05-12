import os
import sys
import time
import warnings

import pysmu


s = pysmu.Session()
devs = s.devices

# setup
print("Setting up...\n")
for dev in devs:
    dev.channels["A"].write([0], cyclic=False)

for dev in devs:
    dev.channels["A"].mode = pysmu.Mode.SVMI
s.run(1)
data = s.read(1)
for dev in devs:
    dev.channels["A"].mode = pysmu.Mode.SVMI

# start continuous mode
print("Starting continuous mode...\n")
attempt = 0
for _ in range(3):
    print(f"Start attempt: {_}")
    try:
        s.start(0)
        break
    except pysmu.exceptions.SessionError as e:
        warnings.warn(str(e))

    attempt += 1

if attempt == 3:
    raise RuntimeError("Couldn't start continuous mode after three attempts.")

# run some measurements
vs = [0, 0.5, 1, 1.5]
for v in vs:
    print(f"Voltage: {v}")
    t0 = time.time()
    for ix, dev in enumerate(devs):
        dev.channels["A"].write([v], cyclic=True)
    t1 = time.time()
    print(f"write time: {t1-t0} s")
    for ix, dev in enumerate(devs):
        dev.read(100000, -1)
    t2 = time.time()
    print(f"dummy read time: {t2-t1} s")
    data = s.read(2500, -1)
    t3 = time.time()
    print(f"read time: {t3-t2} s")
    print(f"Data lengths: {[len(d) for d in data]}")
    # removing the variable from memory at creating it again is faster than
    # overwriting
    del data
    t4 = time.time()
    print(f"Del time: {t4-t3} s\n")

# end continuous mode
if os.name == "nt":
    sys.exit()
else:
    s.end()
