import time
import warnings

import pysmu

s = pysmu.Session()


def write_all(v, retries=3):
    for dev in s.devices:
        dev.channels["A"].write([v], cyclic=False)

    attempt = 0
    for _ in range(retries):
        print(f"Output on attempt {attempt}")
        try:
            for dev in s.devices:
                dev.channels["A"].mode = pysmu.Mode.SVMI
            break
        except pysmu.exceptions.DeviceError as e:
            warnings.warn(str(e))

        attempt += 1

    if attempt == 3:
        raise RuntimeError("Couldn't update output mode after three attempts.")


if __name__ == "__main__":
    retries = 10
    n = 10000
    scans = 2500

    expected_lengths = [n] * len(s.devices)
    total_times = []
    dropped_scans = []
    for i in range(scans):
        print(f"Scan {i}")
        t0 = time.time()
        write_all(0, retries)
        t1 = time.time()
        print(f"write time: {t1-t0} s")

        attempt = 0
        for _ in range(retries):
            print(f"Run on attempt {attempt}")
            try:
                t2 = time.time()
                s.run(n)
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
            data = s.read(n)
            t5 = time.time()
            print(f"read time: {t5-t4} s")
            lengths = [len(d) for d in data]
            print(f"Data lengths: {lengths}")
            # removing the variable from memory at creating it again is faster than
            # overwriting
            del data
            t6 = time.time()
            print(f"Del time: {t6-t5} s\n")

        total_times.append(t6 - t0)

        if lengths != expected_lengths:
            dropped_scans.append(i)

    m = sum(total_times) / len(total_times)
    print(
        f"Summary\n-------\nmean time = {m} s\nscans with dropped data: {dropped_scans}"
    )
