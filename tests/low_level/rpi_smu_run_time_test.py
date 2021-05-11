import time
import warnings

import pysmu

s = pysmu.Session()


def write_all(v):
    for dev in s.devices:
        dev.channels["A"].write([v], cyclic=False)

    attempt = 0
    for _ in range(3):
        print(f"Output on attempt {i}")
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
    n = 100000

    for i in range(10):
        t0 = time.time()
        write_all(0)
        t1 = time.time()
        print(f"write time: {t1-t0}s")

        attempt = 0
        for _ in range(3):
            print(f"Run on attempt {i}")
            try:
                t2 = time.time()
                s.run(n)
                t3 = time.time()
                print(f"run time: {t3-t2}")
                break
            except pysmu.exceptions.SessionError as e:
                warnings.warn(str(e))

            attempt += 1

        if attempt == 3:
            raise RuntimeError("Couldn't run scan after three attempts.")
        else:
            t4 = time.time()
            # blocking indefinitely can cause program to hang, so just return
            # immediately
            data = s.read(n)
            t5 = time.time()
            print(f"read time: {t5-t4}")
            print(len(data), [len(d) for d in data])
