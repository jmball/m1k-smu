import time
import warnings

import pysmu

s = pysmu.Session()


def write_all(v):
    for dev in s.devices:
        dev.channels["A"].write([v], cyclic=False)

    for i in range(3):
        print(f"Output on attempt {i}")
        try:
            for dev in s.devices:
                dev.channels["A"].mode = pysmu.Mode.SVMI
            break
        except pysmu.exceptions.DeviceError as e:
            warnings.warn(str(e))

        i += 1


if __name__ == "__main__":
    n = 100000

    for i in range(10):
        t0 = time.time()
        write_all(0)
        t1 = time.time()
        print(f"write time: {t1-t0}s")

        for i in range(3):
            print(f"Run on attempt {i}")
            try:
                t2 = time.time()
                s.run(n)
                t3 = time.time()
                print(f"run time: {t3-t2}")
                break
            except pysmu.exceptions.SessionError as e:
                warnings.warn(str(e))

        t4 = time.time()
        data = s.read(n)
        t5 = time.time()
        print(f"read time: {t5-t4}")
        print(len(data), [len(d) for d in data])
