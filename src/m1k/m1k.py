"""Source measure unit based on the ADALM1000."""

import math
import time
import warnings

import pysmu
import scipy.interpolate


class smu:
    """Source measure unit based on the ADALM1000.

    If multiple devices are connected, the object can be treated as a multi-channel
    SMU. Devices are grouped by pysmu into a `Session()` object. Only one session can
    run on the host computer at a time. Attempting to run multiple sessions will cause
    the program/s to crash. An smu object must therefore only be instantiated once in
    an application.

    Each ADALM1000 device has two channels internally, each with a third sense wire.
    This class can use the device in that mode but additionally provides the option to
    operate as a single SMU channel with a four-wire measurement mode. In this mode
    Channel A is the master. Channel B (BIN input) is used for voltage sensing on the
    GND side of the device under test.

    Each device can be configured for two quadrant operation with a 0-5 V range
    (channel A LO connected to ground), or for four quadrant operation with a
    -2.5 - +2.5 V range (channel A LO connected to the 2.5 V ouptut).

    Measurement operations can't be performed on specific individual channels one at
    a time, it's all or nothing. Output sweeps are always the same for all channels.
    However, different DC output values can be configured/measured for each channel.
    """

    def __init__(self, plf=50, ch_per_board=2):
        """Initialise object.

        Parameters
        ----------
        plf : float or int
            Power line frequency (Hz).
        ch_per_board : {1, 2}
            Number of channels to use per ADALM1000 board. If 1, channel A is assumed
            as the channel to use. This cannot be changed once the object has been
            instantiated.
        """
        self._plf = plf

        if ch_per_board in [1, 2]:
            self._ch_per_board = ch_per_board
        else:
            raise ValueError(
                f"Invalid number of channels per board: {ch_per_board}. Must be 1 or 2."
            )

        # private attribute to hold pysmu session
        self._session = None

        # private attribute to hold device serials
        self._serials = None

        # private attribute stating maximum buffer size of an ADALM1000
        self._maximum_buffer_size = 100000

        # Init private containers for settings, which get populated on device
        # connection. Call the settings property to read settings. Use configure
        # methods to set them.
        self._channel_settings = {}

        # private global settings, which require a session for initialisation
        # use test for `None` for initialisation in connect method
        self._nplc = None
        self._settling_delay = None
        self._nplc_samples = 0
        self._settling_delay_samples = 0
        self._samples_per_datum = 0

        # some functions allow retries if errors occur
        self._retries = 3

    def __enter__(self):
        """Enter the runtime context related to this object."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Exit the runtime context related to this object.

        Make sure everything gets cleaned up properly.
        """
        # disconnect all devices and destroy session
        self.disconnect()

    @property
    def plf(self):
        """Get power line frequency in Hz."""
        return self._plf

    @plf.setter
    def plf(self, plf):
        """Set the power line frequency in Hz.

        Also update NPLC integration samples, which depends on PLF.

        Parameters
        ----------
        plf : float or int
            Power line frequency in Hz.
        """
        self._plf = plf

        if self._nplc is not None:
            # convert nplc to integration time
            nplc_time = (1 / self._plf) * self.nplc

            self._nplc_samples = int(nplc_time * self.sample_rate)

            # update total samples for each data point
            self._samples_per_datum = self._nplc_samples + self._settling_delay_samples

    @property
    def ch_per_board(self):
        """Get the number of channels per board in use."""
        return self._ch_per_board

    @property
    def connected(self):
        """Get the connected state."""
        if self._session is None:
            return False
        else:
            return True

    @property
    def serials(self):
        """Get list of serials."""
        return self._serials

    @property
    def maximum_buffer_size(self):
        """Maximum number of samples in write/run/read buffers."""
        return self._maximum_buffer_size

    @property
    def num_channels(self):
        """Get the number of connected SMU channels."""
        if self.ch_per_board == 1:
            return self.num_boards
        elif self.ch_per_board == 2:
            return 2 * self.num_boards

    @property
    def num_boards(self):
        """Get the number of connected SMU boards."""
        return len(self._session.devices)

    @property
    def sample_rate(self):
        """Get the raw sample rate for each device."""
        return self._session.sample_rate

    @property
    def channel_settings(self):
        """Get settings dictionary."""
        return self._channel_settings

    @property
    def nplc(self):
        """Integration time in number of power line cycles."""
        return self._nplc

    @nplc.setter
    def nplc(self, nplc):
        """Set the integration time in number of power line cycles.

        Parameters
        ----------
        nplc : float
            Integration time in number of power line cycles (NPLC).
        """
        self._nplc = nplc

        # convert nplc to integration time
        nplc_time = (1 / self.plf) * nplc

        self._nplc_samples = int(nplc_time * self.sample_rate)

        # update total samples for each data point
        self._samples_per_datum = self._nplc_samples + self._settling_delay_samples

    @property
    def settling_delay(self):
        """Settling delay in seconds."""
        return self._settling_delay

    @settling_delay.setter
    def settling_delay(self, settling_delay):
        """Set the settling delay in seconds.

        Parameters
        ----------
        settling_delay : float
            Settling delay (s).
        """
        self._settling_delay = settling_delay

        self._settling_delay_samples = int(settling_delay * self.sample_rate)

        # update total samples for each data point
        self._samples_per_datum = self._nplc_samples + self._settling_delay_samples

    def connect(self, serials=None):
        """Connect one or more devices (channels) to the session (SMU).

        WARNING: this method cannot be called again if a session already exists. To
        make a new connection run `disconnect()` first to destroy the current session.

        Parameters
        ----------
        serials : str, list, or None
            List of device serial numbers to add to the session. The order of the
            serials in the list determines their channel number. The list index will be
            the channel index if `ch_per_board` is 1. Otherwise two channel indices
            will be added per list index, given as `2 * list index` and
            `2 * list index + 1`. If `None`, connect all available devices, assigning
            channel indices in the order determined by pysmu.
        """
        if self._session is None:
            # the session wasn't provided and no session already exists so create one
            self._session = pysmu.Session(add_all=False)
            self._session.scan()
        else:
            raise RuntimeError("Cannot connect more devices to the existing session.")

        if serials is None:
            serials = [dev.serial for dev in self._session.available_devices]
        elif type(serials) is str:
            serials = [serials]
        elif type(serials) is not list:
            raise ValueError(
                f"Invalid type for serials: {type(serials)}. Must be `str`, `list`, or "
                + "`None`."
            )

        self._serials = serials

        for serial in serials:
            self._connect_board(serial)

        # reset to default state
        self.reset()

    def _connect_board(self, serial):
        """Connect a device to the session and configure it with default settings.

        Parameters
        ----------
        serial : str
            Device serial number.
        """
        # see if device is available to be added to the session
        new_dev = None
        for dev in self._session.available_devices:
            if dev.serial == serial:
                new_dev = dev
                break

        if new_dev is None:
            raise ValueError(f"Device not found with serial: {serial}")

        # make sure it hasn't already been added
        for ix, dev in enumerate(self._session.devices):
            if dev.serial == serial:
                warnings.warn(
                    f"Device has already been added to session with serial: {serial}. "
                    + f"It is channel number: {ix}"
                )
                return

        # it looks like a new device so add it
        self._session.add(new_dev)

    def reset(self):
        """Reset all channels to the default state.

        This function will attempt retries if `pysmu.DeviceError`'s occur when setting
        channel B's for four-wire mode when there's only 1 channel per board.
        """
        # reset channel and measurement params
        self._channel_settings = {}
        self._nplc_samples = 0
        self._settling_delay_samples = 0
        self._samples_per_datum = 0

        # get board mapping
        self._map_boards()

        # set outputs
        for ch in range(self.num_channels):
            dev_ix = self._channel_settings[ch]["dev_ix"]
            # disable output (should already be disabled but just to make sure)
            self.enable_output(False, ch)

            if self.ch_per_board == 1:
                # if 1 channel per board, channel B is only used for voltage
                # measurement in four wire mode
                # allow retries
                err = None
                for attempt in range(1, self._retries + 1):
                    try:
                        self._session.devices[dev_ix].channels[
                            "B"
                        ].mode = pysmu.Mode.HI_Z_SPLIT
                        break
                    except pysmu.DeviceError as e:
                        if attempt == self._retries:
                            err = e
                        else:
                            warnings.warn(
                                "`pysmu.DeviceError` occurred setting channel B for "
                                + "four-wire mode, attempting to reconnect and retry."
                            )
                            self._reconnect()
                            continue

                if err is not None:
                    raise err

        # ---the order of actions below is critical---

        # set default output value
        # this will reset all channel outputs to 0 V
        self.configure_dc(values=0, source_mode="v")

        # init global settings
        # depends on session being created and device being connected and a
        # measurement having been performed to properly init sample rate
        self.nplc = 0.1
        self.settling_delay = 0.005

    def _map_boards(self):
        """Map boards to channels in channel settings."""
        # make a list of serials corresponding to every SMU channel, i.e. if using
        # 2 channels per board, 2 channels will share the same serial
        ch_serials = []
        for serial in self._serials:
            if self.ch_per_board == 1:
                ch_serials += [serial]
            elif self.ch_per_board == 2:
                ch_serials += [serial, serial]

        # find device index for each channel and init channel settings
        for ch, serial in enumerate(ch_serials):
            dev_ix = None
            for ix, dev in enumerate(self._session.devices):
                if dev.serial == serial:
                    dev_ix = ix
                    break

            # init new device with default settings
            self._configure_channel_default_settings(ch)

            # store mapping between channel and device index in session
            self._channel_settings[ch]["dev_ix"] = dev_ix
            self._channel_settings[ch]["serial"] = serial

            # store individual device channel
            if self.ch_per_board == 1:
                self.channel_settings[ch]["dev_channel"] = "A"
            elif self.ch_per_board == 2:
                if ch % 2 == 0:
                    self.channel_settings[ch]["dev_channel"] = "A"
                else:
                    self.channel_settings[ch]["dev_channel"] = "B"

    def _reconnect(self):
        """Attempt to reconnect boards if one or more gets unexpectedly dropped."""
        input("Attempting reconnect. Press Enter to continue...")

        # remove all devices from the session
        for dev in self._session.devices:
            try:
                self._session.remove(dev)
            except pysmu.SessionError:
                self._session.remove(dev, True)

        # destroy the session
        del self._session
        self._session = None

        # create a new one
        self._session = pysmu.Session(add_all=False)

        # scan for available devices, one or more has probably changed adress
        self._session.scan()

        # add devices to session again
        for serial in self._serials:
            self._connect_board(serial)

        # update board mapping
        self._map_boards()

    def disconnect(self):
        """Disconnect all devices from the session.

        Disconnecting individual devices would change the remaining channel's indices
        so is forbidden.
        """
        # disable outputs and reset LEDs
        self.enable_output(False)
        self.set_leds(R=True)

        # remove devices from session
        for dev in self._session.devices:
            try:
                self._session.remove(dev)
            except pysmu.SessionError:
                self._session.remove(dev, True)

        # reset channel settings
        self._channel_settings = {}

        # destroy the session
        del self._session
        self._session = None

    def use_external_calibration(self, channel, data=None):
        """Store measurement data used to calibrate a channel externally to the device.

        This function uses interpolation of measurement data to apply a calibration
        to data returned from a device. It does not affect the internal calibration
        used by the device itself to return data.

        Parameters
        ----------
        channel : int
            Channel number (0-indexed).
        data : dict or None
            Calibration data dictionary. The dictionary must be of the form:

            {
                "A": {
                    "meas_v": [data],
                    "meas_i": [data],
                    "source_v": [data],
                    "source_i": [data]
                },
                "B": {
                    "meas_v": [data],
                    "meas_i": [data],
                    "source_v": [data],
                    "source_i": [data]
                }
            }

            where the keys "A" and "B" refer to device channels and [data] values are
            lists of lists of measurement data. For "meas_[x]" keys the format of
            the sub-lists is [dmm_meas, m1k_meas], for "source_[x]" keys the format of
            the sub-lists is [set, m1k_meas, dmm_meas].

            If `None`, use calibration data already provided.
        """
        if data is None:
            if self._channel_settings[channel]["external_calibration"] != {}:
                self._channel_settings[channel]["calibration_mode"] = "external"
                return
            else:
                raise ValueError(
                    f"No external calibration data available for channel: {channel}."
                )

        # interpolate calibration data for each measurement type for each device
        # sub-channel
        external_cal = {}
        for sub_ch, data_dict in data.items():
            external_cal[sub_ch] = {}
            for meas, data in data_dict.items():
                if (meas.startswith("meas") is True) and (data is not None):
                    x = [row[1] for row in data]
                    y = [row[0] for row in data]
                    # linearly interpolate data with linear extrapolation for data
                    # outside measured range
                    f_int = scipy.interpolate.interp1d(
                        x,
                        y,
                        kind="linear",
                        bounds_error=False,
                        fill_value="extrapolate",
                    )
                    external_cal[sub_ch][meas] = f_int
                elif (meas.startswith("source") is True) and (data is not None):
                    x = [row[1] for row in data]
                    y = [row[2] for row in data]
                    z = [row[0] for row in data]
                    # interpolation for returned values from device
                    f_int_meas = scipy.interpolate.interp1d(
                        x,
                        y,
                        kind="linear",
                        bounds_error=False,
                        fill_value="extrapolate",
                    )
                    # interpolation for setting the device output
                    f_int_set = scipy.interpolate.interp1d(
                        y,
                        z,
                        kind="linear",
                        bounds_error=False,
                        fill_value="extrapolate",
                    )
                    external_cal[sub_ch][meas] = {}
                    external_cal[sub_ch][meas]["meas"] = f_int_meas
                    external_cal[sub_ch][meas]["set"] = f_int_set
                elif data is None:
                    pass
                else:
                    raise ValueError(
                        f"Invalid calibration key: {meas}. Must be 'meas_v', 'meas_i',"
                        + " 'source_v', or 'source_i'."
                    )

        self._channel_settings[channel]["calibration_mode"] = "external"
        self._channel_settings[channel]["external_calibration"] = external_cal

    def use_internal_calibration(self, channel=None):
        """Use the device's internal calibration.

        Parameters
        ----------
        channel : int or `None`
            Channel number (0-indexed). If `None` apply to all channels.
        """
        if channel is None:
            channels = range(self.num_channels)
        else:
            channels = [channel]

        for channel in channels:
            self._channel_settings[channel]["calibration_mode"] = "internal"

    def configure_channel_settings(
        self,
        channel=None,
        auto_off=None,
        four_wire=None,
        v_range=None,
        default=False,
    ):
        """Configure channel.

        Parameters
        ----------
        channel : int
            Channel number (0-indexed). If `None`, apply settings to all channels.
        auto_off : bool
            Automatically set output to high impedance mode after a measurement.
        four_wire : bool
            Four wire enabled.
        v_range : {2.5, 5}
            Voltage range. If 5, channel can output 0-5 V (two quadrant). If 2.5
            channel can output -2.5 - +2.5 V (four quadrant).
        default : bool
            Reset all settings to default.
        """
        if channel is None:
            channels = range(self.num_channels)
        else:
            channels = [channel]

        for ch in channels:
            if default is True:
                self._configure_channel_default_settings(ch)
                self.enable_output(False, ch)
            else:
                if auto_off is not None:
                    self._channel_settings[ch]["auto_off"] = auto_off

                if four_wire is not None:
                    self._channel_settings[ch]["four_wire"] = four_wire

                if v_range is not None:
                    if v_range in [2.5, 5]:
                        self._channel_settings[ch]["v_range"] = v_range
                    else:
                        raise ValueError(
                            f"Invalid voltage range setting: {v_range}. Must be 2.5 or"
                            + " 5."
                        )

    def _configure_channel_default_settings(self, channel):
        """Configure a channel with the default settings.

        Parameters
        ----------
        channel : int
            Channel number (0-indexed).
        """
        if self.ch_per_board == 1:
            default_four_wire = True
        elif self.ch_per_board == 2:
            default_four_wire = False

        self._channel_settings[channel] = {
            "serial": None,
            "dev_ix": None,
            "dev_channel": None,
            "auto_off": False,
            "four_wire": default_four_wire,
            "v_range": 5,
            "source_mode": "v",
            "sweep_mode": "v",
            "dc_values": [],
            "sweep_values": [],
            "dual_sweep": False,
            "calibration_mode": "internal",
            "external_calibration": {},
        }

    def configure_sweep(self, start, stop, points, dual=False, source_mode="v"):
        """Configure an output sweep for all channels.

        Parameters
        ----------
        start : float
            Starting value in V or A.
        stop : float
            Stop value in V or A.
        points : int
            Number of points in the sweep.
        dual : bool
            If `True`, append the reverse sweep as well.
        source_mode : str
            Desired source mode: "v" for voltage, "i" for current.
        """
        if source_mode not in ["v", "i"]:
            raise ValueError(
                f"Invalid source mode: {source_mode}. Must be 'v' (voltage) or 'i' "
                + "(current)."
            )

        for ch in range(self.num_channels):
            self._channel_settings[ch]["sweep_mode"] = source_mode

            if source_mode == "v":
                if self._channel_settings[ch]["v_range"] == 2.5:
                    # channel LO connected to 2.5 V
                    start += 2.5
                    stop += 2.5

            step = (stop - start) / (points - 1)
            values = [x * step + start for x in range(points)]

            # update set values according to external calibration
            if self._channel_settings[ch]["calibration_mode"] == "external":
                dev_channel = self._channel_settings[ch]["dev_channel"]
                cal = self._channel_settings[ch]["external_calibration"][dev_channel]
                f_int = cal[f"source_{source_mode}"]["set"]
                values = f_int(values).tolist()

            self._channel_settings[ch]["sweep_values"] = values
            self._channel_settings[ch]["dual_sweep"] = dual

    def configure_list_sweep(self, values=[], dual=False, source_mode="v"):
        """Configure list sweeps for all channels.

        All lists must be the same length.

        Parameters
        ----------
        values : list of lists
            Lists of values for source sweeps, one sub-list for each channel. The
            outer list index is the channel index, e.g. passing
            `[[0, 1, 2], [0, 1, 2]]` will sweep both channels 0 and 1 with values of
            `[0, 1, 2]`. All sub-lists must be the same length.
        dual : bool
            If `True`, append the reverse sweep as well.
        source_mode : str
            Desired source mode during measurement: "v" for voltage, "i" for current.
        """
        if source_mode not in ["v", "i"]:
            raise ValueError(
                f"Invalid source mode: {source_mode}. Must be 'v' (voltage) or 'i' "
                + "(current)."
            )

        if len(values) != self.num_channels:
            raise ValueError(
                f"Invalid values list length: {len(values)}. The length of the values "
                + f"list must match the number of channels: {self.num_channels}."
            )

        # make sure all sub-lists have equal legnth
        unique_sublist_lengths = set([len(sublist) for sublist in values])
        if len(unique_sublist_lengths) != 1:
            raise ValueError(
                "All sub-lists in `values` must be the same length. `values` contains "
                + f"sub-lists with lengths: {unique_sublist_lengths}."
            )

        for ch in range(self.num_channels):
            self._channel_settings[ch]["sweep_mode"] = source_mode

            offset = 0
            if source_mode == "v":
                if self._channel_settings[ch]["v_range"] == 2.5:
                    # channel LO connected to 2.5 V
                    offset = 2.5

            sweep = [x + offset for x in values[ch]]

            # update set values according to external calibration
            if self._channel_settings[ch]["calibration_mode"] == "external":
                dev_channel = self._channel_settings[ch]["dev_channel"]
                cal = self._channel_settings[ch]["external_calibration"][dev_channel]
                f_int = cal[f"source_{source_mode}"]["set"]
                sweep = f_int(sweep).tolist()

            self._channel_settings[ch]["sweep_values"] = sweep
            self._channel_settings[ch]["dual_sweep"] = dual

    def configure_dc(self, values=[], source_mode="v"):
        """Configure a DC output measurement for all channels.

        Parameters
        ----------
        values : list of float or int; float or int
            Desired output values in V or A depending on source mode. The list indeices
            match the channel numbers. If a numeric value is given it is applied to all
            channels.
        source_mode : str
            Desired source mode during measurement: "v" for voltage, "i" for current.
        """
        # validate/format values input
        num_channels = self.num_channels
        t = type(values)
        if t == list:
            if len(values) != num_channels:
                raise ValueError(
                    "All channel values must be set simulateneously. The are "
                    + f"{self.num_channels} channels connected but {len(values)} "
                    + "values were given."
                )
        elif (t == float) or (t == int):
            values = [values] * num_channels
        else:
            raise ValueError(
                f"Invalid type for values: {t}. Must be `list`, `float`, or `int`."
            )

        if source_mode not in ["v", "i"]:
            raise ValueError(
                f"Invalid source mode: {source_mode}. Must be 'v' (voltage) or 'i' "
                + "(current)."
            )

        # setup channel settings for a dc measurement
        for ch, value in enumerate(values):
            self._channel_settings[ch]["source_mode"] = source_mode

            if source_mode == "v":
                if self._channel_settings[ch]["v_range"] == 2.5:
                    # channel LO connected to 2.5 V
                    value += 2.5

            # update set value according to external calibration
            if self._channel_settings[ch]["calibration_mode"] == "external":
                dev_channel = self._channel_settings[ch]["dev_channel"]
                cal = self._channel_settings[ch]["external_calibration"][dev_channel]
                f_int = cal[f"source_{source_mode}"]["set"]
                value = float(f_int(value))

            self._channel_settings[ch]["dc_values"] = [value]

        # write values for all channels
        start_modes = []
        for ch in range(self.num_channels):
            dev_ix = self._channel_settings[ch]["dev_ix"]
            dev_channel = self._channel_settings[ch]["dev_channel"]
            # get current mode to determine whether output needs to be re-enabled
            start_modes.append(self._session.devices[dev_ix].channels[dev_channel].mode)

            values = self._channel_settings[ch]["dc_values"]

            # write new value to the channel
            # self._session.devices[dev_ix].flush(channel=0, read=True)
            self._session.devices[dev_ix].channels[dev_channel].write(values)

        # enable outputs prior to run-read as required to update the device value
        # doing this after the write loop minimises the time the outputs are enabled
        # before the run, which triggers the change in outputs
        self.enable_output(True)

        # run and read one sample for all channels to update output values
        self._session.run(1)
        self._session.read(1)

        # getting a sample automatically turns off the outputs so turn them back
        # on again in the correct mode if they were already on
        for ch, start_mode in enumerate(start_modes):
            if start_mode not in [pysmu.Mode.HI_Z, pysmu.Mode.HI_Z_SPLIT]:
                self.enable_output(True, ch)
            else:
                # although output turns off after measurement run, it doesn't
                # re-set the channel mode in the library to HI_Z so force it manually
                # here
                self.enable_output(False, ch)

    def measure(self, measurement="dc", allow_chunking=False):
        """Perform the configured sweep or dc measurements for all channels.

        This function will attempt retries if `pysmu.SessionError` and/or
        `pysmu.DeviceError`'s occur.

        Parameters
        ----------
        measurement : {"dc", "sweep"}
            Measurement to perform based on stored settings from configure_sweep
            ("sweep") or configure_dc ("dc", default) method calls.
        allow_chunking : bool
            Allow (`True`) or disallow (`False`) measurement chunking. If a requested
            measurement requires a number of samples that exceeds the size of the
            device buffer this flag will determine whether it gets broken up into
            smaller measurement chunks. If set to `False` and the measurement exceeds
            the buffer size this function will raise a ValueError.

        Returns
        -------
        data : dict
            Data dictionary of the form:
            {channel: {"raw": raw_data, "processed": processed_data}}.
        """
        if measurement not in ["dc", "sweep"]:
            raise ValueError(
                f"Invalid measurement mode: {measurement}. Must be 'dc' or 'sweep'."
            )

        err = None
        for attempt in range(1, self._retries + 1):
            try:
                raw_data, t0 = self._measure(measurement, allow_chunking)
                break
            except pysmu.SessionError as e:
                if attempt == self._retries:
                    err = e
                else:
                    warnings.warn(
                        "`pysmu.SessionError` occurred during `measure()`, attempting "
                        + "to reconnect and retry."
                    )
                    self._reconnect()
                    continue
            except pysmu.DeviceError as e:
                if attempt == self._retries:
                    err = e
                else:
                    warnings.warn(
                        "`pysmu.DeviceError` occurred during `measure()`, attempting "
                        + "to reconnect and retry."
                    )
                    self._reconnect()
                    continue

        if err is not None:
            raise err

        # re-format raw data to: (voltage, current, timestamp, status)
        # and process to account for nplc and settling delay if required
        processed_data = self._process_data(raw_data, t0)

        # return processed_data
        return processed_data

    def _measure(self, measurement, allow_chunking):
        """Perform a DC or sweep measurement.

        Parameters
        ----------
        measurement : {"dc", "sweep"}
            Measurement to perform based on stored settings from configure_sweep
            ("sweep") or configure_dc ("dc", default) method calls.
        allow_chunking : bool
            Allow (`True`) or disallow (`False`) measurement chunking. If a requested
            measurement requires a number of samples that exceeds the size of the
            device buffer this flag will determine whether it gets broken up into
            smaller measurement chunks. If set to `False` and the measurement exceeds
            the buffer size this function will raise a ValueError.

        Returns
        -------
        raw_data : dict
            Raw data dictionary.
        t0 : float
            Reading start time in s.
        """
        # get interable of channels now to save repeated lookups later
        channels = range(self.num_channels)

        # get current mode to determine whether output needs to be re-enabled
        start_modes = []
        for ch in channels:
            dev_ix = self._channel_settings[ch]["dev_ix"]
            dev_channel = self._channel_settings[ch]["dev_channel"]
            start_modes.append(self._session.devices[dev_ix].channels[dev_channel].mode)

        # build samples list accounting for nplc and settling delay
        ch_samples = {}
        for ch in channels:
            values = self._channel_settings[ch][f"{measurement}_values"]
            samples = []
            for value in values:
                samples += [value] * self._samples_per_datum
            ch_samples[ch] = samples

        # look up requested number of samples. All channels must be the same so just
        # read from the first channel
        num_samples_requested = len(ch_samples[0])

        # decide whether the request is allowed
        if num_samples_requested > self._maximum_buffer_size:
            if allow_chunking is False:
                raise ValueError(
                    "The requested measurement cannot fit in the device buffer. "
                    + "Consider reducing the number of measurement points, NPLC, or "
                    + "settling delay."
                )
            else:
                warnings.warn(
                    "The requested measurement cannot fit in the device buffer and "
                    + "will be broken into chunks. Consider reducing the number of "
                    + "measurement points, NPLC, or settling delay if this is a "
                    + "problem."
                )

        # convert requested samples to chunks of samples that fit in the buffers
        data_per_chunk = int(
            math.floor(self._maximum_buffer_size / self._samples_per_datum)
        )
        if num_samples_requested <= self._maximum_buffer_size:
            samples_per_chunk = num_samples_requested
        else:
            samples_per_chunk = data_per_chunk * self._samples_per_datum
        num_chunks = int(math.ceil(num_samples_requested / samples_per_chunk))

        # turn on output leds to indicate output on
        for ch in channels:
            self.set_leds(channel=ch, G=True, B=True)

        # update source mode if sweep measurement
        if measurement == "sweep":
            for ch in channels:
                sweep_mode = self._channel_settings[ch]["sweep_mode"]
                self._channel_settings[ch]["source_mode"] = sweep_mode

        # determine how many scans to perform, i.e. is this a dual sweep?
        num_scans = 1
        if measurement == "sweep":
            # all channels have the same dual sweep setting so just look up the 1st
            if self._channel_settings[0]["dual_sweep"] is True:
                num_scans = 2

        # init data container
        # TODO: make more accurate sample timer
        t0 = time.time()
        raw_data = []
        for scan in range(num_scans):
            # iterate over chunks of data that fit into the buffer
            for i in range(num_chunks):
                # write chunks to devices
                self._session.flush()
                for ch in channels:
                    dev_ix = self._channel_settings[ch]["dev_ix"]
                    dev_channel = self._channel_settings[ch]["dev_channel"]
                    samples = ch_samples[ch]
                    if scan == 1:
                        # this is the second scan of a dual sweep so reverse sample list
                        samples.reverse()
                    chunk = samples[i * samples_per_chunk : (i + 1) * samples_per_chunk]
                    self._session.devices[dev_ix].channels[dev_channel].write(chunk)

                # enable outputs
                for ch in channels:
                    dev_ix = self._channel_settings[ch]["dev_ix"]
                    dev_channel = self._channel_settings[ch]["dev_channel"]
                    # determine if request is for special case of open-circuit voltage
                    # measurement requiring HI_Z mode rather than SIMV
                    if (
                        (measurement == "dc")
                        and (self._channel_settings[ch]["source_mode"] == "i")
                        and (chunk[0] == 0)
                    ):
                        if self._channel_settings[ch]["four_wire"] is True:
                            mode = pysmu.Mode.HI_Z_SPLIT
                        else:
                            mode = pysmu.Mode.HI_Z

                        self._session.devices[dev_ix].channels[dev_channel].mode = mode
                    else:
                        # not a special case so just enable output as normal
                        self.enable_output(True, ch)

                # run scans
                self._session.run(len(chunk))

                # read the data chunk and add to raw data container
                raw_data.append(self._session.read(len(chunk), 20000))

        # re-enable outputs if required
        for ch, start_mode in enumerate(start_modes):
            if self._channel_settings[ch]["auto_off"] is False:
                if start_mode not in [pysmu.Mode.HI_Z, pysmu.Mode.HI_Z_SPLIT]:
                    self.enable_output(True, ch)
                else:
                    # although output turns off after measurement run, it doesn't
                    # re-set the channel mode in the library to HI_Z so force it manually
                    # here
                    self.enable_output(False, ch)
            else:
                # turn off output leds and re-set mode
                self.enable_output(False, ch)

        return raw_data, t0

    def _process_data(self, raw_data, t0):
        """Process raw data accounting for NPLC and settling delay.

        Parameters
        ----------
        raw_data : dict
            Raw data dictionary.
        t0 : float
            Timestamp representing start time (s).

        Returns
        -------
        processed_data : list of tuple
            List of processed data tuples. Tuple structure is: (voltage, current,
            timestamp, status).
        """
        t_delta = 1 / self.sample_rate

        # init processed data container
        processed_data = {}
        for ch in range(self.num_channels):
            processed_data[ch] = []

        cumulative_chunk_lengths = 0
        for chunk in raw_data:
            if self.ch_per_board == 1:
                for ch in range(self.num_channels):
                    # start indices for each measurement value
                    start_ixs = range(0, len(chunk[ch]), self._samples_per_datum)

                    A_voltages = []
                    B_voltages = []
                    currents = []
                    timestamps = []
                    for i in start_ixs:
                        # final point can overlap with start of next voltage so cut it
                        data_slice = chunk[ch][i : i + self._samples_per_datum - 1]
                        # discard settling delay data
                        data_slice = data_slice[self._settling_delay_samples :]

                        # approximate datum timestamp, doesn't account for chunking
                        timestamps.append(
                            t0
                            + (cumulative_chunk_lengths + i)
                            * t_delta
                            * self._samples_per_datum
                        )

                        # pick out and process useful data
                        A_point_voltages = []
                        B_point_voltages = []
                        point_currents = []
                        for row in data_slice:
                            A_point_voltages.append(row[0][0])
                            B_point_voltages.append(row[1][0])
                            point_currents.append(row[0][1])

                        A_voltages.append(sum(A_point_voltages) / len(A_point_voltages))
                        B_voltages.append(sum(B_point_voltages) / len(B_point_voltages))
                        currents.append(sum(point_currents) / len(point_currents))

                    # update measured values according to external calibration
                    if self._channel_settings[ch]["calibration_mode"] == "external":
                        A_cal = self._channel_settings[ch]["external_calibration"]["A"]

                        source_mode = self._channel_settings[ch]["source_mode"]
                        if source_mode == "v":
                            f_int_mva = A_cal["source_v"]["meas"]
                            f_int_mia = A_cal["meas_i"]
                        else:
                            f_int_mva = A_cal["meas_v"]
                            f_int_mia = A_cal["source_i"]["meas"]

                        A_voltages = f_int_mva(A_voltages)
                        currents = f_int_mia(currents).tolist()

                        if self._channel_settings[ch]["four_wire"] is True:
                            B_cal = self._channel_settings[ch]["external_calibration"][
                                "B"
                            ]
                            f_int_mvb = B_cal["meas_v"]
                            B_voltages = f_int_mvb(B_voltages)
                            voltages = A_voltages - B_voltages
                        else:
                            voltages = A_voltages

                        voltages = voltages.tolist()
                    else:
                        if self._channel_settings[ch]["four_wire"] is True:
                            voltages = [
                                av - bv for av, bv in zip(A_voltages, B_voltages)
                            ]
                        else:
                            voltages = A_voltages

                    processed_data[ch].extend(
                        [
                            (v, i, t, 0)
                            for v, i, t in zip(voltages, currents, timestamps)
                        ]
                    )
            elif self.ch_per_board == 2:
                for board in range(self.num_boards):
                    # start indices for each measurement value
                    start_ixs = range(0, len(chunk[board]), self._samples_per_datum)

                    A_voltages = []
                    B_voltages = []
                    A_currents = []
                    B_currents = []
                    timestamps = []
                    for i in start_ixs:
                        # final point can overlap with start of next voltage so cut it
                        data_slice = chunk[board][i : i + self._samples_per_datum - 1]
                        # discard settling delay data
                        data_slice = data_slice[self._settling_delay_samples :]

                        # approximate datum timestamp, doesn't account for chunking
                        timestamps.append(
                            t0
                            + (cumulative_chunk_lengths + i)
                            * t_delta
                            * self._samples_per_datum
                        )

                        # pick out and process useful data
                        A_point_voltages = []
                        B_point_voltages = []
                        A_point_currents = []
                        B_point_currents = []
                        for row in data_slice:
                            A_point_voltages.append(row[0][0])
                            B_point_voltages.append(row[1][0])
                            A_point_currents.append(row[0][1])
                            B_point_currents.append(row[1][1])

                        A_voltages.append(sum(A_point_voltages) / len(A_point_voltages))
                        B_voltages.append(sum(B_point_voltages) / len(B_point_voltages))
                        A_currents.append(sum(A_point_currents) / len(A_point_currents))
                        B_currents.append(sum(B_point_currents) / len(B_point_currents))

                    # update measured values according to external calibration
                    if (
                        self._channel_settings[2 * board]["calibration_mode"]
                        == "external"
                    ):
                        A_cal = self._channel_settings[2 * board][
                            "external_calibration"
                        ]["A"]

                        source_mode = self._channel_settings[2 * board]["source_mode"]
                        if source_mode == "v":
                            f_int_mva = A_cal["source_v"]["meas"]
                            f_int_mia = A_cal["meas_i"]
                        else:
                            f_int_mva = A_cal["meas_v"]
                            f_int_mia = A_cal["source_i"]["meas"]

                        A_voltages = f_int_mva(A_voltages).tolist()
                        A_currents = f_int_mia(A_currents).tolist()

                    if (
                        self._channel_settings[2 * board + 1]["calibration_mode"]
                        == "external"
                    ):
                        B_cal = self._channel_settings[2 * board + 1][
                            "external_calibration"
                        ]["B"]

                        source_mode = self._channel_settings[2 * board + 1][
                            "source_mode"
                        ]
                        if source_mode == "v":
                            f_int_mvb = B_cal["source_v"]["meas"]
                            f_int_mib = B_cal["meas_i"]
                        else:
                            f_int_mvb = B_cal["meas_v"]
                            f_int_mib = B_cal["source_i"]["meas"]

                        B_voltages = f_int_mvb(B_voltages).tolist()
                        B_currents = f_int_mib(B_currents).tolist()

                    processed_data[2 * board].extend(
                        [
                            (v, i, t, 0)
                            for v, i, t in zip(A_voltages, A_currents, timestamps)
                        ]
                    )
                    processed_data[2 * board + 1].extend(
                        [
                            (v, i, t, 0)
                            for v, i, t in zip(B_voltages, B_currents, timestamps)
                        ]
                    )

            cumulative_chunk_lengths += len(chunk)

        return processed_data

    def enable_output(self, enable, channel=None):
        """Enable/disable channel outputs.

        This function will attempt retries if `pysmu.DeviceError`'s occur.

        Paramters
        ---------
        enable : bool
            Turn on (`True`) or turn off (`False`) channel outputs.
        channel : int or None
            Channel number (0-indexed). If `None`, apply to all channels.
        """
        err = None
        for attempt in range(1, self._retries + 1):
            try:
                self._enable_output(enable, channel)
                break
            except pysmu.DeviceError as e:
                if attempt == self._retries:
                    err = e
                else:
                    warnings.warn(
                        "`pysmu.DeviceError` occurred during `enable_output()`, "
                        + "attempting to reconnect and retry."
                    )
                    self._reconnect()
                    continue

        if err is not None:
            raise err

    def _enable_output(self, enable, channel=None):
        """Enable/disable channel outputs.

        This function will attempt retries if `pysmu.DeviceError`'s occur.

        Paramters
        ---------
        enable : bool
            Turn on (`True`) or turn off (`False`) channel outputs.
        channel : int or None
            Channel number (0-indexed). If `None`, apply to all channels.
        """
        if channel is None:
            channels = range(self.num_channels)
        else:
            channels = [channel]

        for ch in channels:
            dev_ix = self._channel_settings[ch]["dev_ix"]
            dev_channel = self._channel_settings[ch]["dev_channel"]
            if enable is True:
                if self._channel_settings[ch]["four_wire"] is True:
                    if self._channel_settings[ch]["source_mode"] == "v":
                        mode = pysmu.Mode.SVMI_SPLIT
                    else:
                        mode = pysmu.Mode.SIMV_SPLIT
                else:
                    if self._channel_settings[ch]["source_mode"] == "v":
                        mode = pysmu.Mode.SVMI
                    else:
                        mode = pysmu.Mode.SIMV
                self.set_leds(channel=ch, G=True, B=True)
            else:
                if self._channel_settings[ch]["four_wire"] is True:
                    mode = pysmu.Mode.HI_Z_SPLIT
                else:
                    mode = pysmu.Mode.HI_Z

                # if both channels on a board are accessible, only turn off the blue
                # LED if both channels are off
                if self.ch_per_board == 1:
                    self.set_leds(channel=ch, G=True)
                elif self.ch_per_board == 2:
                    if dev_channel == "A":
                        other_channel_mode = (
                            self._session.devices[dev_ix].channels["B"].mode
                        )
                    else:
                        other_channel_mode = (
                            self._session.devices[dev_ix].channels["A"].mode
                        )

                    if other_channel_mode in [
                        pysmu.Mode.HI_Z,
                        pysmu.Mode.HI_Z_SPLIT,
                    ]:
                        # the other channel is off so ok to turn off blue LED
                        self.set_leds(channel=ch, G=True)

            self._session.devices[dev_ix].channels[dev_channel].mode = mode

    def get_channel_id(self, channel):
        """Get the serial number of requested channel.

        Parameters
        ----------
        channel : int
            Channel number (0-indexed).

        Returns
        -------
        channel_serial : str
            Channel serial string.
        """
        dev_ix = self._channel_settings[channel]["dev_ix"]
        return self._session.devices[dev_ix].serial

    def set_leds(self, channel=None, R=False, G=False, B=False):
        """Set LED configuration for a channel(s).

        Parameters
        ----------
        channel : int or None
            Channel number (0-indexed). If `None`, apply to all channels.
        R : bool
            Turn on (True) or off (False) the red LED.
        G : bool
            Turn on (True) or off (False) the green LED.
        B : bool
            Turn on (True) or off (False) the blue LED.
        """
        setting = int("".join([str(int(s)) for s in [B, G, R]]), 2)

        if channel is None:
            channels = range(self.num_channels)
        else:
            channels = [channel]

        for ch in channels:
            dev_ix = self._channel_settings[ch]["dev_ix"]
            self._session.devices[dev_ix].set_led(setting)
