"""TCP server for SMU."""

import ast
import os
import pathlib
import queue
import socket
import threading
import warnings
import sys

import yaml

sys.path.insert(1, str(pathlib.Path.cwd().parent.parent))
import m1k.m1k as m1k

# get primary ip address
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(("10.255.255.255", 1))
ip = s.getsockname()[0]
s.close()

HOST = ip
PORT = 2101
TERMCHAR = "\n"
TERMCHAR_BYTES = TERMCHAR.encode()


def worker():
    """Handle messages."""
    while True:
        conn, addr = q.get()

        with conn:
            # read incoming message
            buf = b""
            while True:
                buf += conn.recv(1)
                if buf.endswith(TERMCHAR_BYTES):
                    break

            msg = buf.decode().strip(TERMCHAR)
            msg_split = msg.split(" ")

            # handle message
            resp = ""
            if msg_split[0] == "plf":
                if len(msg_split) == 1:
                    resp = str(smu.plf)
                elif len(msg_split) == 2:
                    smu.plf = float(msg_split[1])
                else:
                    resp = "ERROR: invalid message."
            elif msg == "cpb":
                resp = str(smu.ch_per_board)
            elif msg == "rst":
                smu.reset()
            elif msg == "buf":
                resp = str(smu.maximum_buffer_size)
            elif msg == "chs":
                resp = str(smu.num_channels)
            elif msg == "bds":
                resp = str(smu.num_boards)
            elif msg == "sr":
                resp = str(smu.sample_rate)
            elif msg == "set":
                resp = str(smu.channel_settings)
            elif msg_split[0] == "nplc":
                if len(msg_split) == 1:
                    resp = str(smu.nplc)
                elif len(msg_split) == 2:
                    smu.nplc = float(msg_split[1])
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "sd":
                if len(msg_split) == 1:
                    resp = str(smu.settling_delay)
                elif len(msg_split) == 2:
                    smu.settling_delay = float(msg_split[1])
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "idn":
                if len(msg_split) == 1:
                    resp = "SMU"
                elif len(msg_split) == 2:
                    resp = smu.get_channel_id(msg_split[1])
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "cal":
                if len(msg_split) == 3:
                    if msg_split[1] == "ext":
                        if cal_data == {}:
                            resp = "ERROR: external calibration data not available."
                        elif int(msg_split[2]) == -1:
                            for ch, data in cal_data.items():
                                smu.use_external_calibration(ch, data)
                        else:
                            smu.use_external_calibration(
                                int(msg_split[2]), cal_data[int(msg_split[2])]
                            )
                    elif msg_split[1] == "int":
                        if int(msg_split[2]) == -1:
                            smu.use_internal_calibration(None)
                        else:
                            smu.use_internal_calibration(int(msg_split[2]))
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "ao":
                if len(msg_split) == 3:
                    if int(msg_split[2]) == -1:
                        smu.configure_channel_settings(
                            channel=None, auto_off=bool(msg_split[1])
                        )
                    else:
                        smu.configure_channel_settings(
                            channel=int(msg_split[2]), auto_off=bool(msg_split[1])
                        )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "fw":
                if len(msg_split) == 3:
                    if int(msg_split[2]) == -1:
                        smu.configure_channel_settings(
                            channel=None, four_wire=bool(msg_split[1])
                        )
                    else:
                        smu.configure_channel_settings(
                            channel=int(msg_split[2]), four_wire=bool(msg_split[1])
                        )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "vr":
                if len(msg_split) == 3:
                    if int(msg_split[2]) == -1:
                        smu.configure_channel_settings(
                            channel=None, v_range=float(msg_split[1])
                        )
                    else:
                        smu.configure_channel_settings(
                            channel=int(msg_split[2]), v_range=float(msg_split[1])
                        )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "def":
                if len(msg_split) == 3:
                    if int(msg_split[2]) == -1:
                        smu.configure_channel_settings(
                            channel=None, default=bool(msg_split[1])
                        )
                    else:
                        smu.configure_channel_settings(
                            channel=int(msg_split[2]), default=bool(msg_split[1])
                        )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "swe":
                if len(msg_split) == 6:
                    smu.configure_sweep(
                        float(msg_split[1]),
                        float(msg_split[2]),
                        int(msg_split[3]),
                        bool(msg_split[4]),
                        msg_split[5],
                    )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "lst":
                if len(msg_split) == 4:
                    smu.configure_list_sweep(
                        ast.literal_eval(msg_split[1]), bool(msg_split[2]), msg_split[3]
                    )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "dc":
                if len(msg_split) == 3:
                    smu.configure_dc(ast.literal_eval(msg_split[1]), msg_split[2])
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "meas":
                if len(msg_split) == 3:
                    smu.measure(msg_split[1], bool(msg_split[2]))
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "eo":
                if len(msg_split) == 3:
                    if int(msg_split[2]) == -1:
                        smu.enable_output(bool(msg_split[1]))
                    else:
                        smu.enable_output(bool(msg_split[1]), int(msg_split[2]))
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "led":
                if len(msg_split) == 5:
                    if int(msg_split[4]) == -1:
                        smu.set_leds(
                            bool(msg_split[1]),
                            bool(msg_split[2]),
                            bool(msg_split[3]),
                            None,
                        )
                    else:
                        smu.set_leds(
                            bool(msg_split[1]),
                            bool(msg_split[2]),
                            bool(msg_split[3]),
                            int(msg_split[4]),
                        )
                else:
                    resp = "ERROR: invalid message."
            else:
                resp = "ERROR: invalid message."

            # send response
            conn.sendall(resp.encode() + TERMCHAR_BYTES)

        q.task_done()


# load config file
try:
    config_path = pathlib.Path(os.environ["SMU_CONFIG_PATH"])
    with open(config_path, "r") as f:
        config = yaml.load(f, Loader=yaml.SafeLoader)
except KeyError:
    config = None
    warnings.warn(
        "Environment variable 'SMU_CONFIG_PATH' not set. Using default configuration."
    )
except FileNotFoundError:
    config = None
    warnings.warn(
        f"Could not find config file: {config_path}. Using default configuration."
    )

# read settings from config file
init_args = {}
if config is not None:
    try:
        serials = [v for k, v in sorted(config["board_mapping"].items())]
    except KeyError:
        serials = None
        warnings.warn("Board mapping not found. Using pysmu default mapping.")

    try:
        cal_data_folder = pathlib.Path(config["cal_data_folder"])
    except KeyError:
        cal_data_folder = None

    try:
        init_args["ch_per_board"] = config["ch_per_board"]
    except KeyError:
        warnings.warn(
            "Channels per board setting not found. Using default channels per board."
        )

    try:
        init_args["i_threshold"] = config["i_threshold"]
    except KeyError:
        warnings.warn(
            "Channels per board setting not found. Using default channels per board."
        )

    try:
        init_args["libsmu_mod"] = config["libsmu_mod"]
    except KeyError:
        warnings.warn(
            "Channels per board setting not found. Using default channels per board."
        )

# init smu object and connect boards
smu = m1k.smu(**init_args)
smu.connect(serials)

# load calibration data
if cal_data_folder is not None:
    cal_data = {}
    for board, serial in enumerate(smu.serials):
        # get list of cal files for given serial
        fs = [f for f in cal_data_folder.glob(f"cal_*_{serial}.yaml")]

        # pick latest one
        fs.reverse()
        cf = fs[0]

        # load cal data
        with open(cf, "r") as f:
            data = yaml.load(f, Loader=yaml.SafeLoader)

        # add data to cal dict
        if smu.ch_per_board == 1:
            cal_data[board] = data
        elif smu.ch_per_board == 2:
            cal_data[2 * board] = data
            cal_data[2 * board + 1] = data
else:
    cal_data = {}

# initialise a queue to hold incoming connections
q = queue.Queue()

# start worker thread to handle requests
threading.Thread(target=worker, daemon=True).start()

# start server
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind((HOST, PORT))
    s.listen()

    # add client connections to queue for worker
    while True:
        q.put_nowait(s.accept())
