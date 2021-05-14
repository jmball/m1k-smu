import random
import time
import warnings

import pysmu

s = pysmu.Session()
devs = s.devices


def write_all(vs, retries=3):
    for dev in devs:
        dev.channels["A"].write(vs, cyclic=False)
        dev.channels["B"].write(vs, cyclic=False)

    attempt = 0
    for _ in range(retries):
        print(f"Output on attempt {attempt}")
        try:
            for dev in s.devices:
                dev.channels["A"].mode = pysmu.Mode.SVMI
                dev.channels["B"].mode = pysmu.Mode.SVMI
            break
        except pysmu.exceptions.DeviceError as e:
            warnings.warn(str(e))

        attempt += 1

    if attempt == retries:
        raise RuntimeError("Couldn't update output mode after three attempts.")


if __name__ == "__main__":
    retries = 10
    n_sweep = 100000
    n_cont = 500
    scans = 2500
    cont_scans = 20

    sweep_expected_lengths = [n_sweep] * len(s.devices)
    sweep_total_times = []
    sweep_dropped_scans = []
    cont_expected_lengths = [n_cont] * len(s.devices)
    cont_total_times = []
    cont_dropped_scans = []
    for i in range(scans):
        print(f"SCAN {i}\n------")
        v = random.random()
        t0 = time.time()
        write_all([v] * n_sweep, retries)
        t1 = time.time()
        print(f"write time: {t1-t0} s")

        attempt = 0
        for _ in range(retries):
            print(f"Run on attempt {attempt}")
            try:
                t2 = time.time()
                s.run(n_sweep)
                t3 = time.time()
                print(f"run time: {t3-t2} s")
                break
            except pysmu.exceptions.SessionError as e:
                warnings.warn(str(e))
                time.sleep(0.5)

            attempt += 1

        if attempt == retries:
            raise RuntimeError(f"Couldn't run scan after {retries} attempts.")
        else:
            t4 = time.time()
            # blocking indefinitely can cause program to hang, so just return
            # immediately
            data = s.read(n_sweep, 10000)
            t5 = time.time()
            print(f"read time: {t5-t4} s")
            lengths = [len(d) for d in data]
            print(f"Data lengths: {lengths}")
            # removing the variable from memory at creating it again is faster than
            # overwriting
            del data
            t6 = time.time()
            print(f"Del time: {t6-t5} s\n")

        sweep_total_times.append(t6 - t0)
        m = sum(sweep_total_times) / len(sweep_total_times)
        print(f"mean time: {m} s")

        if lengths != sweep_expected_lengths:
            sweep_dropped_scans.append(i)
        print(f"scans with dropped data: {sweep_dropped_scans}")

        # start continuous mode
        print("\nStarting continuous mode...")
        attempt = 0
        for _ in range(retries):
            print(f"Start attempt: {_}")
            try:
                s.start(0)
                break
            except pysmu.exceptions.SessionError as e:
                warnings.warn(str(e))

            attempt += 1

        if attempt == retries:
            raise RuntimeError(
                f"Couldn't start continuous mode after {retries} attempts."
            )

        # wait for start to register
        time.sleep(0.25)

        # run some measurements
        for _ in range(cont_scans):
            v = random.random()
            print(f"\nVoltage: {v}")

            # write voltages
            t0 = time.time()
            for dev in devs:
                dev.channels["A"].write([v], cyclic=True)
                dev.channels["B"].write([v], cyclic=True)
            t1 = time.time()
            print(f"write time: {t1-t0} s")

            # wait for writes to register
            time.sleep(0.25)

            # flush read buffers
            for ix, dev in enumerate(devs):
                dev.flush(-1, True)
            t2 = time.time()
            print(f"dummy read time: {t2-t1} s")

            # read data
            data = s.read(n_cont, 1000)
            t3 = time.time()
            print(f"read time: {t3-t2} s")
            lengths = [len(d) for d in data]
            print(f"Data lengths: {lengths}")
            # removing the variable from memory and creating it again is faster than
            # overwriting
            del data
            t4 = time.time()
            print(f"Del time: {t4-t3} s\n")

            cont_total_times.append(t4 - t0)
            m = sum(cont_total_times) / len(cont_total_times)
            print(f"mean time: {m} s")

            if lengths != cont_expected_lengths:
                cont_dropped_scans.append(i)
            print(f"scans with dropped data: {cont_dropped_scans}")

        s.end()
