"""
Advanced subspace tutorial to show some of the capabilities of the method.

This example uses waveforms from a known earthquake sequence (in the Wairarapa
region north of Wellington, New Zealand). The catalogue locations etc can
be downloaded from this link:

http://quakesearch.geonet.org.nz/services/1.0.0/csv?bbox=175.37956,-40.97912,175.53097,-40.84628&startdate=2015-7-18T2:00:00&enddate=2016-7-18T3:00:00

"""

def run_tutorial(plot=True):
    """
    Run the tutorial.

    :return: detections
    """
    # We are going to use data from the GeoNet (New Zealand) catalogue. GeoNet
    # do not implement the full FDSN system yet, so we have a hack to get
    # around this.  It is not strictly part of EQcorrscan, so we haven't
    # included it here, but you can find it in the tutorials directory of the
    # github repository
    import obspy
    if int(obspy.__version__.split('.')[0]) >= 1:
        from obspy.clients.fdsn import Client
    else:
        from obspy.fdsn import Client
    from eqcorrscan.tutorials.get_geonet_events import get_geonet_events
    from obspy import UTCDateTime, Catalog
    from eqcorrscan.utils.catalog_utils import filter_picks
    from eqcorrscan.utils.clustering import space_cluster, SVD, SVD_2_stream
    from eqcorrscan.utils.pre_processing import shortproc
    from eqcorrscan.utils.plotting import cumulative_detections
    from eqcorrscan.core import template_gen, subspace, match_filter

    cat = get_geonet_events(minlat=-40.98, maxlat=-40.85, minlon=175.4,
                            maxlon=175.5, startdate=UTCDateTime(2016, 5, 1),
                            enddate=UTCDateTime(2016, 5, 30))
    # This gives us a catalog of 89 events - it takes a while to download all
    # the information, so give it a bit!
    # We will filter the picks simply to reduce the cost - you don't have to!
    cat = filter_picks(catalog=cat, top_n_picks=5)
    # Then remove events with fewer than three picks
    cat = Catalog([event for event in cat if len(event.picks) >= 3])
    # In this tutorial we will only work on one cluster, defined spatially.
    # You can work on multiple clusters, or try to whole set.
    clusters = space_cluster(catalog=cat, d_thresh=2, show=False)
    # We will work on the largest cluster
    cluster = sorted(clusters, key=lambda c: len(c))[-1]
    # This cluster contains 42 events, we will now generate simple waveform
    # templates for each of them
    templates = template_gen.from_client(catalog=cluster,
                                         client_id='GEONET',
                                         lowcut=2.0, highcut=9.0,
                                         samp_rate=20.0, filt_order=4,
                                         length=3.0, prepick=0.15,
                                         swin='all', process_len=3600,
                                         debug=0, plot=False)
    # We should note here that the templates are not perfectly aligned, but
    # they are close enough for us to compute a useful singular-value
    # decomposition.
    SVectors, SValues, Uvectors, stachans = SVD(stream_list=templates)
    # Convert to streams, which you can plot - we also need them for
    # subspace_detect - we chose here to use a detector of order five (k).
    detector = SVD_2_stream(SVectors=SVectors, stachans=stachans, k=5,
                            sampling_rate=20.0)
    # We will look for detections on the 13th of May 2016 between midday and 3pm
    t1 = UTCDateTime(2016, 5, 13, 12)
    t2 = t1 + 10800
    bulk_info = [('NZ', stachan.split('.')[0], '*',
                  stachan.split('.')[1][0] + '?' + stachan.split('.')[1][-1],
                  t1, t2) for stachan in stachans]
    client = Client('GEONET')
    st = client.get_waveforms_bulk(bulk_info)
    st.merge().detrend('simple').trim(starttime=t1, endtime=t2)
    st = shortproc(st=st, highcut=9, lowcut=2, filt_order=4, samp_rate=20,
                   parallel=True)
    detections = subspace.subspace_detect(detector_names=['subspace_detector'],
                                          detector_list=[detector], st=st,
                                          threshold=0.25,
                                          threshold_type='absolute',
                                          trig_int=6, plotvar=False, cores=4)
    # We can compare these detections to those obtained by matched-filtering
    template_names = [str(i) for i in range(len(templates))]
    match_dets = match_filter.match_filter(template_names=template_names,
                                           template_list=templates, st=st,
                                           threshold=8, threshold_type='MAD',
                                           trig_int=6, plotvar=False, cores=4)
    # We can visualise the differences quickly
    for det in match_dets:
        det.template_name = 'match_filter'
    if plot:
        cumulative_detections(detections=detections + match_dets)
    # We obviously detect different things with the subspace detector and the
    # matched-filter technique.
    return detections


if __name__ == '__main__':
    run_tutorial()
