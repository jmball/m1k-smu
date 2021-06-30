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
import pprint
import traceback

fsadfdsa

sys.path.insert(1, str(pathlib.Path.cwd().parent.joinpath("src")))
import m1k.m1k as m1k

HOST = "0.0.0.0"  # server listens on all interfaces
PORT = 20101
TERMCHAR = "\n"
TERMCHAR_BYTES = TERMCHAR.encode()
COMMS_TIMEOUT = 10  # in seconds

pp = pprint.PrettyPrinter(indent=2)

# load config file
try:
    config_path = pathlib.Path(os.environ["SMU_CONFIG_PATH"])
    print(f"Config path: {config_path}")
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
        channel_mapping = config["channel_mapping"]
        for channel, info in channel_mapping.items():
            channel_mapping[channel]["serial"] = config["board_mapping"][info["board"]]
    except KeyError:
        channel_mapping = None
        warnings.warn("Channel mapping not found. Using pysmu default mapping.")

    try:
        cal_data_folder = pathlib.Path(config["cal_data_folder"])
    except KeyError:
        cal_data_folder = None

    try:
        idn = config["idn"]
    except KeyError:
        idn = "SMU"

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
else:
    channel_mapping = None
    cal_data_folder = None
    idn = "SMU"

print("Channel Mapping:")
pp.pprint(channel_mapping)


def stringify_nonnative_dict_values(d):
    """Convert non-native types in a dictionary to a string representation.

    Non-native types cannot be sent over TCP so require conversion.

    Assumes anything contained in a list is a native type.

    Parameters
    ----------
    d : dict
        Dictionary.

    Returns
    -------
    d : dict
        Formatted dictionary.
    """
    for key, value in d.items():
        if type(value) is dict:
            d[key] = stringify_nonnative_dict_values(value)
        elif type(value) not in [str, float, int, list, tuple, bool]:
            d[key] = str(value)
        else:
            d[key] = value

    return d


def worker(smu):
    """Handle messages.

    Parameters
    ----------
    smu : m1k.smu() object
        SMU object.
    """
    # load calibration data
    if cal_data_folder is not None:
        cal_data = {}
        for board, serial in enumerate(smu.serials):
            # get list of cal files for given serial
            fs = [f for f in cal_data_folder.glob(f"cal_*_{serial}.yaml")]

            # pick latest one
            fs.reverse()
            cf = fs[0]
            print(f"Loading calibration file: {cf}")

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

    # run infinite loop to handle messages
    while True:
        conn, addr = q.get()
        conn.settimeout(COMMS_TIMEOUT)

        with conn:
            # read incoming message
            with conn.makefile('r', newline=TERMCHAR) as cf:
                msg = cf.readline().rstrip(TERMCHAR)

            print(f"Message received: {msg}")
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
                resp = str(stringify_nonnative_dict_values(smu.channel_settings))
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
            elif msg == "eos":
                resp = str(smu.enabled_outputs)
            elif msg_split[0] == "idn":
                if len(msg_split) == 1:
                    resp = idn
                elif len(msg_split) == 2:
                    resp = smu.get_channel_id(int(msg_split[1]))
                else:
                    resp = "ERROR: invalid message."
            elif msg == "ovc":
                resp = str(smu.overcurrent)
            elif msg == "chm":
                resp = str(smu.channel_mapping)
            elif msg_split[0] == "inv":
                if len(msg_split) == 1:
                    resp = smu.channels_inverted
                elif len(msg_split) == 2:
                    smu.invert_channels(bool(int(msg_split[1])))
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "cal":
                if len(msg_split) == 3:
                    if msg_split[1] == "ext":
                        if cal_data == {}:
                            resp = "ERROR: external calibration data not available."
                        elif ast.literal_eval(msg_split[2]) is None:
                            for ch, data in cal_data.items():
                                smu.use_external_calibration(ch, data)
                        else:
                            smu.use_external_calibration(
                                int(msg_split[2]), cal_data[int(msg_split[2])]
                            )
                    elif msg_split[1] == "int":
                        smu.use_internal_calibration(ast.literal_eval(msg_split[2]))
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "fw":
                if len(msg_split) == 3:
                    smu.configure_channel_settings(
                        channel=ast.literal_eval(msg_split[2]),
                        four_wire=bool(int(msg_split[1])),
                    )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "vr":
                if len(msg_split) == 3:
                    smu.configure_channel_settings(
                        channel=ast.literal_eval(msg_split[2]),
                        v_range=float(msg_split[1]),
                    )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "def":
                if len(msg_split) == 3:
                    smu.configure_channel_settings(
                        channel=ast.literal_eval(msg_split[2]),
                        default=bool(int(msg_split[1])),
                    )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "swe":
                if len(msg_split) == 5:
                    smu.configure_sweep(
                        float(msg_split[1]),
                        float(msg_split[2]),
                        int(msg_split[3]),
                        msg_split[4],
                    )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "lst":
                if len(msg_split) == 3:
                    smu.configure_list_sweep(
                        ast.literal_eval(msg_split[1]),
                        msg_split[2],
                    )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "dc":
                if len(msg_split) == 3:
                    smu.configure_dc(ast.literal_eval(msg_split[1]), msg_split[2])
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "meas":
                if len(msg_split) == 4:
                    resp = str(
                        smu.measure(
                            ast.literal_eval(msg_split[1]),
                            msg_split[2],
                            bool(int(msg_split[3])),
                        )
                    )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "eo":
                if len(msg_split) == 3:
                    smu.enable_output(
                        bool(int(msg_split[1])), ast.literal_eval(msg_split[2])
                    )
                else:
                    resp = "ERROR: invalid message."
            elif msg_split[0] == "led":
                if len(msg_split) == 5:
                    smu.set_leds(
                        ast.literal_eval(msg_split[4]),
                        bool(int(msg_split[1])),
                        bool(int(msg_split[2])),
                        bool(int(msg_split[3])),
                    )
                else:
                    resp = "ERROR: invalid message."
            else:
                resp = "ERROR: invalid message."

            # send response
            conn.sendall(resp.encode() + TERMCHAR_BYTES)

        q.task_done()


# a global flag for keeping track if an exception has occured in the worker thread
worker_crashed = threading.Event()

def worker_thread_exception_handler(args):
    # set the flag indicating that the worker thread is toast
    # checking is_alive() on the thread is too slow to properly
    # react to the error in time to prevent another main loop cycle
    worker_crashed.set()

    # show the user what killed the worker thread
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)

    #raise(ValueError("The worker thread crashed! (see above for traceback)"))

threading.excepthook = worker_thread_exception_handler

# init smu
smu = m1k.smu(**init_args)
smu.connect(channel_mapping)

# initialise a queue to hold incoming connections
q = queue.Queue()

# setup worker thread to handle requests
worker_thread = threading.Thread(target=worker, args=(smu,), daemon=True)
worker_thread.start()  # start worker thread

# start server
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.settimeout(COMMS_TIMEOUT)
    s.bind((HOST, PORT))
    s.listen()

    print(f"SMU server started listening on {HOST}:{PORT}")

    # add client connections to queue for worker
    while worker_thread.is_alive() and not worker_crashed.is_set():
        try:
            (conn, address) = s.accept()
        except Exception as e:
            if isinstance(e, socket.timeout):
                # timeouts for s.accept() are cool,
                # that just means nobody sent us a message
                # during the timeout interval
                pass
            else:
                # non-timeout exceptions for accept() are not cool
                raise(e)
        else:  # there was no exception
            if worker_thread.is_alive() and not worker_crashed.is_set():
                # only deliver the connection to the worker if it is not dead or dying
                q.put_nowait((conn, address))

# rejoin the worker thread to the main one,
# but only if it crashed
if (not worker_thread.is_alive()) or (worker_crashed.is_set()):
    worker_thread.join()

# it's not possible to exit this program without an error
sys.exit(-1)
