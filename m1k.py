"""Source measure unit based on the ADALM1000."""

import copy
import math
import time
import warnings

import pysmu
import scipy as sp
from scipy.interpolate import interp1d


class smu:
    """Source measure unit based on the ADALM1000.

    If multiple devices are connected, the object can be treated as a multi-channel
    SMU. Devices are grouped by pysmu into a `Session()` object. Only one session can
    run on the host computer at a time. Attempting to run multiple sessions will cause
    the program/s to crash.

    Each device has two channels internally but this class exposes the device as a
    single channel entity with a four-wire measurement mode. Channel A is the master.

    Each device can be configured for two quadrant operation with a 0-5 V range
    (channel A LO connected to ground), or for four quadrant operation with a
    -2.5 - +2.5 V range (channel A LO connected to the 2.5 V ouptut).
    """

    def __init__(self, plf=50):
        """Initialise object.

        Parameters
        ----------
        plf : numeric
            Power line frequency (Hz).
        """
        self.plf = plf

        # Init private containers for settings, which get populated on device
        # connection. Call the settings property to read settings. Use configure
        # methods to set them.
        self._channel_settings = {}

        # private attribute to hold pysmu session
        self._session = None

        # private attribute stating maximum buffer size of an ADALM1000
        self._maximum_buffer_size = 100000

    def __enter__(self):
        """Enter the runtime context related to this object."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Exit the runtime context related to this object.

        Make sure everything gets cleaned up properly.
        """
        self.disconnect()

    def connect(self, serials=None, session=None):
        """Connect one or more devices (channels) to the session (SMU).

        Parameters
        ----------
        serials : str, list, or None
            List of device serial numbers to add to the session. If there are currently
            no devices in the session then the index of the device serial in the list
            will be its channel index. If a single serial is given it will be assigned
            the next available channel index. If `None`, add all available devices.
        session : pysmu.Session() or None
            Pysmu session object. If `None`, reuse the existing session attribute if
            available or create a new one. If in fact a session object does already
            exist, creating a new one will cause the program/s to crash.
        """
        if session is not None:
            # the session was provided
            self._session = session
        elif self._session is None:
            # the session wasn't provided and no session already exists so create one
            self._session = pysmu.Session(add_all=False)

            # init global settings (depends on session being created so do it now)
            self.nplc = 1
            self.settling_delay = 0.005

        if serials is None:
            self._session.scan()
            serials = [dev.serial for dev in self._session.available_devices]
        elif type(serials) is str:
            serials = [serials]
        elif type(serials) is not list:
            raise ValueError(
                f"Invalid type for serials: {type(serials)}. Must be `str`, `list`, or "
                + "`None`."
            )

        for serial in serials:
            self._connect(serial)

    def _connect(self, serial):
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

        # find new device's session index
        dev_ix = None
        for ix, dev in enumerate(self._session.devices):
            if dev.serial == serial:
                dev_ix = ix
                break

        # init new device with default settings
        self._configure_channel_default(dev_ix)
        self.enable_output(False, dev_ix)

        # channel B is only used for voltage measurement in four wire mode
        self._session.devices[dev_ix].channels["B"].mode = pysmu.Mode.HI_Z_SPLIT

    def disconnect(self, serials=None):
        """Disconnect one or more devices from the session.

        Parameters
        ----------
        serials : str, list, or None
            List of device serial numbers to remove from the session. If `None`, remove
            all available devices from the session.
        """
        if serials is None:
            serials = [dev.serial for dev in self._session.devices]
        elif type(serials) is str:
            serials = [serials]
        elif type(serials) is not list:
            raise ValueError(
                f"Invalid type for serials: {type(serials)}. Must be `str`, `list`, or "
                + "`None`."
            )

        for serial in serials:
            # find device's session index
            dev_ix = None
            for ix, dev in enumerate(self._session.devices):
                if dev.serial == serial:
                    dev_ix = ix
                    break

            if dev_ix is None:
                raise ValueError(
                    f"Device serial not found: {serial}. Could not disconnect."
                )

            self.enable_output(False, dev_ix)

            self.set_leds(dev_ix, R=True)
            dev = self._session.devices[dev_ix]
            self._session.remove(dev)

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
            lists of lists of measurement data pairs. For "meas_[x]" keys the format of
            the sub-lists is [dmm_meas, mk1_meas], for "source_[x]" keys the format of
            the sub-lists is [mk1_meas, dmm_meas].

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
                if meas.startswith("meas") is True:
                    x = [row[0] for row in data]
                    y = [row[1] for row in data]
                elif meas.startswith("source") is True:
                    x = [row[1] for row in data]
                    y = [row[0] for row in data]
                else:
                    raise ValueError(
                        f"Invalid calibration key: {meas}. Must be 'meas_v', 'meas_i',"
                        + "'source_v', or 'source_i'."
                    )

                # linearly interpolate data with linear extrapolation for data outside
                # measured range
                f_int = sp.interpolate.interp1d(
                    x, y, kind="linear", bounds_error=False, fill_value="extrapolate"
                )
                external_cal[sub_ch][meas] = f_int

        self._channel_settings[channel]["calibration_mode"] = "external"
        self._channel_settings[channel]["external_calibration"] = external_cal

    def use_internal_calibration(self, channel=None):
        """Use the devices internal calibration.

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

    @property
    def num_channels(self):
        """Get the number of connected SMU channels."""
        return len(self._session.devices)

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

        # samples per s
        sample_rate = self._session.sample_rate

        # convert nplc to integration time
        nplc_time = (1 / self.plf) * nplc

        self._nplc_samples = int(nplc_time * sample_rate)

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

        # samples per s
        sample_rate = self._session.sample_rate

        self._settling_delay_samples = int(settling_delay * sample_rate)

        # update total samples for each data point
        self._samples_per_datum = self._nplc_samples + self._settling_delay_samples

    def configure_channel(
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
        nplc : float
            Integration time in number of power line cycles (NPLC).
        settling_delay : float
            Settling delay (s).
        auto_off : bool
            Automatically set output to high impedance mode after a measurement.
        four_wire : bool
            Four wire enabled.
        v_range : float
            Voltage range (5 or 2.5). If 5, channel can output 0-5 V (two quadrant), if
            2.5 channel can output -2.5 - +2.5 V (four quadrant).
        default : bool
            Reset all settings to default.
        """
        if channel is None:
            channels = range(self.num_channels)
        else:
            channels = [channel]

        for ch in channels:
            if default is True:
                self._configure_channel_default(ch)
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

    def _configure_channel_default(self, channel):
        """Configure a channel with the default settings.

        Parameters
        ----------
        channel : int
            Channel number (0-indexed).
        """
        self._channel_settings[channel] = {
            "auto_off": False,
            "four_wire": True,
            "v_range": 5,
            "source_mode": "v",
            "samples": [],
            "calibration_mode": "internal",
            "external_calibration": {},
        }

    def configure_sweep(self, start, stop, points, dual=True, source_mode="v"):
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
            Desired source mode: "v" for voltage, "c" for current.
        """
        if source_mode not in ["v", "c"]:
            raise ValueError(
                f"Invalid source mode: {source_mode}. Must be 'v' (voltage) or 'c' "
                + "(current)."
            )

        for ch in range(self.num_channels):
            if source_mode == "v":
                if self._channel_settings[ch]["v_range"] == 2.5:
                    # channel LO connected to 2.5 V
                    start += 2.5
                    stop += 2.5

            step = (stop - start) / (points - 1)
            values = [x * step + start for x in range(points)]

            # build values array accounting for nplc and settling delay
            new_values = []
            for value in values:
                new_values += [value] * self._samples_per_datum

            if dual is True:
                _new_values = copy.deepcopy(new_values)
                _new_values.reverse()
                new_values += _new_values

            self._channel_settings[ch]["samples"] = new_values

    def configure_sources(self, values=[], source_mode="v"):
        """Set fixed output voltages for each channel.

        Parameters
        ----------
        values : list of float
            Desired output values in V or A depending on source mode. The list indeices
            match the channel numbers.
        source_mode : str
            Desired source mode: "v" for voltage, "c" for current.
        """
        if len(values) != self.num_channels:
            raise ValueError(
                "All channel values must be set simulateneously. The are "
                + f"{self.num_channels} channels connected but only {len(values)} "
                + "values were given."
            )

        if source_mode not in ["v", "c"]:
            raise ValueError(
                f"Invalid source mode: {source_mode}. Must be 'v' (voltage) or 'c' "
                + "(current)."
            )

        for ch, value in enumerate(values):
            self._channel_settings[ch]["source_mode"] = source_mode

            if source_mode == "v":
                if self._channel_settings[ch]["v_range"] == 2.5:
                    # channel LO connected to 2.5 V
                    value += 2.5

            self._channel_settings[ch]["samples"] = [value] * self._samples_per_datum

            mode = self._session.devices[ch].channels["A"].mode
            if mode not in [pysmu.Mode.HI_Z, pysmu.Mode.HI_Z_SPLIT]:
                # the output is on so set new voltage and get a sample to trigger the
                # change in output
                self._session.devices[ch].channels["A"].constant(value)
                self._session.devices[ch].get_samples(1)

                # getting a sample automatically turns off the output so turn it back
                # on again in the correct mode
                self.enable_output(True, ch)

    def measure(self, process_data=True):
        """Perform the configured sweep or source measurements for all channels.

        Parameters
        ----------
        process : bool
            If `True`, include processing accounting for NPLC and settling delay in
            the returned data.

        Returns
        -------
        data : dict
            Data dictionary of the form:
            {channel: {"raw": raw_data, "processed": processed_data}}.
        """
        # get interable of channels now to save repeated lookups later
        channels = range(self.num_channels)

        # look up requested number of samples. All channels must be the same so just
        # read from the first channel
        num_samples_requested = len(self._channel_settings[0]["samples"])

        # convert requested samples to chunks of samples that fit in the buffers
        data_per_chunk = int(
            math.floor(self._maximum_buffer_size / self._samples_per_datum)
        )
        samples_per_chunk = data_per_chunk * self._samples_per_datum
        num_chunks = int(math.ceil(num_samples_requested / samples_per_chunk))

        # init data container
        raw_data = {}

        # iterate over chunks of data that fit into the buffer
        for i in range(num_chunks):
            # write chunks to devices
            self._session.flush()
            for ch in channels:
                samples = self._channel_settings[ch]["samples"]
                chunk = samples[i * samples_per_chunk : (i + 1) * samples_per_chunk]
                self._session.devices[ch].channel["A"].write(chunk)

            # run scans
            t0 = time.time()
            self._session.run(samples_per_chunk)

            # re-enable outputs if required
            for ch in channels:
                if self._channel_settings[ch]["auto_off"] is False:
                    self.enable_output(True, ch)

            # read the data chunks and add to raw data container
            for ch in channels:
                data = self._session.devices[ch].read(samples_per_chunk, -1)
                try:
                    # add new chunk to previous data
                    raw_data[ch].extend(data)
                except KeyError:
                    # no previous chunks so create key-value pair
                    raw_data[ch] = data

        # re-format raw data to: (voltage, current, timestamp, status)
        # and process to account for nplc and settling delay if required
        if process_data is True:
            formatted_data = self._format_data(raw_data, t0)
            processed_data = self._process_data(formatted_data, t0)
        else:
            processed_data = None

        return {"raw": raw_data, "processed": processed_data}

    def _format_data(self, raw_data, t0):
        """Format raw data to match Keithley 2400.

        Parameters
        ----------
        raw_data : dict
            Raw data dictionary for all channels.
        t0 : float
            Timestamp representing start time (s).

        Returns
        -------
        formatted_data : dict
            Dictionary of formatted data for all channels. Data for each channel is a
            list of tuples structured as: (voltage, current, timestamp, status).
        """
        t_delta = 1 / self._session.sample_rate

        formatted_data = {}
        for ch in range(self.num_channels):
            data = []
            for i, data in enumerate(raw_data[ch]):
                timestamp = t0 + i * t_delta
                status = 0
                current = data[0][1]
                if self._channel_settings[ch]["four_wire"] is True:
                    voltage = data[0][0] - data[1][0]
                else:
                    voltage = data[0][0]
                data.extend([(voltage, current, timestamp, status)])
            formatted_data[ch] = data

        return formatted_data

    def _process_data(self, formatted_data, t0):
        """Process raw data accounting for NPLC and settling delay.

        Parameters
        ----------
        formatted_data : dict
            Formatted data dictionary.
        t0 : float
            Timestamp representing start time (s).

        Returns
        -------
        processed_data : list of tuple
            List of processed data tuples. Tuple structure is: (voltage, current,
            timestamp, status).
        """
        processed_data = {}
        for ch in range(self.num_channels):
            # start indices for each measurement value
            start_ixs = range(0, len(formatted_data[ch]), self._samples_per_datum)

            data = []
            for i in start_ixs:
                # final point can overlap with start of next voltage so cut it
                data_slice = formatted_data[i : i + self._samples_per_datum - 1]
                timestamp = data_slice[0][0]
                status = data_slice[0][3]
                voltages = [d[0] for d in data_slice][self._settling_delay_samples :]
                voltage = sum(voltages) / len(voltages)
                currents = [d[1] for d in data_slice][self._settling_delay_samples :]
                current = sum(currents) / len(currents)
                data.extend([(voltage, current, timestamp, status)])

            processed_data[ch] = data

        return processed_data

    def enable_output(self, enable, channel=None):
        """Enable/disable channel outputs.

        Paramters
        ---------
        enable : bool
            Turn on (`True`) or turn off (`False`) channel outputs.
        channel : int or None
            Channel number. If `None`, apply to all channels.
        """
        if channel is None:
            channels = range(self.num_channels)
        else:
            channels = [channel]

        for ch in channels:
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
                self.set_leds(channel=ch, G=True)

            self._session.devices[ch].channels["A"].mode = mode

    def get_channel_id(self, channel):
        """Get the serial number of requested channel.

        Parameters
        ----------
        channel : int
            Channel number.

        Returns
        -------
        channel_serial : str
            Channel serial string.
        """
        return self._session.devices[channel].serial

    def set_leds(self, channel=None, R=False, G=False, B=False):
        """Set LED configuration for a channel(s).

        Parameters
        ----------
        channel : int or None
            Channel number. If `None`, apply to all channels.
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

        for i in channels:
            self._session.devices[i].set_led(setting)
