"""Source measure unit based on the ADALM1000."""

import copy
import time
import warnings

import pysmu


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

        # Init private container for settings, which gets populated on device
        # connection. Call the settings property to read settings. Use configure
        # methods to set them.
        self._settings = {}

        # private attribute to hold pysmu session
        self._session = None

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

    @property
    def num_channels(self):
        return len(self._session.devices)

    @property
    def settings(self):
        return self._settings

    def configure_all_channels(
        self,
        nplc=None,
        settling_delay=None,
        auto_off=None,
        four_wire=None,
        v_range=None,
        default=False,
    ):
        """Configure all channels.

        Parameters
        ----------
        nplc : float
            Integration time in number of power line cycles (NPLC).
        settling_delay : float
            Settling delay (s).
        auto_off : bool
            Automatically set output ot high impedance mode after a measurement.
        four_wire : bool
            Four wire setting.
        v_range : float
            Voltage range (5 or 2.5).
        default : bool
            Reset channels to their default values. If `True`, all other settings
            passed to this method are ignored.
        """
        num_channels = self.num_channels

        for channel in range(num_channels):
            self.configure_channel(
                channel, nplc, settling_delay, auto_off, four_wire, v_range, default
            )

    def configure_channel(
        self,
        channel,
        nplc=None,
        settling_delay=None,
        auto_off=None,
        four_wire=None,
        v_range=None,
        default=False,
    ):
        """Configure channel.

        Parameters
        ----------
        channel : int
            Channel number (0-indexed).
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
        if default is True:
            self._configure_channel_default(channel)
            self.enable_output(False, channel)
            return

        if nplc is not None:
            self._settings[channel]["nplc"] = nplc
            self._settings[channel]["nplc_samples"] = self._nplc_samples(nplc)
            self._settings[channel]["samples"] = (
                self._settings[channel]["nplc_samples"]
                + self._settings[channel]["settling_delay_samples"]
            )

        if settling_delay is not None:
            self._settings[channel]["settling_delay"] = settling_delay
            self._settings[channel][
                "settling_delay_samples"
            ] = self._settling_delay_samples(settling_delay)
            self._settings[channel]["samples"] = (
                self._settings[channel]["nplc_samples"]
                + self._settings[channel]["settling_delay_samples"]
            )

        if auto_off is not None:
            self._settings[channel]["auto_off"] = auto_off

        if four_wire is not None:
            self._settings[channel]["four_wire"] = four_wire

        if v_range is not None:
            if v_range in [2.5, 5]:
                self._settings[channel]["v_range"] = v_range
            else:
                raise ValueError(
                    f"Invalid voltage range setting: {v_range}. Must be 2.5 or 5."
                )

    def _configure_channel_default(self, channel):
        """Configure a channel with the default settings.

        Parameters
        ----------
        channel : int
            Channel number (0-indexed).
        """
        # default nplc
        nplc = 0.1
        nplc_samples = self._nplc_samples(nplc)

        # default settling delay in s
        settling_delay = 0.002
        settling_delay_samples = self._settling_delay_samples(settling_delay)

        # hence default number of source measurements
        samples = nplc_samples + settling_delay_samples

        self._settings[channel] = {
            "nplc": nplc,
            "nplc_samples": nplc_samples,
            "settling_delay": settling_delay,
            "settling_delay_samples": settling_delay_samples,
            "auto_off": False,
            "four_wire": True,
            "v_range": 5,
            "source_mode": "v",
            "samples": samples,
        }

    def _nplc_samples(self, nplc):
        """Get equivlent number of samples for an NPLC setting.

        Parameters
        ----------
        nplc : float
            Integration time in number of power line cycles (NPLC).

        Returns
        -------
        nplc_samples : int
            Integration time in number of ADC samples.
        """
        # samples per s
        sample_rate = self._session.sample_rate

        # convert nplc to integration time
        nplc_time = (1 / self.plf) * nplc

        return int(nplc_time * sample_rate)

    def _settling_delay_samples(self, settling_delay):
        """Get equivlent number of samples for a settling delay setting.

        Parameters
        ----------
        settling_delay : float
            Settling delay (s).

        Returns
        -------
        settling_delay_samples : int
            Settling delay in number of ADC samples.
        """
        # samples per s
        sample_rate = self._session.sample_rate

        return int(settling_delay * sample_rate)

    def configure_sweep(
        self, start, stop, points, dual=True, source_mode="v", channel=None
    ):
        """Configure an output sweep.

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
        channel : int or None
            Channel number for outputting voltage. If `None`, apply to all channels.
        """
        if source_mode not in ["v", "c"]:
            raise ValueError(
                f"Invalid source mode: {source_mode}. Must be 'v' (voltage) or 'c' "
                + "(current)."
            )

        if channel is None:
            channels = range(self.num_channels)
        else:
            channels = [channel]

        for i in channels:
            if source_mode == "v":
                if self.settings[i]["v_range"] == 2.5:
                    # channel LO connected to 2.5 V
                    start += 2.5
                    stop += 2.5

            step = (stop - start) / (points - 1)
            values = [x * step + start for x in range(points)]

            points_per_value = (
                self._settings[i]["nplc_samples"]
                + self._settings[i]["settling_delay_samples"]
            )

            # build values array accounting for nplc and settling delay
            new_values = []
            for value in values:
                new_values += [value] * points_per_value

            if dual is True:
                _new_values = copy.deepcopy(new_values)
                _new_values.reverse()
                new_values += _new_values

            self._settings[i]["samples"] = len(new_values)

            self._session.devices[i].channels["A"].arbitrary(new_values)

    def configure_source(self, value, source_mode="v", channel=None):
        """Set output voltage.

        Parameters
        ----------
        voltage : float
            Desired output voltage.
        source_mode : str
            Desired source mode: "v" for voltage, "c" for current.
        channel : int or None
            Channel number for outputting voltage. If `None`, apply to all channels.
        """
        if source_mode not in ["v", "c"]:
            raise ValueError(
                f"Invalid source mode: {source_mode}. Must be 'v' (voltage) or 'c' "
                + "(current)."
            )

        if channel is None:
            channels = range(self.num_channels)
        else:
            channels = [channel]

        for i in channels:
            self._settings[i]["source_mode"] = source_mode

            self._settings[i]["samples"] = (
                self._settings[i]["nplc_samples"]
                + self._settings[i]["settling_delay_samples"]
            )

            if source_mode == "v":
                if self.settings[i]["v_range"] == 2.5:
                    # channel LO connected to 2.5 V
                    value += 2.5

            # apply voltage
            self._session.devices[i].channels["A"].constant(value)

            mode = self._session.devices[i].channels["A"].mode
            if mode not in [pysmu.HI_Z, pysmu.HI_Z_SPLIT]:
                # the output is on so get a sample to trigger the change in output
                # voltage
                self._session.devices[i].get_samples(1)

                # getting a sample automatically turns off the output so turn it back
                # on again in the correct mode
                self.enable_output(True, i)

    def measure(self, channel=None, process_data=True):
        """Take a measurement(s) according to the channl(s) source configuration.

        Parameters
        ----------
        channel : int or None
            Channel number. If `None`, measure all channels
        process : bool
            If `True`, include processing accounting for NPLC and settling delay in
            the returned data.

        Returns
        -------
        data : dict
            Data dictionary of the form:
            {channel: {"raw": raw_data, "processed": processed_data}}.
        """
        if channel is None:
            channels = range(self.num_channels)
        else:
            channels = [channel]

        data = {}
        for i in channels:
            t0 = time.time()
            raw_data = self._session.devices[i].get_samples(
                self._settings[i]["samples"]
            )

            if self._settings[i]["auto_off"] is False:
                self.enable_output(True, i)

            # re-format raw data to match Keithley 2400 format
            formatted_data = self._format_data(i, raw_data, t0)

            if process_data is True:
                processed_data = self._process_data(i, formatted_data, t0)
            else:
                processed_data = None

            data[i] = {"raw": raw_data, "processed": processed_data}

        return data

    def _format_data(self, channel, raw_data, t0):
        """Format raw data to match Keithley 2400.

        Parameters
        ----------
        channel : int
            Channel number.
        raw_data : list of tuple
            Raw data returned from the device.
        t0 : float
            Timestamp representing start time (s).

        Returns
        -------
        formatted_data : list of tuple
            List of formatted data tuples. Tuple structure is: (voltage, current,
            timestamp, status).
        """
        t_delta = 1 / self._session.sample_rate

        formatted_data = []
        for i, data in enumerate(raw_data):
            timestamp = t0 + i * t_delta
            status = 0
            current = data[1]
            if self._settings[channel]["four_wire"] is True:
                voltage = data[0] - data[2]
            else:
                voltage = data[0]
            formatted_data.append((voltage, current, timestamp, status))

        return formatted_data

    def _process_data(self, channel, formatted_data, t0):
        """Process raw data accounting for NPLC and settling delay.

        Parameters
        ----------
        channel : int
            Channel number.
        raw_data : list of tuple
            Raw data returned from the device.
        t0 : float
            Timestamp representing start time (s).

        Returns
        -------
        processed_data : list of tuple
            List of processed data tuples. Tuple structure is: (voltage, current,
            timestamp, status).
        """
        nplc_samples = self._settings[channel]["nplc_samples"]
        settling_delay_samples = self._settings[channel]["settling_delay_samples"]
        points_per_value = nplc_samples + settling_delay_samples

        # start indices for each measurement value
        start_ixs = range(0, len(formatted_data) + points_per_value, points_per_value)

        processed_data = []
        for i in start_ixs:
            data_slice = formatted_data[i : i + points_per_value]
            timestamp = data_slice[0][0]
            status = data_slice[0][3]
            voltages = [d[0] for d in data_slice][settling_delay_samples:]
            voltage = sum(voltages) / len(voltages)
            currents = [d[1] for d in data_slice][settling_delay_samples:]
            current = sum(currents) / len(currents)
            processed_data.append((voltage, current, timestamp, status))

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

        for i in channels:
            if enable is True:
                if self._settings[i]["four_wire"] is True:
                    if self._settings[i]["source_mode"] == "v":
                        mode = pysmu.SVMI_SPLIT
                    else:
                        mode = pysmu.SIMV_SPLIT
                else:
                    if self._settings[i]["source_mode"] == "v":
                        mode = pysmu.SVMI
                    else:
                        mode = pysmu.SIMV
                self.set_leds(channel=i, G=True, B=True)
            else:
                if self._settings[i]["four_wire"] is True:
                    mode = pysmu.HI_Z_SPLIT
                else:
                    mode = pysmu.HI_Z
                self.set_leds(channel=i, G=True)

            self._session.devices[i].channels["A"].mode = mode

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
