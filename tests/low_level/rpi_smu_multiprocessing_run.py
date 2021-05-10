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
    t0 = time.time()
    write_all(0)
    t1 = time.time()
    print(f"write time: {t1-t0}s")

    n = 100000

    failed = True
    i = 0
    while (failed is True) or (i > 3):
        t2 = time.time()

        p = multiprocessing.Process(target=s.run, args=(n,))
        p.start()

        # 5s timeout for run process
        p.join(5)

        if p.is_alive():
            print(f"Attempt {i}: run failed!")

            p.terminate()
            p.join()
        else:
            print(f"Attempt {i}: run succeeded!")
            failed = False

        t3 = time.time()

        print(f"run time: {t3-t2}s")

        i += 1

    t4 = time.time()
    data = s.read(n)
    t5 = time.time()
    print(f"read time: {t5-t4}")
    print(len(data), [len(d) for d in data])
