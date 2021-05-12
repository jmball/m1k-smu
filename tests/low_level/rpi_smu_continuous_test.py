import time

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
s.start(0)

# run some measurements
vs = [0, 0.5, 1, 1.5]
for v in vs:
    print(f"Voltage: {v}")
    t0 = time.time()
    for dev in devs:
        dev.channels["A"].write([v], cyclic=True)
    t1 = time.time()
    print(f"write time: {t1-t0} s")
    s.read(100000, -1)
    data = s.read(2500, -1)
    t2 = time.time()
    print(f"read time: {t2-t1} s\n")
    print(f"Data lengths: {[len(d) for d in data]}")
    # removing the variable from memory at creating it again is faster than
    # overwriting
    # del data
    # t3 = time.time()
    # print(f"Del time: {t3-t2} s\n")

# end continuous mode
s.end()
