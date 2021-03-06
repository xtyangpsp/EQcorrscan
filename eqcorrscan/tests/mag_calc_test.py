"""
Functions to test the mag_calc functions within EQcorrscan.
"""
import unittest
import pytest
import numpy as np
import os
import glob
import logging

from obspy.core.event import Event, Pick, WaveformStreamID
from obspy import UTCDateTime, read, Trace
from obspy.clients.fdsn import Client

from eqcorrscan.utils import mag_calc
from eqcorrscan.utils.mag_calc import (
    dist_calc, _sim_WA, _max_p2t, _pairwise, svd_moments, amp_pick_event,
    _snr, relative_amplitude, relative_magnitude)
from eqcorrscan.utils.clustering import svd
from eqcorrscan.helpers.mock_logger import MockLoggingHandler


class TestMagCalcMethods(unittest.TestCase):
    """Test all mag_calc functions."""
    def test_dist_calc(self):
        """
        Test the distance calculation that comes with mag_calc.
        """
        self.assertEqual(dist_calc((0, 0, 0), (0, 0, 10)), 10)
        self.assertEqual(round(dist_calc((0, 0, 0), (0, 1, 0))), 111)
        self.assertEqual(round(dist_calc((0, 0, 0), (1, 0, 0))), 111)
        self.assertEqual(round(dist_calc((45, 45, 0), (45, 45, 10))), 10)
        self.assertEqual(round(dist_calc((45, 45, 0), (45, 46, 0))), 79)
        self.assertEqual(round(dist_calc((45, 45, 0), (46, 45, 0))), 111)
        self.assertEqual(round(dist_calc((90, 90, 0), (90, 90, 10))), 10)
        self.assertEqual(round(dist_calc((90, 90, 0), (90, 89, 0))), 0)
        self.assertEqual(round(dist_calc((90, 90, 0), (89, 90, 0))), 111)
        self.assertEqual(round(dist_calc((0, 180, 0), (0, -179, 0))), 111)
        self.assertEqual(round(dist_calc((0, -180, 0), (0, 179, 0))), 111)

    @pytest.mark.network
    @pytest.mark.flaky(reruns=2)
    def test_sim_WA(self):
        """ Test simulating a Wood Anderson instrument. """
        t1 = UTCDateTime("2010-09-3T16:30:00.000")
        t2 = UTCDateTime("2010-09-3T17:00:00.000")
        fdsn_client = Client('IRIS')
        st = fdsn_client.get_waveforms(
            network='NZ', station='BFZ', location='10', channel='HHZ',
            starttime=t1, endtime=t2, attach_response=True)
        inventory = fdsn_client.get_stations(
            network='NZ', station='BFZ', location='10', channel='HHZ',
            starttime=t1, endtime=t2, level="response")
        tr = st[0]
        # Test with inventory
        _sim_WA(trace=tr, inventory=inventory, water_level=10)
        # TODO: This doesn't really test the accuracy

    def test_max_p2t(self):
        """Test the minding of maximum peak-to-trough."""
        data = np.random.randn(1000)
        data[500] = 20
        delta = 0.01
        amplitude, period, time = _max_p2t(data=data, delta=delta)
        self.assertTrue(amplitude > 15)
        self.assertTrue(amplitude < 25)
        self.assertEqual(round(time), 5)

    def test_pairwise(self):
        """Test the itertools wrapper"""
        pairs = _pairwise(range(20))
        for i, pair in enumerate(pairs):
            self.assertEqual(pair[0] + 1, pair[1])
        self.assertEqual(i, 18)

    def test_SVD_mag(self):
        """Test the SVD magnitude calculator."""
        # Do the set-up
        testing_path = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                                    'test_data', 'similar_events_processed')
        stream_files = glob.glob(os.path.join(testing_path, '*DFDPC*'))
        stream_list = [read(stream_file) for stream_file in stream_files]
        event_list = []
        for i, stream in enumerate(stream_list):
            st_list = []
            for tr in stream:
                if (tr.stats.station, tr.stats.channel) not in\
                        [('WHAT2', 'SH1'), ('WV04', 'SHZ'), ('GCSZ', 'EHZ')]:
                    stream.remove(tr)
                    continue
                st_list.append(i)
            event_list.append(st_list)
        event_list = np.asarray(event_list).T.tolist()
        SVectors, SValues, Uvectors, stachans = svd(stream_list=stream_list)
        M, events_out = svd_moments(u=Uvectors, s=SValues, v=SVectors,
                                    stachans=stachans, event_list=event_list)
        self.assertEqual(len(M), len(stream_list))
        self.assertEqual(len(events_out), len(stream_list))


class TestRelativeAmplitudes(unittest.TestCase):
    """Test the relative amplitude methods."""
    @classmethod
    @pytest.mark.network
    def setUpClass(cls):
        client = Client("GEONET")
        event1 = client.get_events(eventid="2016p912302")[0]
        event2 = client.get_events(eventid="3470170")[0]
        shared_chans = {p1.waveform_id.get_seed_string()
                        for p1 in event1.picks}.intersection(
            {p2.waveform_id.get_seed_string() for p2 in event2.picks})
        bulk = [(p.waveform_id.network_code, p.waveform_id.station_code,
                 p.waveform_id.location_code, p.waveform_id.channel_code,
                 p.time - 20, p.time + 60) for p in event1.picks
                if p.waveform_id.get_seed_string() in shared_chans]
        st1 = client.get_waveforms_bulk(bulk)
        st1 = st1.detrend().filter("bandpass", freqmin=2, freqmax=20)
        bulk = [(p.waveform_id.network_code, p.waveform_id.station_code,
                 p.waveform_id.location_code, p.waveform_id.channel_code,
                 p.time - 20, p.time + 60) for p in event2.picks
                if p.waveform_id.get_seed_string() in shared_chans]
        st2 = client.get_waveforms_bulk(bulk)
        st2 = st2.detrend().filter("bandpass", freqmin=2, freqmax=20)
        cls.event1 = event1
        cls.event2 = event2
        cls.st1 = st1
        cls.st2 = st2

    def test_snr(self):
        noise = np.random.randn(100)
        signal = np.random.randn(100)
        signal[50] = 100
        trace = Trace(data=np.concatenate([noise, signal]))
        trace.stats.sampling_rate = 1.
        snr = _snr(
            tr=trace,
            noise_window=(trace.stats.starttime, trace.stats.starttime + 100),
            signal_window=(trace.stats.starttime + 100, trace.stats.endtime))
        self.assertLessEqual(abs(100 - snr), 30)

    def test_scaled_event(self):
        scale_factor = 0.2
        st1 = read()
        st1.filter("bandpass", freqmin=2, freqmax=20)
        st2 = st1.copy()
        event1 = Event(picks=[
            Pick(time=tr.stats.starttime + 5, phase_hint="P",
                 waveform_id=WaveformStreamID(seed_string=tr.id))
            for tr in st1])
        event2 = event1
        for tr in st2:
            tr.data *= scale_factor
        relative_amplitudes = relative_amplitude(
            st1=st1, st2=st2, event1=event1, event2=event2)
        self.assertEqual(len(relative_amplitudes), len(st1))
        for value in relative_amplitudes.values():
            self.assertAlmostEqual(value, scale_factor)

    def test_no_suitable_picks_event1(self):
        scale_factor = 0.2
        st1 = read()
        st1.filter("bandpass", freqmin=2, freqmax=20)
        st2 = st1.copy()
        event1 = Event(picks=[
            Pick(time=tr.stats.starttime + 5, phase_hint="S",
                 waveform_id=WaveformStreamID(seed_string=tr.id))
            for tr in st1])
        event2 = event1
        for tr in st2:
            tr.data *= scale_factor
        relative_amplitudes = relative_amplitude(
            st1=st1, st2=st2, event1=event1, event2=event2)
        self.assertEqual(len(relative_amplitudes), 0)

    def test_no_suitable_picks_event2(self):
        import copy

        scale_factor = 0.2
        st1 = read()
        st1.filter("bandpass", freqmin=2, freqmax=20)
        st2 = st1.copy()
        event1 = Event(picks=[
            Pick(time=tr.stats.starttime + 5, phase_hint="P",
                 waveform_id=WaveformStreamID(seed_string=tr.id))
            for tr in st1])
        event2 = copy.deepcopy(event1)
        for pick in event2.picks:
            pick.phase_hint = "S"
        for tr in st2:
            tr.data *= scale_factor
        relative_amplitudes = relative_amplitude(
            st1=st1, st2=st2, event1=event1, event2=event2)
        self.assertEqual(len(relative_amplitudes), 0)

    def test_no_picks_event2(self):
        import copy

        scale_factor = 0.2
        st1 = read()
        st1.filter("bandpass", freqmin=2, freqmax=20)
        st2 = st1.copy()
        event1 = Event(picks=[
            Pick(time=tr.stats.starttime + 5, phase_hint="P",
                 waveform_id=WaveformStreamID(seed_string=tr.id))
            for tr in st1])
        event2 = copy.deepcopy(event1)
        event2.picks = []
        for tr in st2:
            tr.data *= scale_factor
        relative_amplitudes = relative_amplitude(
            st1=st1, st2=st2, event1=event1, event2=event2)
        self.assertEqual(len(relative_amplitudes), 0)

    def test_no_picks_event1(self):
        scale_factor = 0.2
        st1 = read()
        st1.filter("bandpass", freqmin=2, freqmax=20)
        st2 = st1.copy()
        event1 = Event()
        event2 = event1
        for tr in st2:
            tr.data *= scale_factor
        relative_amplitudes = relative_amplitude(
            st1=st1, st2=st2, event1=event1, event2=event2)
        self.assertEqual(len(relative_amplitudes), 0)

    def test_low_snr(self):
        scale_factor = 0.2
        st1 = read()
        st1[0].data += np.random.randn(st1[0].stats.npts) * st1[0].data.max()
        st2 = st1.copy()
        st2[1].data += np.random.randn(st2[1].stats.npts) * st2[1].data.max()
        event1 = Event(picks=[
            Pick(time=tr.stats.starttime + 5, phase_hint="P",
                 waveform_id=WaveformStreamID(seed_string=tr.id))
            for tr in st1])
        event2 = event1
        for tr in st2:
            tr.data *= scale_factor
        relative_amplitudes = relative_amplitude(
            st1=st1, st2=st2, event1=event1, event2=event2)
        self.assertEqual(len(relative_amplitudes), 1)
        for value in relative_amplitudes.values():
            self.assertAlmostEqual(value, scale_factor)

    def test_real_near_repeat(self):
        relative_amplitudes = relative_amplitude(
            st1=self.st1, st2=self.st2, event1=self.event1, event2=self.event2)
        for seed_id, ratio in relative_amplitudes.items():
            self.assertLess(abs(0.8 - ratio), 0.1)

    def test_real_near_repeat_magnitudes(self):
        relative_magnitudes, correlations = relative_magnitude(
            st1=self.st1, st2=self.st2, event1=self.event1, event2=self.event2,
            return_correlations=True)
        for seed_id, mag_diff in relative_magnitudes.items():
            self.assertLess(abs(mag_diff + 0.15), 0.1)

    def test_real_near_repeat_magnitudes_corr_provided(self):
        relative_magnitudes = relative_magnitude(
            st1=self.st1, st2=self.st2, event1=self.event1, event2=self.event2,
            correlations={tr.id: 1.0 for tr in self.st1})
        for seed_id, mag_diff in relative_magnitudes.items():
            self.assertLess(abs(mag_diff + 0.15), 0.1)

    def test_real_near_repeat_magnitudes_bad_corr(self):
        relative_magnitudes = relative_magnitude(
            st1=self.st1, st2=self.st2, event1=self.event1, event2=self.event2,
            correlations={tr.id: 0.2 for tr in self.st1})
        self.assertEqual(len(relative_magnitudes), 0)


# TODO: None of these actually test for accuracy.
class TestAmpPickEvent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        log = logging.getLogger(mag_calc.__name__)
        cls._log_handler = MockLoggingHandler(level='DEBUG')
        log.addHandler(cls._log_handler)
        cls.log_messages = cls._log_handler.messages
        client = Client("GEONET")
        cls.event = client.get_events(eventid="2019p498440")[0]
        origin_time = cls.event.preferred_origin().time
        bulk = [(
            p.waveform_id.network_code, p.waveform_id.station_code,
            p.waveform_id.location_code, p.waveform_id.channel_code,
            origin_time - 10, origin_time + 120)
            for p in cls.event.picks]
        cls.inventory = client.get_stations_bulk(bulk, level='response')
        cls.st = client.get_waveforms_bulk(bulk)
        cls.available_stations = len({p.waveform_id.station_code
                                      for p in cls.event.picks})

    def setUp(self):
        self._log_handler.reset()

    def test_amp_pick_event(self):
        """Test the main amplitude picker."""
        picked_event = amp_pick_event(
            event=self.event.copy(), st=self.st.copy(),
            inventory=self.inventory)
        self.assertEqual(len(picked_event.picks),
                         len(self.st) + self.available_stations)

    def test_amp_pick_remove_old_picks(self):
        picked_event = amp_pick_event(
            event=self.event.copy(), st=self.st.copy(),
            inventory=self.inventory, remove_old=True)
        self.assertEqual(len(picked_event.amplitudes), self.available_stations)

    def test_amp_pick_missing_channel(self):
        picked_event = amp_pick_event(
            event=self.event.copy(), st=self.st.copy()[0:-3],
            inventory=self.inventory, remove_old=True)
        missed = False
        for warning in self.log_messages['warning']:
            if 'no station and channel match' in warning:
                missed = True
        self.assertTrue(missed)
        self.assertEqual(len(picked_event.amplitudes),
                         self.available_stations - 1)

    def test_amp_pick_not_varwin(self):
        picked_event = amp_pick_event(
            event=self.event.copy(), st=self.st.copy(),
            inventory=self.inventory, remove_old=True,
            var_wintype=False)
        self.assertEqual(len(picked_event.amplitudes), self.available_stations)

    def test_amp_pick_not_varwin_no_S(self):
        event = self.event.copy()
        for pick in event.picks:
            if pick.phase_hint.upper() == 'S':
                event.picks.remove(pick)
        picked_event = amp_pick_event(
            event=event, st=self.st.copy(), inventory=self.inventory,
            remove_old=True, var_wintype=False)
        self.assertEqual(len(picked_event.amplitudes), 1)

    def test_amp_pick_varwin_no_S(self):
        event = self.event.copy()
        for pick in event.picks:
            if pick.phase_hint.upper() == 'S':
                event.picks.remove(pick)
        picked_event = amp_pick_event(
            event=event, st=self.st.copy(), inventory=self.inventory,
            remove_old=True, var_wintype=True)
        self.assertEqual(len(picked_event.amplitudes), 1)

    def test_amp_pick_varwin_no_P(self):
        event = self.event.copy()
        for pick in event.picks:
            if pick.phase_hint.upper() == 'P':
                event.picks.remove(pick)
        picked_event = amp_pick_event(
            event=event, st=self.st.copy(), inventory=self.inventory,
            remove_old=True, var_wintype=True)
        self.assertEqual(len(picked_event.amplitudes), self.available_stations)

    def test_amp_pick_high_min_snr(self):
        picked_event = amp_pick_event(
            event=self.event.copy(), st=self.st.copy(),
            inventory=self.inventory, remove_old=True, var_wintype=False,
            min_snr=15)
        self.assertEqual(len(picked_event.amplitudes), 0)

    def test_amp_pick_no_prefilt(self):
        picked_event = amp_pick_event(
            event=self.event.copy(), st=self.st.copy(),
            inventory=self.inventory, remove_old=True,
            var_wintype=False, pre_filt=False)
        self.assertEqual(len(picked_event.amplitudes), 4)


if __name__ == '__main__':
    unittest.main()
