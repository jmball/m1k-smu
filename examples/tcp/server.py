"""TCP server for SMU."""

import ast
import queue
import socket
import threading

import m1k

# get primary ip address
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(("10.255.255.255", 1))
ip = s.getsockname()[0]
s.close()

HOST = ip
PORT = 2101
TERMCHAR = "\n"


def worker():
    """Handle messages."""
    TERMCHAR_BYTES = TERMCHAR.encode()

    while True:
        conn, addr = q.get()

        with conn:

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
                # TODO: fix cal data mapping
                if len(msg_split) == 3:
                    if msg_split[1] == "ext":
                        if int(msg_split[2]) == -1:
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


# initialise a queue to hold incoming connections
q = queue.Queue()

# start worker thread
threading.Thread(target=worker, daemon=True).start()

# load channel serial mapping
# TODO: load serial mapping
serials = []

# connect to smu
smu = m1k.m1k()
smu.connect(serials)

# load calibration data
# TODO: load cal dict
cal_data = {}

# start server
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind((HOST, PORT))
    s.listen()

    # add client connections to queue for worker
    while True:
        q.put_nowait(s.accept())
