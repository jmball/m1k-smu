"""Identify board serial numbers by lighting their LEDs."""

import pathlib
import sys

sys.path.insert(1, str(pathlib.Path.cwd().parent.joinpath("src")))
import m1k.m1k as m1k


with m1k.smu() as smu:
    smu.connect()

    for board in range(smu.num_boards):
        smu.set_leds(2 * board, R=True, G=True, B=True)

        input(
            f"This board's serial is '{smu.get_channel_id(2 * board)}'. Press Enter to"
            + " continue..."
        )

        smu.set_leds(2 * board, R=False, G=True, B=False)
