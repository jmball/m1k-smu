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
    for a in range(retries):
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
    sweep_run_failures = 0
    cont_expected_lengths = [n_cont] * len(s.devices)
    cont_total_times = []
    cont_dropped_scans = []
    cont_start_failures = 0
    cont_end_failures = 0
    cont_unexpected_v = []
    for i in range(scans):
        print(f"\nSCAN {i}\n------")
        v = random.random()

        attempt = 0
        for _ in range(retries):
            t0 = time.time()
            write_all([v] * n_sweep, retries)
            t1 = time.time()
            print(f"write time: {t1-t0} s")

            print(f"Run sweep attempt {attempt}")
            try:
                t2 = time.time()
                s.run(n_sweep)
                t3 = time.time()
                print(f"run time: {t3-t2} s")

                t4 = time.time()
                # blocking indefinitely can cause program to hang
                data = s.read(n_sweep, 10000)
                t5 = time.time()
                print(f"read time: {t5-t4} s")
                lengths = [len(d) for d in data]
                print(f"Data lengths: {lengths}")
                # removing the variable from memory and creating it again is faster than
                # overwriting
                del data
                t6 = time.time()
                print(f"Del time: {t6-t5} s")

                sweep_total_times.append(t6 - t0)

                if lengths != sweep_expected_lengths:
                    sweep_dropped_scans.append(i)
                else:
                    break
            except pysmu.exceptions.SessionError as e:
                warnings.warn(str(e))
                sweep_run_failures += 1
                time.sleep(1)

            attempt += 1

        if attempt == retries:
            raise RuntimeError(f"Couldn't run sweep after {retries} attempts.")

        # print metadata of scans to date
        m = sum(sweep_total_times) / len(sweep_total_times)
        print(f"mean time: {m} s")
        print(f"scans with retries: {sweep_dropped_scans}")
        print(f"Sweep run failures: {sweep_run_failures}")

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
                cont_start_failures += 1
                time.sleep(1)

            attempt += 1

        if attempt == retries:
            raise RuntimeError(
                f"Couldn't start continuous mode after {retries} attempts."
            )

        # wait for start to register
        while True:
            if s.continuous is True:
                break

        # run some measurements
        for scan in range(cont_scans):
            v = (0.5 * scans) % 5
            print(f"\nVoltage {i * cont_scans + scan}: {v}")

            attempt = 0
            for _ in range(retries):
                print(f"Attempt: {attempt}")
                # write voltages
                t0 = time.time()
                for dev in devs:
                    dev.channels["A"].write([v], cyclic=True)
                    dev.channels["B"].write([v], cyclic=True)
                t1 = time.time()
                print(f"write time: {t1-t0} s")

                # wait for writes to register
                # without this delay voltage transitions will be captured in the read
                time.sleep(0.25)

                # flush read buffers
                for ix, dev in enumerate(devs):
                    dev.flush(-1, True)
                t2 = time.time()
                print(f"dummy read time: {t2-t1} s")

                # read data
                data = s.read(n_cont, 10000)
                t3 = time.time()
                print(f"read time: {t3-t2} s")

                lengths = [len(d) for d in data]
                print(f"Data lengths: {lengths}")
                if lengths != cont_expected_lengths:
                    # didn't get the data we need so retry
                    retry = True

                    cont_dropped_scans.append([i, scan])
                else:
                    # we got the amount of data expected so no need to retry
                    retry = False

                    # validate voltage data is approximately right
                    for ch_data in data:
                        vsa = [
                            (d[0][0] > v - 0.1) and (d[0][0] < v + 0.1) for d in ch_data
                        ]
                        vsb = [
                            (d[1][0] > v - 0.1) and (d[1][0] < v + 0.1) for d in ch_data
                        ]
                        if (not all(vsa)) or (not all(vsb)):
                            cont_unexpected_v.append([i, scan, attempt])

                    print(f"scans with unexpected voltage: {cont_unexpected_v}")
                    print(f"scans with retries: {cont_dropped_scans}")

                # removing the variable from memory and creating it again is faster than
                # overwriting
                t4 = time.time()
                del data
                t5 = time.time()
                print(f"Del time: {t5-t4} s")
                cont_total_times.append(t5 - t0)
                m = sum(cont_total_times) / len(cont_total_times)
                print(f"mean time: {m} s")

                if retry is False:
                    break

        # attempt to end
        attempt = 0
        for _ in range(retries):
            print(f"End attempt: {_}")
            try:
                s.end()
                break
            except pysmu.exceptions.SessionError as e:
                warnings.warn(str(e))
                cont_end_failures += 1
                time.sleep(1)

            attempt += 1

        if attempt == retries:
            raise RuntimeError(
                f"Couldn't end continuous mode after {retries} attempts."
            )

        print(f"Continuous start failures: {cont_start_failures}")
        print(f"Continuous end failures: {cont_end_failures}")
