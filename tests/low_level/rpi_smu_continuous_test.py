import pysmu
import time
import matplotlib.pyplot as plt

s = pysmu.Session()
devs = s.devices

# setup
for dev in devs:
    dev.channels["A"].write([0], cyclic=False)

for dev in devs:
    dev.channels["A"].mode = pysmu.Mode.SVMI
s.run(1)
data = s.read(1)
for dev in devs:
    dev.channels["A"].mode = pysmu.Mode.SVMI

# start continuous mode
s.start(0)

# run some measurements
vs = [0, 0.5, 1, 1.5]
data = []
for v in vs:
    t0 = time.time()
    for dev in devs:
        dev.channels["A"].write([v], cyclic=True)
    s.read(100000, -1)
    data.append(s.read(2500, -1))
    print(time.time() - t0)

# end continuous mode
s.end()
