import multiprocessing
import time

import pysmu

# create session
s = pysmu.Session()
print(f"Number of devices: {len(s.devices)}\n")


def write_all(v):
    for dev in s.devices:
        dev.channels["A"].write([v], cyclic=False)

    for dev in s.devices:
        dev.channels["A"].mode = pysmu.Mode.SVMI


def run(s, n):
    s.run(n)


if __name__ == "__main__":
    # write voltage
    t0 = time.time()
    write_all(0)
    t1 = time.time()
    print(f"write time: {t1-t0}s\n")

    # number of samples
    n = 100000

    # run capture
    failed = True
    i = 0
    while (failed is True) or (i < 3):
        print(f"Run attempt {i}...")
        t2 = time.time()

        p = multiprocessing.Process(
            target=run,
            args=(
                s,
                n,
            ),
        )
        p.start()

        # 5s timeout for run process
        p.join(5)

        # if timeout occurs terminate process and try again
        if p.is_alive():
            print("...run failed!\n")

            p.terminate()
            p.join()
        else:
            print("...run succeeded!\n")
            failed = False

        t3 = time.time()
        print(f"run time: {t3-t2}s\n")

        i += 1

    t4 = time.time()
    data = s.read(n)
    t5 = time.time()
    print(f"read time: {t5-t4}\n")
    print(len(data), [len(d) for d in data])
