"""
Functions for network matched-filter detection of seismic data.

Designed to cross-correlate templates generated by template_gen function
with data and output the detections.

:copyright:
    EQcorrscan developers.

:license:
    GNU Lesser General Public License, Version 3
    (https://www.gnu.org/copyleft/lesser.html)
"""
import ast
import copy
import os
import shutil
import logging

from obspy import UTCDateTime

from eqcorrscan.core.match_filter.detection import Detection, get_catalog
from eqcorrscan.utils.plotting import cumulative_detections


Logger = logging.getLogger(__name__)


class Family(object):
    """
    Container for Detection objects from a single template.

    :type template: eqcorrscan.core.match_filter.Template
    :param template: The template used to detect the family
    :type detections: list
    :param detections: list of Detection objects
    :type catalog: obspy.core.event.Catalog
    :param catalog:
        Catalog of detections, with information for the individual detections.
    """

    def __init__(self, template, detections=None, catalog=None):
        """Instantiation of Family object."""
        self.template = template
        if isinstance(detections, Detection):
            detections = [detections]
        self.detections = detections or []
        self.__catalog = get_catalog(self.detections)
        if catalog:
            Logger.warning("Setting catalog directly is no-longer supported, "
                           "now generated from detections.")

    @property
    def catalog(self):
        if len(self.__catalog) != len(self.detections):
            self.__catalog = get_catalog(self.detections)
        return self.__catalog

    @catalog.setter
    def catalog(self, catalog):
        raise NotImplementedError(
            "Setting catalog directly is no-longer supported")

    def __repr__(self):
        """
        Print method on Family.

        :return: str

        .. rubric:: Example

        >>> from eqcorrscan import Template
        >>> family = Family(template=Template(name='a'))
        >>> print(family)
        Family of 0 detections from template a
        """
        print_str = ('Family of %s detections from template %s' %
                     (len(self.detections), self.template.name))
        return print_str

    def __add__(self, other):
        """
        Extend method. Used for '+'

        .. rubric:: Example

        >>> from eqcorrscan import Template, Detection
        >>> family_a = Family(template=Template(name='a'))
        >>> family_b = Family(template=Template(name='a'))
        >>> family_c = family_a + family_b
        >>> print(family_c)
        Family of 0 detections from template a


        Can only extend family with the family of detections from the same
        template:

        >>> family_a = Family(template=Template(name='a'))
        >>> family_b = Family(template=Template(name='b'))
        >>> family_c = family_a + family_b # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        NotImplementedError: Templates do not match


        Can extend by adding a detection from the same template.

        >>> family_a = Family(template=Template(name='a'))
        >>> detection = Detection(
        ...     template_name='a', detect_time=UTCDateTime(), no_chans=5,
        ...     detect_val=2.5, threshold=1.23, typeofdet='corr',
        ...     threshold_type='MAD', threshold_input=8.0)
        >>> family = family_a + detection
        >>> print(family)
        Family of 1 detections from template a


        Will not work if detections are made using a different Template.

        >>> family_a = Family(template=Template(name='a'))
        >>> detection = Detection(
        ...     template_name='b', detect_time=UTCDateTime(), no_chans=5,
        ...     detect_val=2.5, threshold=1.23, typeofdet='corr',
        ...     threshold_type='MAD', threshold_input=8.0)
        >>> family = family_a + detection # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        NotImplementedError: Templates do not match


        Cannot extent a family with a list, or another object.

        >>> family_a = Family(template=Template(name='a'))
        >>> family = family_a + ['albert'] # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        NotImplementedError: Can only extend with a Detection of Family object.
        """
        return self.copy().__iadd__(other)

    def __iadd__(self, other):
        """
        Rich method '+='

        .. rubric:: Example

        >>> from eqcorrscan import Template
        >>> family_a = Family(template=Template(name='a'))
        >>> family_b = Family(template=Template(name='a'))
        >>> family_a += family_b
        >>> print(family_a)
        Family of 0 detections from template a
        """
        if isinstance(other, Family):
            if other.template == self.template:
                self.detections.extend(other.detections)
                self.__catalog.events.extend(get_catalog(other.detections))
            else:
                raise NotImplementedError('Templates do not match')
        elif isinstance(other, Detection) and other.template_name \
                == self.template.name:
            self.detections.append(other)
            self.__catalog.events.extend(get_catalog([other]))
        elif isinstance(other, Detection):
            raise NotImplementedError('Templates do not match')
        else:
            raise NotImplementedError('Can only extend with a Detection or '
                                      'Family object.')
        return self

    def __eq__(self, other, verbose=False):
        """
        Check equality, rich comparison operator '=='

        .. rubric:: Example

        >>> from eqcorrscan import Template, Detection
        >>> family_a = Family(template=Template(name='a'), detections=[])
        >>> family_b = Family(template=Template(name='a'), detections=[])
        >>> family_a == family_b
        True
        >>> family_c = Family(template=Template(name='b'))
        >>> family_c == family_a
        False


        Test if families are equal without the same detections

        >>> family_a = Family(
        ...     template=Template(name='a'), detections=[
        ...     Detection(template_name='a', detect_time=UTCDateTime(0),
        ...               no_chans=8, detect_val=4.2, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0)])
        >>> family_b = Family(
        ...     template=Template(name='a'), detections=[
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 10,
        ...               no_chans=8, detect_val=4.2, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0)])
        >>> family_a == family_b
        False
        >>> family_c = Family(
        ...     template=Template(name='a'), detections=[
        ...     Detection(template_name='a', detect_time=UTCDateTime(0),
        ...               no_chans=8, detect_val=4.2, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0),
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 10,
        ...               no_chans=8, detect_val=4.5, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0)])
        >>> family_a == family_c
        False
        """
        if not self.template.__eq__(other.template, verbose=verbose):
            return False
        if len(self.detections) != len(other.detections):
            return False
        if len(self.detections) != 0 and len(other.detections) != 0:
            for det, other_det in zip(self.sort().detections,
                                      other.sort().detections):
                if not det.__eq__(other_det, verbose=verbose):
                    return False
        # currently not checking for catalog...
        if len(self.catalog) != len(other.catalog):
            return False
        return True

    def __ne__(self, other):
        """
        Rich comparison operator '!='

        .. rubric:: Example

        >>> from eqcorrscan import Template, Detection
        >>> family_a = Family(
        ...     template=Template(name='a'), detections=[
        ...     Detection(template_name='a', detect_time=UTCDateTime(0),
        ...               no_chans=8, detect_val=4.2, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0)])
        >>> family_b = Family(
        ...     template=Template(name='a'), detections=[
        ...     Detection(template_name='a', detect_time=UTCDateTime(),
        ...               no_chans=8, detect_val=4.2, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0)])
        >>> family_a != family_b
        True
        """
        return not self.__eq__(other)

    def __getitem__(self, index):
        """
        Retrieve a detection or series of detections from the Family.

        .. rubric:: Example

        >>> from eqcorrscan import Template, Detection
        >>> family = Family(
        ...     template=Template(name='a'), detections=[
        ...     Detection(template_name='a', detect_time=UTCDateTime(0),
        ...               no_chans=8, detect_val=4.2, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0),
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 10,
        ...               no_chans=8, detect_val=4.5, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0)])
        >>> isinstance(family[0], Detection)
        True
        >>> len(family[0:])
        2
        """
        return self.detections.__getitem__(index)

    def __len__(self):
        """Number of detections in Family.

        .. rubric:: Example

        >>> from eqcorrscan import Template, Detection
        >>> family = Family(
        ...     template=Template(name='a'), detections=[
        ...     Detection(template_name='a', detect_time=UTCDateTime(0),
        ...               no_chans=8, detect_val=4.2, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0),
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 10,
        ...               no_chans=8, detect_val=4.5, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0)])
        >>> print(len(family))
        2
        """
        return len(self.detections)

    def _uniq(self):
        """
        Get list of unique detections.
        Works in place.

        .. rubric:: Example

        >>> from eqcorrscan import Template, Detection
        >>> family = Family(
        ...     template=Template(name='a'), detections=[
        ...     Detection(template_name='a', detect_time=UTCDateTime(0),
        ...               no_chans=8, detect_val=4.2, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0),
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 10,
        ...               no_chans=8, detect_val=4.5, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0),
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 10,
        ...               no_chans=8, detect_val=4.5, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0)])
        >>> len(family)
        3
        >>> len(family._uniq())
        2
        """
        _detections = []
        [_detections.append(d) for d in self.detections
         if not _detections.count(d)]
        self.detections = _detections
        return self

    def sort(self):
        """Sort by detection time.

        .. rubric:: Example

        >>> from eqcorrscan import Template, Detection
        >>> family = Family(
        ...     template=Template(name='a'), detections=[
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 200,
        ...               no_chans=8, detect_val=4.2, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0),
        ...     Detection(template_name='a', detect_time=UTCDateTime(0),
        ...               no_chans=8, detect_val=4.5, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0),
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 10,
        ...               no_chans=8, detect_val=4.5, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0)])
        >>> family[0].detect_time
        UTCDateTime(1970, 1, 1, 0, 3, 20)
        >>> family.sort()[0].detect_time
        UTCDateTime(1970, 1, 1, 0, 0)
        """
        self.detections = sorted(self.detections, key=lambda d: d.detect_time)
        return self

    def copy(self):
        """
        Returns a copy of the family.

        :return: Copy of family

        .. rubric:: Example

        >>> from eqcorrscan import Template, Detection
        >>> family = Family(
        ...     template=Template(name='a'), detections=[
        ...     Detection(template_name='a', detect_time=UTCDateTime(0),
        ...               no_chans=8, detect_val=4.2, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0),
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 10,
        ...               no_chans=8, detect_val=4.5, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0)])
        >>> family == family.copy()
        True
        """
        return copy.deepcopy(self)

    def append(self, other):
        """
        Add another family or detection to the family.

        .. rubric:: Example

        Append a family to a family

        >>> from eqcorrscan import Template, Detection
        >>> family_a = Family(template=Template(name='a'))
        >>> family_b = Family(template=Template(name='a'))
        >>> family_a.append(family_b)
        Family of 0 detections from template a


        Append a detection to the family

        >>> family_a = Family(template=Template(name='a'))
        >>> detection = Detection(
        ...     template_name='a', detect_time=UTCDateTime(), no_chans=5,
        ...     detect_val=2.5, threshold=1.23, typeofdet='corr',
        ...     threshold_type='MAD', threshold_input=8.0)
        >>> family_a.append(detection)
        Family of 1 detections from template a
        """
        return self.__add__(other)

    def plot(self, plot_grouped=False):
        """
        Plot the cumulative number of detections in time.

        .. rubric:: Example

        >>> from eqcorrscan import Template, Detection
        >>> family = Family(
        ...     template=Template(name='a'), detections=[
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 200,
        ...               no_chans=8, detect_val=4.2, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0),
        ...     Detection(template_name='a', detect_time=UTCDateTime(0),
        ...               no_chans=8, detect_val=4.5, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0),
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 10,
        ...               no_chans=8, detect_val=4.5, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0)])
        >>> family.plot(plot_grouped=True)  # doctest: +SKIP

        .. plot::

            from eqcorrscan.core.match_filter import Family, Template
            from eqcorrscan.core.match_filter import Detection
            from obspy import UTCDateTime
            family = Family(
                template=Template(name='a'), detections=[
                Detection(template_name='a', detect_time=UTCDateTime(0) + 200,
                          no_chans=8, detect_val=4.2, threshold=1.2,
                          typeofdet='corr', threshold_type='MAD',
                          threshold_input=8.0),
                Detection(template_name='a', detect_time=UTCDateTime(0),
                          no_chans=8, detect_val=4.5, threshold=1.2,
                          typeofdet='corr', threshold_type='MAD',
                          threshold_input=8.0),
                Detection(template_name='a', detect_time=UTCDateTime(0) + 10,
                          no_chans=8, detect_val=4.5, threshold=1.2,
                          typeofdet='corr', threshold_type='MAD',
                          threshold_input=8.0)])
            family.plot(plot_grouped=True)
        """
        cumulative_detections(
            detections=self.detections, plot_grouped=plot_grouped)

    def write(self, filename, format='tar'):
        """
        Write Family out, select output format.

        :type format: str
        :param format:
            One of either 'tar', 'csv', or any obspy supported
            catalog output.
        :type filename: str
        :param filename: Path to write file to.

        .. Note:: csv format will write out detection objects, all other
            outputs will write the catalog.  These cannot be rebuilt into
            a Family object.  The only format that can be read back into
            Family objects is the 'tar' type.

        .. Note:: csv format will append detections to filename, all others
            will overwrite any existing files.

        .. rubric:: Example

        >>> from eqcorrscan import Template, Detection
        >>> from obspy import read
        >>> family = Family(
        ...     template=Template(name='a', st=read()), detections=[
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 200,
        ...               no_chans=8, detect_val=4.2, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0),
        ...     Detection(template_name='a', detect_time=UTCDateTime(0),
        ...               no_chans=8, detect_val=4.5, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0),
        ...     Detection(template_name='a', detect_time=UTCDateTime(0) + 10,
        ...               no_chans=8, detect_val=4.5, threshold=1.2,
        ...               typeofdet='corr', threshold_type='MAD',
        ...               threshold_input=8.0)])
        >>> family.write('test_family')
        """
        from eqcorrscan.core.match_filter.party import Party

        Party(families=[self]).write(filename=filename, format=format)
        return

    def lag_calc(self, stream, pre_processed, shift_len=0.2, min_cc=0.4,
                 horizontal_chans=['E', 'N', '1', '2'], vertical_chans=['Z'],
                 cores=1, interpolate=False, plot=False, parallel=True,
                 process_cores=None):
        """
        Compute picks based on cross-correlation alignment.

        :type stream: obspy.core.stream.Stream
        :param stream:
            All the data needed to cut from - can be a gappy Stream.
        :type pre_processed: bool
        :param pre_processed:
            Whether the stream has been pre-processed or not to match the
            templates. See note below.
        :type shift_len: float
        :param shift_len:
            Shift length allowed for the pick in seconds, will be
            plus/minus this amount - default=0.2
        :type min_cc: float
        :param min_cc:
            Minimum cross-correlation value to be considered a pick,
            default=0.4.
        :type horizontal_chans: list
        :param horizontal_chans:
            List of channel endings for horizontal-channels, on which
            S-picks will be made.
        :type vertical_chans: list
        :param vertical_chans:
            List of channel endings for vertical-channels, on which P-picks
            will be made.
        :type cores: int
        :param cores:
            Number of cores to use in parallel processing, defaults to one.
        :type interpolate: bool
        :param interpolate:
            Interpolate the correlation function to achieve sub-sample
            precision.
        :type plot: bool
        :param plot:
            To generate a plot for every detection or not, defaults to False
        :type parallel: bool
        :param parallel: Turn parallel processing on or off.
        :type process_cores: int
        :param process_cores:
            Number of processes to use for pre-processing (if different to
            `cores`).

        :returns:
            Catalog of events with picks.  No origin information is included.
            These events can then be written out via
            :func:`obspy.core.event.Catalog.write`, or to Nordic Sfiles using
            :func:`eqcorrscan.utils.sfile_util.eventtosfile` and located
            externally.
        :rtype: obspy.core.event.Catalog

        .. Note::
            Note on pre-processing: You can provide a pre-processed stream,
            which may be beneficial for detections over large time periods
            (the stream can have gaps, which reduces memory usage).  However,
            in this case the processing steps are not checked, so you must
            ensure that all the template in the Party have the same sampling
            rate and filtering as the stream.
            If pre-processing has not be done then the data will be processed
            according to the parameters in the templates, in this case
            templates will be grouped by processing parameters and run with
            similarly processed data.  In this case, all templates do not have
            to have the same processing parameters.

        .. Note::
            Picks are corrected for the template pre-pick time.
        """
        from eqcorrscan.core.match_filter.party import Party

        cat = Party(families=[self]).lag_calc(
            stream=stream, pre_processed=pre_processed, shift_len=shift_len,
            min_cc=min_cc, horizontal_chans=horizontal_chans,
            vertical_chans=vertical_chans, cores=cores,
            interpolate=interpolate, plot=plot, parallel=parallel,
            process_cores=process_cores)
        return cat


def _write_family(family, filename):
    """
    Write a family to a csv file.

    :type family: :class:`eqcorrscan.core.match_filter.Family`
    :param family: Family to write to file
    :type filename: str
    :param filename: File to write to.
    """
    with open(filename, 'w') as f:
        for detection in family.detections:
            det_str = ''
            for key in detection.__dict__.keys():
                if key == 'event' and detection.__dict__[key] is not None:
                    value = str(detection.event.resource_id)
                elif key in ['threshold', 'detect_val', 'threshold_input']:
                    value = format(detection.__dict__[key], '.32f').rstrip('0')
                else:
                    value = str(detection.__dict__[key])
                det_str += key + ': ' + value + '; '
            f.write(det_str + '\n')
    return


def _read_family(fname, all_cat, template, encoding="UTF8",
                 estimate_origin=True):
    """
    Internal function to read csv family files.

    :type fname: str
    :param fname: Filename
    :return: list of Detection
    """
    detections = []
    with open(fname, 'rb') as _f:
        lines = _f.read().decode(encoding).splitlines()
    for line in lines:
        det_dict = {}
        gen_event = False
        for key_pair in line.rstrip().split(';'):
            key = key_pair.split(': ')[0].strip()
            value = key_pair.split(': ')[-1].strip()
            if key == 'event':
                if len(all_cat) == 0:
                    gen_event = True
                    continue
                el = [e for e in all_cat
                      if str(e.resource_id).split('/')[-1] == value][0]
                det_dict.update({'event': el})
            elif key == 'detect_time':
                det_dict.update(
                    {'detect_time': UTCDateTime(value)})
            elif key == 'chans':
                det_dict.update({'chans': ast.literal_eval(value)})
            elif key in ['template_name', 'typeofdet', 'id',
                         'threshold_type']:
                det_dict.update({key: value})
            elif key == 'no_chans':
                det_dict.update({key: int(float(value))})
            elif len(key) == 0:
                continue
            else:
                det_dict.update({key: float(value)})
        detection = Detection(**det_dict)
        if gen_event:
            detection._calculate_event(
                template=template, estimate_origin=estimate_origin)
        detections.append(detection)
    return detections


if __name__ == "__main__":
    import doctest

    doctest.testmod()
    # List files to be removed after doctest
    cleanup = ['test_family.tgz']
    for f in cleanup:
        if os.path.isfile(f):
            os.remove(f)
        elif os.path.isdir(f):
            shutil.rmtree(f)
