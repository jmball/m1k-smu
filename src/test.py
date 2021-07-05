import m1k
import time

smu = m1k.smu()
smu.connect()
smu.configure_sweep(0, 1, 101)
for i in range(1000):
    t0 = time.time()
    smu.measure(0)
    smu.enable_output(True, 0)
    smu.measure(0, "sweep")
    smu.enable_output(False, 0)
    print(i, time.time() - t0)
smu.disconnect()
