import multiprocessing
import time

import pysmu

s = pysmu.Session()


def write_all(v):
    for dev in s.devices:
        dev.channels["A"].write([v], cyclic=False)

    for dev in s.devices:
        dev.channels["A"].mode = pysmu.Mode.SVMI


if __name__ == "__main__":
    n = 100000

    for i in range(10):
        t0 = time.time()
        write_all(0)
        t1 = time.time()
        print(f"write time: {t1-t0}s")

        passed = False
        i = 0
        while (passed is False) or (i < 3):
            try:
                t2 = time.time()
                s.run(n)
                t3 = time.time()
                print(f"run time: {t3-t2}")
                passed = True
            except pysmu.exceptions.SessionError:
                pass

            i += 1

        t4 = time.time()
        data = s.read(n)
        t5 = time.time()
        print(f"read time: {t5-t4}")
        print(len(data), [len(d) for d in data])
