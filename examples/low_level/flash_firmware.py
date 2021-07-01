"""Flash new firmware on all attached devices."""

import argparse

import pysmu

# get cli args
parser = argparse.ArgumentParser()
parser.add_argument(
    "--path",
    type=str,
    default="",
    help="Path to firmware binary",
)
args = parser.parse_args()

cont = input(
    "\nThe firmware currently installed on all connected devices is about to be erased "
    + "and replaced!\nMake sure you have a backup of the currently installed firmware "
    + "binary before continuing.\nDo you wish to continue flashing the firmware? [y/n] "
)

if cont == "y":
    print("\nFlashing firmware...\n")

    # create session and add all devices
    s = pysmu.Session()

    # flash all devices with new firmware
    s.flash_firmware(args.path)

    print(
        "Firmware flashed successfully! Power cycle the devices to begin using them "
        + "again."
    )
else:
    print("\nFirmware flash aborted!\n")