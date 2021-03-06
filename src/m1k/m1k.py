"""Source measure unit based on the ADALM1000."""

import math
import platform
import time
import numpy as np
from typing import ValuesView
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

    def __init__(
        self,
        plf=50,
        ch_per_board=2,
        i_threshold=0.2,
        read_timeout=2000,
    ):
        """Initialise object.

        Parameters
        ----------
        plf : float or int
            Power line frequency (Hz).
        ch_per_board : {1, 2}
            Number of channels to use per ADALM1000 board. If 1, channel A is assumed
            as the channel to use. This cannot be changed once the object has been
            instantiated.
        i_threshold : float
            Set status code in measured data if absolute value of current in A is above
            this threshold.
        read_timeout : int
            Timeout in ms for reading data.
        """
        self._plf = plf

        if ch_per_board in [1, 2]:
            self._ch_per_board = ch_per_board
        else:
            raise ValueError(
                f"Invalid number of channels per board: {ch_per_board}. Must be 1 or 2."
            )

        self.read_timeout = read_timeout
        self.i_threshold = abs(i_threshold)

        # private attribute to hold pysmu session
        self._session = None

        # private attribute to hold device serials, channel mapping, and inverted flag
        self._serials = None
        self._channel_mapping = None
        self._channels_inverted = False

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

        # keep a private cache of channel states that gets updated when enable_outputs
        # is called. This is used to reset the enabled state after a reconnect if a
        # device error is encountered
        self._enabled_cache = {}

        # when a channel gets measured in high impedance mode both sub-channels on the
        # board DAC get locked at ~2V requiring a hard reset. Keep a cache of which
        # channels need a reset
        self._reset_cache = {}

    def __del__(self):
        """Try to disconnect."""
        self.disconnect()

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
        return len(self.channel_mapping.keys())

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

    @property
    def enabled_outputs(self):
        """Get dictionary of enabled state of all channels."""
        enabled_outputs = {}
        for ch in self.channel_mapping.keys():
            dev_ix = self._channel_settings[ch]["dev_ix"]
            dev_channel = self._channel_settings[ch]["dev_channel"]
            mode = self._session.devices[dev_ix].channels[dev_channel].mode
            if mode in [pysmu.Mode.HI_Z, pysmu.Mode.HI_Z_SPLIT]:
                enabled_outputs[ch] = False
            else:
                enabled_outputs[ch] = True

        return enabled_outputs

    @property
    def overcurrent(self):
        """Get dictionary of overcurrent state of all channels."""
        overcurrents = {}
        for ch in self.channel_mapping.keys():
            dev_ix = self._channel_settings[ch]["dev_ix"]
            overcurrents[ch] = self._session.devices[dev_ix].overcurrent

        return overcurrents

    @property
    def channel_mapping(self):
        """Get channel mapping dictionary."""
        return self._channel_mapping

    @property
    def channels_inverted(self):
        """Get state on channel mapping reversal."""
        return self._channels_inverted

    def connect(self, channel_mapping=None, sample_rate=100000):
        """Connect one or more devices (channels) to the session (SMU).

        WARNING: this method cannot be called again if a session already exists. To
        make a new connection run `disconnect()` first to destroy the current session.

        Parameters
        ----------
        channel_mapping : dict
            Dictionary of the form:
                `{channel: {"serial": serial, "sub_channel": sub_channel}}`
            where the `channel` keys are SMU channel numbers, `serial` is the board
            serial number for the corresponding channel, and `sub_channel` is the board
            sub-channel ('A' or 'B'). If `None`, connect all available devices,
            assigning channel indices in the order determined by pysmu.
        sample_rate : int
            ADC sample rate in Hz.
        """
        if self._session is None:
            # the session wasn't provided and no session already exists so create one
            self._session = pysmu.Session(add_all=False)
            num_available_devices = self._session.scan()
            if num_available_devices == 0:
                raise RuntimeError(
                    "Cannot connect to SMU, no channels available. Check SMU is "
                    + "powered on and try again."
                )
        else:
            raise RuntimeError("Cannot connect more devices to the existing session.")

        if channel_mapping is None:
            serials = [dev.serial for dev in self._session.available_devices]

            # build channel map
            channel_mapping = {}
            for ix, serial in enumerate(serials):
                if self.ch_per_board == 1:
                    channel_mapping[ix] = {"serial": serial, "sub_channel": "A"}
                else:
                    channel_mapping[2 * ix] = {"serial": serial, "sub_channel": "A"}
                    channel_mapping[2 * ix + 1] = {"serial": serial, "sub_channel": "B"}
        elif type(channel_mapping) is not dict:
            raise ValueError(
                f"Invalid type for channel_mapping: {type(channel_mapping)}. Must be"
                + " `str`, `list`, or `None`."
            )
        else:
            # get list of unique serials and mapping info from channel mapping
            serials = []
            _all_serials = []
            _all_info = []
            for channel, info in sorted(channel_mapping.items()):
                # append serial to list of serials if not already added
                serial = info["serial"]
                _all_serials.append(serial)
                if serial not in serials:
                    serials.append(serial)

                # verify sub channel string is valid
                if info["sub_channel"] not in ["A", "B"]:
                    raise ValueError(
                        "Invalid sub-channel name in channel mapping for channel "
                        + f"{channel}: {info['sub_channel']}. Must be 'A' or 'B'."
                    )
                else:
                    _all_info.append(info)

            # check channel mapping is compatible with ch_per_board setting
            if (len(serials) != len(_all_serials)) and (self.ch_per_board == 1):
                raise ValueError(
                    "If channels per board is 1 all channels in the channel mapping "
                    + "must be unique."
                )

            # check there are no duplicates in channel mapping info
            if len(set([str(info) for info in _all_info])) != len(_all_info):
                raise ValueError(
                    "Duplicate channel info found in channel mapping. Check all "
                    + "channels are uniquely defined and try again."
                )

        # connect boards 1 by 1
        self._channel_mapping = channel_mapping
        self._serials = serials
        for serial in serials:
            self._connect_board(serial)

        # set the session sample rate
        self._session.configure(sample_rate)

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
        if self.channels_inverted is True:
            self.invert_channels(False)
        self._channel_settings = {}
        self._nplc_samples = 0
        self._settling_delay_samples = 0
        self._samples_per_datum = 0
        self._enabled_cache = {}
        self._reset_cache = {}

        channels = list(self.channel_mapping.keys())

        # init with default settings
        for ch in channels:
            self._configure_channel_default_settings(ch)
            self._enabled_cache[ch] = False

        # get board mapping
        self._map_boards()

        # hard reset boards
        for ch in channels:
            self._reset_cache[ch] = True
        self._reset_boards(channels)

        # update spare channel mode if only 1 in use per board
        self._update_spare_channel()

        # ---the order of actions below is critical---

        # set default output value
        # this will reset all channel outputs to 0 V
        self.configure_dc(values=0, source_mode="v")

        # cycle outputs to register change and avoid the defualt 2V setting showing
        # on the output on first enable, then leave them all off
        self.enable_output(True)
        self.enable_output(False)

        # init global settings
        # depends on session being created and device being connected and a
        # measurement having been performed to properly init sample rate
        self.nplc = 0.1
        self.settling_delay = 0.005

    def _update_spare_channel(self):
        """Update spare channel mode if only 1 in use per board."""
        for ch in self.channel_mapping.keys():
            dev_ix = self._channel_settings[ch]["dev_ix"]
            dev_channel = self._channel_settings[ch]["dev_channel"]

            if self.ch_per_board == 1:
                # if 1 channel per board, other sub_channel is only used for voltage
                # measurement in four wire mode
                # allow retries
                if dev_channel == "A":
                    other_channel = "B"
                else:
                    other_channel = "A"
                err = None
                for attempt in range(1, self._retries + 1):
                    try:
                        self._session.devices[dev_ix].channels[
                            other_channel
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
                            self._reconnect(e)
                            continue

                if err is not None:
                    raise err

    def _map_boards(self):
        """Map boards to channels in channel settings."""
        # find device index for each channel and init channel settings
        for ch, info in sorted(self._channel_mapping.items()):
            serial = info["serial"]
            dev_ix = None
            for ix, dev in enumerate(self._session.devices):
                if dev.serial == serial:
                    dev_ix = ix
                    break

            # store mapping between channel and device index in session
            self._channel_settings[ch]["dev_ix"] = dev_ix
            self._channel_settings[ch]["serial"] = serial

            # store individual device channel
            self.channel_settings[ch]["dev_channel"] = info["sub_channel"]

    def invert_channels(self, inverted=False):
        """Invert the channel mapping.

        Parameters
        ----------
        inverted : bool
            Inverted state of the channel mapping. If an inverted state is supplied
            that matches the current inverted state, this method has no effect.
        """
        if self.channels_inverted != inverted:
            # build inverted channel mapping
            max_ch = max(self._channel_mapping.keys())
            new_channel_mapping = {}
            for ch, info in self._channel_mapping.items():
                # invert channel, doesn't matter whether `inverted` is True or False,
                # all that's required is that it's different to the current setting
                new_ch = abs(ch - max_ch)
                new_channel_mapping[new_ch] = info

            # build inverted channel settings
            new_channel_settings = {}
            for ch in self._channel_mapping.keys():
                new_ch = abs(ch - max_ch)
                new_channel_settings[new_ch] = self.channel_settings[ch]

            # apply changes
            self._channel_mapping = new_channel_mapping
            self._channel_settings = new_channel_settings
            self._channels_inverted = inverted
        elif inverted is True:
            warnings.warn(
                "Channels are already inverted. Set `False` to revert to original "
                + "channel mapping."
            )
        elif inverted is False:
            warnings.warn("Channels are already in the original channel mapping.")

    def _reconnect(self, err=None):
        """Attempt to reconnect boards if one or more gets dropped.

        Parameters
        ----------
        err : Exception
            Exception that triggered attampt to reconnect.
        """
        if platform.system() == "Windows":
            # reconnecting isn't possible on Windows to re-raise the error if avilable
            if err is not None:
                raise err
        else:
            # get the sample rate setting
            sample_rate = self.sample_rate

            # destroy the session
            self._session._close()
            del self._session
            self._session = None

            # create a new one
            self._session = pysmu.Session(add_all=False)

            # scan for available devices, one or more has probably changed index.
            # it takes some time for the scan to detect devices after they get removed
            # so check several times until the scan can see all boards
            all_found = False
            for _ in range(10):
                time.sleep(1)
                av = self._session.scan()
                if av == len(self._serials):
                    all_found = True
                    break
            if all_found is False:
                raise RuntimeError(
                    "Counld not find all devices in channel map during reconnect. "
                    + f"Found {av} devices."
                )

            # add devices to session again
            for serial in self._serials:
                self._connect_board(serial)

            # set the session sample rate
            self._session.configure(sample_rate)

            # update board mapping
            self._map_boards()

            # update spare channel mode if only 1 in use per board
            self._update_spare_channel()

            # attempt to re-enable outputs according to cache
            self._reenable_outputs()

    def _reenable_outputs(self):
        """Re-enable outputs according to enable cache."""
        enable_chs = []
        disable_chs = []
        for ch, enable in self._enabled_cache.items():
            if enable is True:
                enable_chs.append(ch)
            else:
                disable_chs.append(ch)
        self.enable_output(True, enable_chs)

        # run disable method to ensure LEDs are set properly
        self.enable_output(False, enable_chs)

    def disconnect(self):
        """Disconnect all devices from the session.

        Disconnecting individual devices would change the remaining channel's indices
        so is forbidden.
        """
        if self._session is not None:
            # hard reset boards
            channels = list(self.channel_mapping.keys())
            for ch in channels:
                self._reset_cache[ch] = True
            self._reset_boards(channels)

            # disable outputs and reset LEDs
            self.enable_output(False)
            self.set_leds(R=True)

            # reset channel settings
            self._channel_settings = {}

            # destroy the session
            self._session._close()
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
                    "meas_v": {"smu": [data], "dmm": [data]},
                    "meas_i": {"smu": [data], "dmm": [data]},
                    "source_v": {"set": [data], "smu": [data], "dmm": [data]},
                    "source_i": {"set": [data], "smu": [data], "dmm": [data]}
                },
                "B": {
                    "meas_v": {"smu": [data], "dmm": [data]},
                    "meas_i": {"smu": [data], "dmm": [data]},
                    "source_v": {"set": [data], "smu": [data], "dmm": [data]},
                    "source_i": {"set": [data], "smu": [data], "dmm": [data]}
                }
            }

            where the keys "A" and "B" refer to device channels and [data] values are
            lists of measurement data.

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
                    # linearly interpolate data with linear extrapolation for data
                    # outside measured range
                    f_int = scipy.interpolate.interp1d(
                        data["smu"],
                        data["dmm"],
                        kind="linear",
                        bounds_error=False,
                        fill_value="extrapolate",
                    )
                    external_cal[sub_ch][meas] = f_int
                elif (meas.startswith("source") is True) and (data is not None):
                    # interpolation for returned values from device
                    f_int_meas = scipy.interpolate.interp1d(
                        data["smu"],
                        data["dmm"],
                        kind="linear",
                        bounds_error=False,
                        fill_value="extrapolate",
                    )
                    # interpolation for setting the device output
                    if meas.endswith("v") is True:
                        # some voltages are unreachable by extrapolation so fix values
                        # to full device range of 0-5 V range
                        fill_value = (0, 5)
                    else:
                        fill_value = "extrapolate"
                    f_int_set = scipy.interpolate.interp1d(
                        data["dmm"],
                        data["set"],
                        kind="linear",
                        bounds_error=False,
                        fill_value=fill_value,
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
            channels = self.channel_mapping.keys()
        else:
            channels = [channel]

        for channel in channels:
            self._channel_settings[channel]["calibration_mode"] = "internal"

    def configure_channel_settings(
        self,
        channel=None,
        four_wire=None,
        v_range=None,
        default=False,
    ):
        """Configure channel.

        Parameters
        ----------
        channel : int
            Channel number (0-indexed). If `None`, apply settings to all channels.
        four_wire : bool
            Four wire enabled.
        v_range : {2.5, 5}
            Voltage range. If 5, channel can output 0-5 V (two quadrant). If 2.5
            channel can output -2.5 - +2.5 V (four quadrant).
        default : bool
            Reset all settings to default.
        """
        if channel is None:
            channels = self.channel_mapping.keys()
        else:
            channels = [channel]

        for ch in channels:
            if default is True:
                self._configure_channel_default_settings(ch)
                self.enable_output(False, ch)
            else:
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
            "four_wire": default_four_wire,
            "v_range": 5,
            "dc_mode": "v",
            "sweep_mode": "v",
            "dc_values": [],
            "sweep_values": [],
            "calibration_mode": "internal",
            "external_calibration": {},
        }

    def configure_sweep(self, start, stop, points, source_mode="v"):
        """Configure an output sweep for all channels.

        Parameters
        ----------
        start : float
            Starting value in V or A.
        stop : float
            Stop value in V or A.
        points : int
            Number of points in the sweep.
        source_mode : str
            Desired source mode: "v" for voltage, "i" for current.
        """
        if source_mode not in ["v", "i"]:
            raise ValueError(
                f"Invalid source mode: {source_mode}. Must be 'v' (voltage) or 'i' "
                + "(current)."
            )

        for ch in self.channel_mapping.keys():
            self._channel_settings[ch]["sweep_mode"] = source_mode

            step = (stop - start) / (points - 1)
            sweep = [x * step + start for x in range(points)]

            self._channel_settings[ch]["sweep_values"] = sweep

    def configure_list_sweep(self, values={}, source_mode="v"):
        """Configure list sweeps.

        Parameters
        ----------
        values : dict of lists or list
            Dictionary of lists of source values for sweeps, of the form
            {channel: [source values]}. If a list is given, this list of values will
            be set for all channels.
        source_mode : str
            Desired source mode during measurement: "v" for voltage, "i" for current.
        """
        if source_mode not in ["v", "i"]:
            raise ValueError(
                f"Invalid source mode: {source_mode}. Must be 'v' (voltage) or 'i' "
                + "(current)."
            )

        # convert list input to dictionary
        if type(values) is list:
            values_dict = {}
            for ch in self.channel_mapping.keys():
                values_dict[ch] = values
            values = values_dict

        for ch, sweep in values.items():
            self._channel_settings[ch]["sweep_mode"] = source_mode
            self._channel_settings[ch]["sweep_values"] = sweep

    def configure_dc(self, values={}, source_mode="v"):
        """Configure DC outputs.

        Parameters
        ----------
        values : dict of float or int; float or int
            Dictionary of output values, of the form {channel: dc_value}. If a value
            of numeric type is given it is applied to all channels.
        source_mode : str
            Desired source mode during measurement: "v" for voltage, "i" for current.
        """
        if source_mode not in ["v", "i"]:
            raise ValueError(
                f"Invalid source mode: {source_mode}. Must be 'v' (voltage) or 'i' "
                + "(current)."
            )

        # validate/format values input
        if type(values) in [float, int]:
            values_dict = {}
            for ch in self.channel_mapping.keys():
                values_dict[ch] = values
            values = values_dict

        # setup channel settings for a dc measurement
        for ch, ch_value in values.items():
            self._channel_settings[ch]["dc_mode"] = source_mode
            self._channel_settings[ch]["dc_values"] = [ch_value]

        # if outputs are currently enabled, update their values
        for ch, ch_value in values.items():
            dev_ix = self._channel_settings[ch]["dev_ix"]
            dev_channel = self._channel_settings[ch]["dev_channel"]

            mode = self._session.devices[dev_ix].channels[dev_channel].mode
            if mode not in [pysmu.Mode.HI_Z, pysmu.Mode.HI_Z_SPLIT]:
                # setting enable_output to True updates its value
                self.enable_output(True, ch)

    def measure(self, channels=None, measurement="dc", allow_chunking=False):
        """Perform the configured sweep or dc measurements for all channels.

        This function will attempt retries if `pysmu.SessionError` and/or
        `pysmu.DeviceError`'s occur.

        Parameters
        ----------
        channels : list of int or int
            List of channel numbers (0-indexed) to measure. If only one channel is
            measured its number can be provided as an int. If `None`, measure all
            channels.
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
            Data dictionary of the form: {channel: data}.
        """
        if measurement not in ["dc", "sweep"]:
            raise ValueError(
                f"Invalid measurement mode: {measurement}. Must be 'dc' or 'sweep'."
            )

        if type(channels) is int:
            channels = [channels]

        if channels is None:
            channels = list(self.channel_mapping.keys())

        err = None
        for attempt in range(1, self._retries + 1):
            try:
                raw_data, overcurrents, t0, t1 = self._measure(
                    channels, measurement, allow_chunking
                )

                # re-format raw data to: (voltage, current, timestamp, status)
                # and process to account for nplc and settling delay if required
                processed_data = self._process_data(
                    raw_data, channels, measurement, overcurrents, t0, t1
                )
                break
            except pysmu.SessionError as e:
                if attempt == self._retries:
                    err = e
                else:
                    warnings.warn(
                        "`pysmu.SessionError` occurred during `measure()`, attempting "
                        + "to reconnect and retry."
                    )
                    self._reconnect(e)
                    continue
            except pysmu.DeviceError as e:
                if attempt == self._retries:
                    err = e
                else:
                    warnings.warn(
                        "`pysmu.DeviceError` occurred during `measure()`, attempting "
                        + "to reconnect and retry."
                    )
                    self._reconnect(e)
                    continue
            except ZeroDivisionError as e:
                if attempt == self._retries:
                    err = e
                else:
                    warnings.warn(
                        "`ZeroDivisionError` occurred during `measure()`. A device "
                        + "probably didn't return data. Attempting to reconnect and "
                        + "retry."
                    )
                    self._reconnect(e)
                    continue

        if err is not None:
            raise err

        # return processed_data
        return processed_data

    def _measure(self, channels, measurement, allow_chunking):
        """Perform a DC or sweep measurement.

        Some care needs to be taken with how the output states are set during a
        measurement because of limitations in the board firmware/libsmu backend.
        Whenever a measurement runs on a channel in high impedance mode the DAC gets
        locked in a state with ~2 V on its output. This means under normal operation
        there will be ~2 V or ~-0.038 A on the output when the channel mode gets set to
        SVMI mode or SIMV mode, respectively. If the firmware mod is available, this
        can be avoided with a hard reset of the board triggered by software if running
        on a non-Windows operating system.

        Parameters
        ----------
        channels : list
            List of channel numbers to measure.
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
        raw_data : list of lists
            List of chunks for raw data.
        overcurrents : list of dict
            List of channel overcurrent statuses for each chunk.
        t0 : float
            Reading start time in s.
        """
        # reset any channels in this request that have been added to the reset cache
        # and are now not in high impedance mode
        non_hi_z_chs = []
        for ch in channels:
            dev_ix = self._channel_settings[ch]["dev_ix"]
            dev_channel = self._channel_settings[ch]["dev_channel"]
            mode = self._session.devices[dev_ix].channels[dev_channel].mode
            if mode not in [pysmu.Mode.HI_Z, pysmu.Mode.HI_Z_SPLIT]:
                non_hi_z_chs.append(ch)
        if len(non_hi_z_chs) > 0:
            self._reset_boards(channels)

        # build samples list accounting for nplc and settling delay
        # set number of samples requested as maximum of all requested channels
        ch_samples = {}
        num_samples_requested = 0
        for ch in channels:
            values = self._channel_settings[ch][f"{measurement}_values"]
            meas_mode = self._channel_settings[ch][f"{measurement}_mode"]

            # update setpoints according voltage range and cal if required
            values = self._update_values(ch, values, meas_mode)

            samples = []
            for value in values:
                samples += [value] * self._samples_per_datum
            ch_samples[ch] = samples
            if len(samples) > num_samples_requested:
                num_samples_requested = len(samples)

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

        # if a sweep has been requested and the output is enabled but in the wrong
        # mode, change it to the correct mode
        if measurement == "sweep":
            start_modes = {}
            for ch in channels:
                dev_ix = self._channel_settings[ch]["dev_ix"]
                dev_channel = self._channel_settings[ch]["dev_channel"]
                values = self._channel_settings[ch]["sweep_values"]
                requested_mode = self._channel_settings[ch]["sweep_mode"]
                current_mode = self._session.devices[dev_ix].channels[dev_channel].mode
                if (current_mode in [pysmu.Mode.SVMI, pysmu.Mode.SVMI_SPLIT]) and (
                    requested_mode == "i"
                ):
                    # set first current of sweep in requested mode
                    self.configure_dc({ch: values[0]}, "i")
                elif (current_mode in [pysmu.Mode.SIMV, pysmu.Mode.SIMV_SPLIT]) and (
                    requested_mode == "v"
                ):
                    # set first voltage of sweep in requested mode
                    self.configure_dc({ch: values[0]}, "v")
                else:
                    # ignore if starting in HI_Z mode, i.e. output off
                    pass

                # update start modes
                start_modes[ch] = (
                    self._session.devices[dev_ix].channels[dev_channel].mode
                )

        # init data container
        # TODO: make more accurate sample timer
        t0 = time.time()
        raw_data = []
        overcurrents = []
        # iterate over chunks of data that fit into the buffer
        for i in range(num_chunks):
            # write chunks to devices
            self._session.flush()
            for ch in channels:
                dev_ix = self._channel_settings[ch]["dev_ix"]
                dev_channel = self._channel_settings[ch]["dev_channel"]
                samples = ch_samples[ch]
                chunk = samples[i * samples_per_chunk : (i + 1) * samples_per_chunk]
                if chunk != []:
                    # flush write and read buffers
                    self._session.devices[dev_ix].flush(int(dev_channel == "B"), True)
                    self._session.devices[dev_ix].channels[dev_channel].write(chunk)

            # run scans
            self._session.start(samples_per_chunk)

            # read the data chunk and add to raw data container
            raw_data.append(self._session.read(samples_per_chunk, self.read_timeout))

            chunk_overcurrents = {}
            for ch in channels:
                chunk_overcurrents[ch] = self._session.devices[dev_ix].overcurrent
            overcurrents.append(chunk_overcurrents)
        t1 = time.time()

        # disable/enable outputs as required
        for ch in channels:
            # if a sweep has been performed update the dc output to the last value to
            # avoid unexpected changes to the output on subsequent enable/disables
            if measurement == "sweep":
                # only update if output was on during measurement
                if start_modes[ch] not in [pysmu.Mode.HI_Z, pysmu.Mode.HI_Z_SPLIT]:
                    values = self._channel_settings[ch]["sweep_values"]
                    requested_mode = self._channel_settings[ch]["sweep_mode"]
                    self.configure_dc({ch: values[-1]}, requested_mode)

        # update the reset cache
        self._update_reset_cache()

        return raw_data, overcurrents, t0, t1

    def _low_level_voltage_sweep(self, start, stop, points):
        """Perform a voltage sweep and return full buffer.

        Parameters
        ----------
        start : float
            Start voltage in V.
        stop : float
            Stop voltage in V.
        points : int
            Number of points in sweep.

        Returns
        -------
        raw_data : dict
            Raw data dictionary containing full data buffers.
        """
        step = (stop - start) / (points - 1)
        sweep = [x * step + start for x in range(points)]

        samples = []
        for value in sweep:
            samples += [value] * self._samples_per_datum

        if len(samples) > self.maximum_buffer_size:
            raise ValueError(
                "Cannot fit sweep in buffer. Reduce NPLC, settling delay, and/or "
                + "number of samples."
            )

        for ch in self.channel_mapping.keys():
            dev_ix = self.channel_settings[ch]["dev_ix"]
            dev_channel = self.channel_settings[ch]["dev_channel"]
            self._session.devices[dev_ix].channels[dev_channel].write(samples)

        self._session.start(len(samples))
        data = self._session.read(len(samples), self.read_timeout)

        data_dict = {}
        for ch in self.channel_mapping.keys():
            dev_ix = self.channel_settings[ch]["dev_ix"]
            dev_channel = self.channel_settings[ch]["dev_channel"]
            if dev_channel == "A":
                dev_channel_num = 0
            else:
                dev_channel_num = 1
            dev_data = data[dev_ix]
            ch_data = []
            for d in dev_data:
                ch_data.append(d[dev_channel_num])
            data_dict[ch] = ch_data

        return data_dict

    def _reset_boards(self, channels):
        """Reset boards to default state.

        Requires firmware mod. Cannot be done on Windows.

        Parameters
        ----------
        channels : list
            List of SMU channels to check.
        """
        reset_channels = []
        for ch in channels:
            if self._reset_cache[ch] is True:
                reset_channels.append(ch)

        if platform.system() != "Windows":
            # find all unique boards that require resetting
            dev_ixs = set(
                [self.channel_settings[ch]["dev_ix"] for ch in reset_channels]
            )

            # reset boards that require it
            reset_devs = 0
            for dev_ix in dev_ixs:
                dev = self._session.devices[dev_ix]
                try:
                    # send message to reset
                    # will only work if board is running firmware board
                    # other boards will igore the request and it'll pass without error
                    dev.ctrl_transfer(0x40, 0x26, 0, 0, 0, 0, 100)
                except OSError:
                    # the OSError means the command was succesfully processed by the
                    # firmware mod and detached the device
                    reset_devs += 1

            # update reset cache
            for ch in reset_channels:
                self._reset_cache[ch] = False

            # after resetting the boards they get detatched so reconnect them
            if reset_devs > 0:
                self._reconnect(Exception)

    def _update_reset_cache(self):
        """Update the reset cache.

        Whenever a measurement is performed, any channel in high impedance mode
        needs to be reset before a subsequent measurement if the firmware modification
        is available. This prevents ~2V showing on the output when subsequently
        activating SVMI mode.
        """
        for ch in self.channel_mapping.keys():
            dev_ix = self._channel_settings[ch]["dev_ix"]
            dev_channel = self._channel_settings[ch]["dev_channel"]
            mode = self._session.devices[dev_ix].channels[dev_channel].mode
            if mode in [pysmu.Mode.HI_Z, pysmu.Mode.HI_Z_SPLIT]:
                self._reset_cache[ch] = True
            else:
                self._reset_cache[ch] = False

    def _update_values(self, ch, values, meas_mode):
        """Update set values according to voltage range and external calibration.

        Parameters
        ----------
        ch : int
            SMU channel (0-indexed).
        values : list
            List of voltage or current set points to measure.
        meas_mode : str
            Measurement source mode: "v" (voltage) or "i" (current).

        Results
        -------
        values : list
            List of voltage or current set points to measure, re-scaled according to
            calibration settings.
        """
        # add offset if lo is 2.5V
        offset = 0
        if meas_mode == "v":
            if self._channel_settings[ch]["v_range"] == 2.5:
                # channel LO connected to 2.5 V
                offset = 2.5
        values = [x + offset for x in values]

        # update set value according to external cal
        if self._channel_settings[ch]["calibration_mode"] == "external":
            dev_channel = self._channel_settings[ch]["dev_channel"]
            cal = self._channel_settings[ch]["external_calibration"][dev_channel]
            f_int = cal[f"source_{meas_mode}"]["set"]
            values = f_int(values).tolist()

        return values

    def _process_data(self, raw_data, channels, measurement, overcurrents, t0, t1):
        """Process raw data accounting for NPLC and settling delay.

        Parameters
        ----------
        raw_data : dict
            Raw data dictionary.
        channels : list of int or int
            List of channel numbers (0-indexed) to extract from raw data.
        measurement : {"dc", "sweep"}
            Measurement to perform based on stored settings from configure_sweep
            ("sweep") or configure_dc ("dc") method calls.
        overcurrents : list of dict
            List of channel overcurrent statuses for each chunk.
        t0 : float
            Timestamp representing start time (s).
        t1 : float
            Timestamp representing end time (s)..

        Returns
        -------
        processed_data : list of tuple
            List of processed data tuples. Tuple structure is: (voltage, current,
            timestamp, status).
        """
        t_delta = 1 / self.sample_rate

        # determine if overcurrent occured in any chunk for each channel
        channel_overcurrents = {}
        for ch, _ in overcurrents[0].items():
            channel_overcurrents[ch] = []
            for chunk_overcurrents in overcurrents:
                channel_overcurrents[ch].append(chunk_overcurrents[ch])
            channel_overcurrents[ch] = any(channel_overcurrents[ch])

        # init processed data container
        processed_data = {}
        for ch in channels:
            processed_data[ch] = []

        cumulative_chunk_lengths = 0
        for chunk in raw_data:
            if self.ch_per_board == 1:
                for ch in channels:
                    dev_ix = self._channel_settings[ch]["dev_ix"]
                    dev_channel = self._channel_settings[ch]["dev_channel"]
                    # start indices for each measurement value
                    start_ixs = range(0, len(chunk[dev_ix]), self._samples_per_datum)

                    A_voltages = []
                    B_voltages = []
                    currents = []
                    timestamps = []
                    for i in start_ixs:
                        # final point can overlap with start of next voltage so cut it
                        data_slice = chunk[dev_ix][i : i + self._samples_per_datum - 1]
                        # discard settling delay data
                        data_slice = data_slice[self._settling_delay_samples :]

                        # approximate datum timestamp, doesn't account for chunking
                        # timestamps.append(
                        #     t0
                        #     + (cumulative_chunk_lengths + i)
                        #     * t_delta
                        #     * self._samples_per_datum
                        # )
                        # don't estimate timestamps for sweeps, just store start value
                        if cumulative_chunk_lengths + i == 0:
                            timestamps.append(t0)
                        else:
                            timestamps.append("nan")

                        # pick out and process useful data
                        A_point_voltages = []
                        B_point_voltages = []
                        point_currents = []
                        for row in data_slice:
                            A_point_voltages.append(row[0][0])
                            B_point_voltages.append(row[1][0])
                            point_currents.append(row[0][1])

                        # filter spikes
                        thresh = 0.01
                        diffs = np.gradient(point_currents)
                        pc = np.array(point_currents)
                        keep_i = np.abs(diffs) < thresh
                        to_keep = np.roll(keep_i, 1)

                        point_currents = pc[to_keep].tolist()
                        A_point_voltages = np.array(A_point_voltages)[to_keep].tolist()
                        B_point_voltages = np.array(B_point_voltages)[to_keep].tolist()

                        A_voltages.append(sum(A_point_voltages) / len(A_point_voltages))
                        B_voltages.append(sum(B_point_voltages) / len(B_point_voltages))
                        currents.append(sum(point_currents) / len(point_currents))

                    # update measured values according to external calibration
                    if self._channel_settings[ch]["calibration_mode"] == "external":
                        cal = self._channel_settings[ch]["external_calibration"]
                        A_cal = cal["A"]

                        mode = self._session.devices[dev_ix].channels[dev_channel].mode

                        if mode in [pysmu.Mode.SVMI, pysmu.Mode.SVMI_SPLIT]:
                            f_int_mva = A_cal["source_v"]["meas"]
                            f_int_mia = A_cal["meas_i"]
                        elif mode in [pysmu.Mode.SIMV, pysmu.Mode.SIMV_SPLIT]:
                            f_int_mva = A_cal["meas_v"]
                            f_int_mia = A_cal["source_i"]["meas"]
                        else:
                            # HI_Z or HI_Z_SPLIT mode
                            f_int_mva = A_cal["meas_v"]
                            f_int_mia = A_cal["meas_i"]

                        A_voltages = f_int_mva(A_voltages)
                        currents = f_int_mia(currents).tolist()

                        if self._channel_settings[ch]["four_wire"] is True:
                            B_cal = cal["B"]
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

                    # set status: 0=ok, 1=i>i_theshold, 2=overcurrent (overload on
                    # board input power)
                    if channel_overcurrents[ch] is True:
                        statuses = [2 for i in currents]
                    else:
                        statuses = [
                            0 if abs(i) <= self.i_threshold else 1 for i in currents
                        ]
                    processed_data[ch].extend(
                        [
                            (v, i, t, s)
                            for v, i, t, s in zip(
                                voltages, currents, timestamps, statuses
                            )
                        ]
                    )
            elif self.ch_per_board == 2:
                # derive list of boards from channels
                for ch in channels:
                    dev_ix = self._channel_settings[ch]["dev_ix"]
                    dev_channel = self._channel_settings[ch]["dev_channel"]
                    # start indices for each measurement value
                    start_ixs = range(0, len(chunk[dev_ix]), self._samples_per_datum)

                    if dev_channel == "A":
                        dev_channel_num = 0
                    else:
                        dev_channel_num = 1

                    voltages = []
                    currents = []
                    timestamps = []
                    for i in start_ixs:
                        # final point can overlap with start of next voltage so cut it
                        data_slice = chunk[dev_ix][i : i + self._samples_per_datum - 1]
                        # discard settling delay data
                        data_slice = data_slice[self._settling_delay_samples :]

                        # approximate datum timestamp, doesn't account for chunking
                        # timestamps.append(
                        #     t0
                        #     + (cumulative_chunk_lengths + i)
                        #     * t_delta
                        #     * self._samples_per_datum
                        # )
                        # don't estimate timestamps for sweeps, just store start value
                        if cumulative_chunk_lengths + i == 0:
                            timestamps.append(t0)
                        else:
                            timestamps.append("nan")

                        # pick out and process useful data
                        point_voltages = []
                        point_currents = []
                        for row in data_slice:
                            point_voltages.append(row[dev_channel_num][0])
                            point_currents.append(row[dev_channel_num][1])

                        # filter spikes
                        thresh = 0.01
                        diffs = np.gradient(point_currents)
                        pc = np.array(point_currents)
                        keep_i = np.abs(diffs) < thresh
                        to_keep = np.roll(keep_i, 1)

                        point_currents = pc[to_keep].tolist()
                        point_voltages = np.array(point_voltages)[to_keep].tolist()

                        voltages.append(sum(point_voltages) / len(point_voltages))
                        currents.append(sum(point_currents) / len(point_currents))

                    # update measured values according to external calibration
                    cal_mode = self._channel_settings[ch]["calibration_mode"]

                    # get source mode to determine how to look up external cal
                    mode = self._session.devices[dev_ix].channels[dev_channel].mode

                    # apply external calibration if required
                    if cal_mode == "external":
                        cal = self._channel_settings[ch]["external_calibration"][
                            dev_channel
                        ]

                        if mode in [pysmu.Mode.SVMI, pysmu.Mode.SVMI_SPLIT]:
                            f_int_mv = cal["source_v"]["meas"]
                            f_int_mi = cal["meas_i"]
                        elif mode in [pysmu.Mode.SIMV, pysmu.Mode.SIMV_SPLIT]:
                            f_int_mv = cal["meas_v"]
                            f_int_mi = cal["source_i"]["meas"]
                        else:
                            # HI_Z or HI_Z_SPLIT mode
                            f_int_mv = cal["meas_v"]
                            f_int_mi = cal["meas_i"]

                        voltages = f_int_mv(voltages).tolist()
                        currents = f_int_mi(currents).tolist()

                    # set status: 0=ok, 1=i>i_theshold, 2=overcurrent (overload on
                    # board input power)
                    if channel_overcurrents[ch] is True:
                        statuses = [2 for i in currents]
                    else:
                        statuses = [
                            0 if abs(i) <= self.i_threshold else 1 for i in currents
                        ]
                    processed_data[ch].extend(
                        [
                            (v, i, t, s)
                            for v, i, t, s in zip(
                                voltages, currents, timestamps, statuses
                            )
                        ]
                    )

            cumulative_chunk_lengths += len(chunk)

        # if sweep lists are different lengths, discard data that wasn't requested
        if measurement == "sweep":
            for ch in channels:
                values = self._channel_settings[ch]["sweep_values"]
                processed_data[ch] = processed_data[ch][: len(values)]

        # set last time to t1 if more than one value measured
        for ch in list(processed_data.keys()):
            if len(processed_data[ch]) > 1:
                last_row = list(processed_data[ch][-1])
                last_row[2] = t1
                processed_data[ch][-1] = tuple(last_row)

        return processed_data

    def enable_output(self, enable, channels=None):
        """Enable/disable channel outputs.

        This function will attempt retries if `pysmu.DeviceError`'s occur.

        Paramters
        ---------
        enable : bool
            Turn on (`True`) or turn off (`False`) channel outputs.
        channels : list of int, int, or None
            List of channel numbers (0-indexed). If only one channel is required its
            number can be provided as an int. If `None`, apply to all channels.
        """
        if type(channels) is int:
            channels = [channels]

        if channels is None:
            channels = list(self.channel_mapping.keys())

        err = None
        for attempt in range(1, self._retries + 1):
            try:
                self._enable_output(enable, channels)
                break
            except pysmu.DeviceError as e:
                if attempt == self._retries:
                    err = e
                else:
                    warnings.warn(
                        "`pysmu.DeviceError` occurred during `enable_output()`, "
                        + "attempting to reconnect and retry."
                    )
                    self._reconnect(e)
                    continue
            except pysmu.SessionError as e:
                if attempt == self._retries:
                    err = e
                else:
                    warnings.warn(
                        "`pysmu.SessionError` occurred during `measure()`, attempting "
                        + "to reconnect and retry."
                    )
                    self._reconnect(e)
                    continue

        if err is not None:
            raise err

    def _enable_output(self, enable, channels):
        """Enable/disable channel outputs.

        This function will attempt retries if `pysmu.DeviceError`'s occur.

        Paramters
        ---------
        enable : bool
            Turn on (`True`) or turn off (`False`) channel outputs.
        channels : list of int, int, or None
            List of channel numbers (0-indexed). If only one channel is required its
            number can be provided as an int. If `None`, apply to all channels.
        """
        if (enable is True) and (len(channels) > 0):
            # reset any channels in this request that have been added to the reset cache
            self._reset_boards(channels)

            for ch in channels:
                dev_ix = self._channel_settings[ch]["dev_ix"]
                dev_ch = self._channel_settings[ch]["dev_channel"]

                # set leds
                self.set_leds(channel=ch, G=True, B=True)

                dc_values = self._channel_settings[ch]["dc_values"]
                source_mode = self._channel_settings[ch]["dc_mode"]

                # update values depending on mode and cal
                dc_values = self._update_values(ch, dc_values, source_mode)

                # update output
                self._write_dc_values(ch, dev_ix, dev_ch, dc_values, source_mode)

            # run non-blocking measurement to update all output values
            self._session.start(1)
            self._session.read(1, self.read_timeout)

            # update reset cache
            self._update_reset_cache()
        else:
            # disable channels
            for ch in channels:
                dev_ix = self._channel_settings[ch]["dev_ix"]
                dev_ch = self._channel_settings[ch]["dev_channel"]

                if self._channel_settings[ch]["four_wire"] is True:
                    mode = pysmu.Mode.HI_Z_SPLIT
                else:
                    mode = pysmu.Mode.HI_Z

                # if both channels on a board are accessible, only turn off the blue
                # LED if both channels are off
                if self.ch_per_board == 1:
                    self.set_leds(channel=ch, G=True)
                elif self.ch_per_board == 2:
                    if dev_ch == "A":
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

                # set output mode
                self._session.devices[dev_ix].channels[dev_ch].mode = mode

        # cache enable setting in case a reconnect is required
        # this must happen after boards get reset or else the reset gets stuck in
        # a recursive loop
        for ch in channels:
            self._enabled_cache[ch] = enable

    def _write_dc_values(self, ch, dev_ix, dev_ch, dc_values, source_mode):
        """Write a DC value to a device sub-channel.

        Parameters
        ----------
        ch : int
            SMU channel, i.e. channels that are keys in channel_mapping and
            channel_settings.
        dev_ix : int
            Device index.
        dev_ch : str
            Device sub-channel, "A" or "B".
        dc_values : list
            DC value to set output to.

        Returns
        -------
        mode : pysmu.Mode
            Sub-channel mode.
        """
        # determine and set source mode
        if self._channel_settings[ch]["four_wire"] is True:
            if source_mode == "v":
                mode = pysmu.Mode.SVMI_SPLIT
            else:
                mode = pysmu.Mode.SIMV_SPLIT
        else:
            if source_mode == "v":
                mode = pysmu.Mode.SVMI
            else:
                mode = pysmu.Mode.SIMV

        # firmware mod not available so run a measuremnt to update the value
        # write value to buffer
        self._session.devices[dev_ix].channels[dev_ch].write(dc_values)

        # set output mode
        self._session.devices[dev_ix].channels[dev_ch].mode = mode

    def _write_dac_value(self, dev_ix, dev_ch, dc_value, source_mode):
        """Write a value directly to the DAC.

        Requires firmware mod.

        Parameter
        ---------
        dev_ix : int
            Device index.
        dev_ch : str
            Device sub-channel, "A" or "B".
        dc_values : float
            DC value to set output to.
        source_mode : str
            Desired source mode: "v" for voltage, "i" for current.
        """
        # TODO: fix firmware to make this function work and then call it when required
        # scale dc value for DAC according to mode
        if source_mode == "v":
            # (max 5 V, 16-bit)
            dac_val = (dc_value / 5) * 65535
        else:
            # (max +/- 200 mA, 16-bit)
            dac_val = ((dc_value + 0.2) / 0.4) * 65535

        # convert sub-channel letter to number
        if dev_ch == "A":
            dev_ch_num = 0
        else:
            dev_ch_num = 1

        # write to DAC
        self._session.devices[dev_ix].ctrl_transfer(
            0x40, 0x27, dac_val, dev_ch_num, 0, 0, 0, 100
        )

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
            channels = self.channel_mapping.keys()
        else:
            channels = [channel]

        for ch in channels:
            dev_ix = self._channel_settings[ch]["dev_ix"]
            self._session.devices[dev_ix].set_led(setting)
