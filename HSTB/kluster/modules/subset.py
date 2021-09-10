import numpy as np
import xarray as xr
from copy import deepcopy
from typing import Union

import matplotlib.path as mpl_path
from pyproj import CRS, Transformer

from HSTB.kluster.xarray_helpers import slice_xarray_by_dim
from HSTB.kluster.modules.georeference import polygon_to_geohashes
from HSTB.kluster import kluster_variables


class FqprSubset:
    """
    Tools for building a subset, or a smaller piece of the larger Fqpr instance.

    fqpr = fully qualified ping record, the term for the datastore in kluster

    Processed fqpr_generation.Fqpr instance is passed in as argument
    """

    def __init__(self, fqpr):
        """

        Parameters
        ----------
        fqpr
            Fqpr instance to export from
        """
        self.fqpr = fqpr
        self.backup_fqpr = {}
        self.subset_mintime = 0
        self.subset_maxtime = 0

        self.ping_filter = None

    @property
    def is_subset(self):
        if self.backup_fqpr == {}:
            return False
        else:
            return True

    def subset_by_time(self, mintime: float = None, maxtime: float = None):
        """
        We save the line start/end time as an attribute within each raw_ping record.  Use this method to pull out
        just the data that is within the mintime/maxtime range (inclusive mintime, exclusive maxtime).  The class will
        then only have access to data within that time period.

        To return to the full original dataset, use restore_subset

        Parameters
        ----------
        mintime
            minimum time of the subset, if not provided and maxtime is, use the minimum time of the datasets
        maxtime
            maximum time of the subset, if not provided and mintime is, use the maximum time of the datasets
        """

        if mintime is None and maxtime is not None:
            mintime = np.min([rp.time.values[0] for rp in self.fqpr.multibeam.raw_ping])
        if maxtime is None and mintime is not None:
            maxtime = np.max([rp.time.values[-1] for rp in self.fqpr.multibeam.raw_ping])
        if mintime is None and maxtime is None:
            raise ValueError('subset_by_time: either mintime or maxtime must be provided to subset by time')

        if self.backup_fqpr != {}:
            self.restore_subset()
        self.subset_mintime = mintime
        self.subset_maxtime = maxtime
        self.backup_fqpr['raw_ping'] = [ping.copy() for ping in self.fqpr.multibeam.raw_ping]
        self.backup_fqpr['raw_att'] = self.fqpr.multibeam.raw_att.copy()

        slice_raw_ping = []
        for ra in self.fqpr.multibeam.raw_ping:
            slice_ra = slice_xarray_by_dim(ra, dimname='time', start_time=mintime, end_time=maxtime)
            slice_raw_ping.append(slice_ra)
        self.fqpr.multibeam.raw_ping = slice_raw_ping
        self.fqpr.multibeam.raw_att = slice_xarray_by_dim(self.fqpr.multibeam.raw_att, dimname='time', start_time=mintime, end_time=maxtime)
        if isinstance(self.fqpr.navigation, xr.Dataset):  # if self.navigation is a dataset, make a backup
            self.backup_fqpr['ppnav'] = self.fqpr.navigation.copy()
            self.fqpr.navigation = slice_xarray_by_dim(self.fqpr.navigation, dimname='time', start_time=mintime, end_time=maxtime)

    def restore_subset(self):
        """
        Restores the original data if subset_by_time has been run.
        """

        if self.backup_fqpr != {}:
            self.fqpr.multibeam.raw_ping = self.backup_fqpr['raw_ping']
            self.fqpr.multibeam.raw_att = self.backup_fqpr['raw_att']
            if 'ppnav' in self.backup_fqpr:
                self.fqpr.navigation = self.backup_fqpr['ppnav']
            self.backup_fqpr = {}
            self.subset_maxtime = 0
            self.subset_mintime = 0
        else:
            self.fqpr.logger.error('restore_subset: no subset found to restore from')
            raise ValueError('restore_subset: no subset found to restore from')

    def redo_subset(self):
        """
        Subset by the existing subset times, used after reload to get the subset back
        """
        if self.subset_mintime and self.subset_maxtime:
            self.subset_by_time(self.subset_mintime, self.subset_maxtime)

    def subset_variables(self, variable_selection: list, ping_times: Union[np.array, float, tuple] = None,
                         skip_subset_by_time: bool = False, filter_by_detection: bool = False):
        """
        Take specific variable names and return just those variables in a new xarray dataset.  If you provide ping_times,
        either as the minmax of a range or individual times, it will return the variables just within those times.

        Parameters
        ----------
        variable_selection
            variable names you want from the fqpr dataset
        ping_times
            time to select the dataset by, can either be an array of times (will use the min/max of the array to subset),
            a float for a single time, or a tuple of (min time, max time).  If None, will use the min/max of the dataset
        skip_subset_by_time
            if True, will not run the subset by time method
        filter_by_detection
            if True, will filter the dataset by the detection info flag = 2 (rejected by multibeam system)

        Returns
        -------
        xr.Dataset
            Dataset with the
        """

        if filter_by_detection and 'detectioninfo' not in variable_selection:
            variable_selection.append('detectioninfo')
        if not skip_subset_by_time:
            if ping_times is None:
                ping_times = (np.min([rp.time.values[0] for rp in self.fqpr.multibeam.raw_ping]),
                              np.max([rp.time.values[-1] for rp in self.fqpr.multibeam.raw_ping]))

            if isinstance(ping_times, float):
                min_time, max_time = ping_times, ping_times
            elif isinstance(ping_times, tuple):
                min_time, max_time = ping_times
            else:
                min_time, max_time = float(np.min(ping_times)), float(np.max(ping_times))

            self.subset_by_time(min_time, max_time)

        dataset_variables = {}
        maxbeams = 0
        times = np.concatenate([rp.time.values for rp in self.fqpr.multibeam.raw_ping]).flatten()
        systems = np.concatenate([[rp.system_identifier] * rp.time.shape[0] for rp in self.fqpr.multibeam.raw_ping]).flatten().astype(np.int32)
        for var in variable_selection:
            if self.fqpr.multibeam.raw_ping[0][var].ndim == 2:
                if self.fqpr.multibeam.raw_ping[0][var].dims == ('time', 'beam'):
                    dataset_variables[var] = (['time', 'beam'], np.concatenate([rp[var] for rp in self.fqpr.multibeam.raw_ping]))
                    newmaxbeams = self.fqpr.multibeam.raw_ping[0][var].shape[1]
                    if maxbeams and maxbeams != newmaxbeams:
                        raise ValueError('Found multiple max beam number values for the different ping datasets, {} and {}, beam shapes must match'.format(maxbeams, newmaxbeams))
                    else:
                        maxbeams = newmaxbeams
                else:
                    raise ValueError('Only time and beam dimensions are suppoted, found {} for {}'.format(self.fqpr.multibeam.raw_ping[0][var].dims, var))
            elif self.fqpr.multibeam.raw_ping[0][var].ndim == 1:
                if self.fqpr.multibeam.raw_ping[0][var].dims == ('time',):
                    dataset_variables[var] = (['time'], np.concatenate([rp[var] for rp in self.fqpr.multibeam.raw_ping]))
                else:
                    raise ValueError('Only time dimension is suppoted, found {} for {}'.format(self.fqpr.multibeam.raw_ping[0][var].dims, var))
            else:
                raise ValueError('Only 2 and 1 dimension variables are supported, {}} is {} dim'.format(var, self.fqpr.multibeam.raw_ping[0][var].ndim))

        dataset_variables['system_identifier'] = (['time'], systems)
        if maxbeams:  # when variables are a mix of time time/beam dimensions
            coords = {'time': times, 'beam': np.arange(maxbeams)}
        else:  # when variables are just time dimension
            coords = {'time': times}
        dset = xr.Dataset(dataset_variables, coords, attrs=deepcopy(self.fqpr.multibeam.raw_ping[0].attrs))
        dset = dset.sortby('time')

        if filter_by_detection:
            dset = filter_subset_by_detection(dset)
        if not skip_subset_by_time:
            self.restore_subset()

        return dset

    def subset_variables_by_line(self, variable_selection: list, line_names: Union[str, list] = None, ping_times: tuple = None,
                                 filter_by_detection: bool = False):
        """
        Apply subset_variables to get the data split up into lines for the variable_selection provided

        Parameters
        ----------
        variable_selection
            variable names you want from the fqpr dataset
        line_names
            if provided, only returns data for the line(s), otherwise, returns data for all lines
        ping_times
            time to select the dataset by, must be a tuple of (min time, max time) in utc seconds.  If None, will use
            the full min/max time of the dataset
        filter_by_detection
            if True, will filter the dataset by the detection info flag = 2 (rejected by multibeam system)

        Returns
        -------
        dict
            dict of {linename: xr.Dataset} for each line name in the dataset (or just for the line names provided
            if you provide line names)
        """

        mfiles = self.fqpr.return_line_dict(line_names=line_names, ping_times=ping_times)

        return_data = {}
        for linename in mfiles.keys():
            starttime, endtime = mfiles[linename]
            dset = self.subset_variables(variable_selection, ping_times=(starttime, endtime), skip_subset_by_time=False,
                                         filter_by_detection=filter_by_detection)
            return_data[linename] = dset
        return return_data

    def soundings_by_poly(self, geo_polygon: np.ndarray, proj_polygon: np.ndarray):
        """
        Return soundings and sounding attributes that are within the box formed by the provided coordinates.

        Parameters
        ----------
        geo_polygon
            (N, 2) array of points that make up the selection polygon, (x, y) in Fqpr CRS
        proj_polygon
            (N, 2) array of points that make up the selection polygon, (longitude, latitude) in Fqpr CRS

        Returns
        -------
        list
            list of 1d numpy arrays for the head index of the soundings in the box
        list
            list of 1d numpy arrays for the x coordinate of the soundings in the box
        list
            list of 1d numpy arrays for the y coordinate of the soundings in the box
        list
            list of 1d numpy arrays for the z coordinate of the soundings in the box
        list
            list of 1d numpy arrays for the tvu value of the soundings in the box
        list
            list of 1d numpy arrays for the rejected flag of the soundings in the box
        list
            list of 1d numpy arrays for the time of the soundings in the box
        list
            list of 1d numpy arrays for the beam number of the soundings in the box
        """

        head = []
        x = []
        y = []
        z = []
        tvu = []
        rejected = []
        pointtime = []
        beam = []
        self.ping_filter = []
        polypath = mpl_path.Path(proj_polygon)
        for cnt, rp in enumerate(self.fqpr.multibeam.raw_ping):
            if 'z' not in rp:
                continue
            insidedata, intersectdata = filter_subset_by_polygon(rp, geo_polygon)
            base_filter = np.zeros(rp.x.shape[0] * rp.x.shape[1], dtype=bool)
            if insidedata or intersectdata:
                # ping_dataset = rp.stack({'sounding': ('time', 'beam')})
                if insidedata:
                    for mline, mdata in insidedata.items():
                        linemask, startidx, endidx, starttime, endtime = mdata
                        slice_pd = slice_xarray_by_dim(rp, dimname='time', start_time=starttime, end_time=endtime)
                        base_filter[startidx:endidx] = linemask
                        stacked_slice = slice_pd.stack({'sounding': ('time', 'beam')})
                        xval = stacked_slice.x[linemask].values
                        head.append(np.full_like(xval, cnt, dtype=np.int8))
                        x.append(xval)
                        y.append(stacked_slice.y[linemask].values)
                        z.append(stacked_slice.z[linemask].values)
                        tvu.append(stacked_slice.tvu[linemask].values)
                        rejected.append(stacked_slice.detectioninfo[linemask].values)
                        pointtime.append(stacked_slice.time[linemask].values)
                        beam.append(stacked_slice.beam[linemask].values)
                if intersectdata:
                    for mline, mdata in intersectdata.items():
                        linemask, startidx, endidx, starttime, endtime = mdata
                        # only brute force check those points that are in intersecting geohash regions
                        slice_pd = slice_xarray_by_dim(rp, dimname='time', start_time=starttime, end_time=endtime)
                        xintersect, yintersect = np.ravel(slice_pd.x), np.ravel(slice_pd.y)
                        filt = polypath.contains_points(np.c_[xintersect[linemask], yintersect[linemask]])
                        base_filter[startidx:endidx][linemask] = filt
                        stacked_slice = slice_pd.stack({'sounding': ('time', 'beam')})
                        xval = stacked_slice.x[linemask][filt].values
                        head.append(np.full_like(xval, cnt, dtype=np.int8))
                        x.append(xval)
                        y.append(stacked_slice.y[linemask][filt].values)
                        z.append(stacked_slice.z[linemask][filt].values)
                        tvu.append(stacked_slice.tvu[linemask][filt].values)
                        rejected.append(stacked_slice.detectioninfo[linemask][filt].values)
                        pointtime.append(stacked_slice.time[linemask][filt].values)
                        beam.append(stacked_slice.beam[linemask][filt].values)
            self.ping_filter.append(base_filter)
        return head, x, y, z, tvu, rejected, pointtime, beam

    def swaths_by_poly(self, polygon: np.ndarray):
        """
        Return soundings and sounding attributes that are a part of swaths within the box formed by the provided
        coordinates.  Only returns complete swaths.

        Parameters
        ----------
        polygon
            (N, 2) array of points that make up the selection polygon, (longitude, latitude) in geographic coords

        Returns
        -------
        list
            list of 1d numpy arrays for the head index of the soundings in the box
        list
            list of 1d numpy arrays for the acrosstrack coordinate of the soundings in the box
        list
            list of 1d numpy arrays for the y coordinate of the soundings in the box
        list
            list of 1d numpy arrays for the z coordinate of the soundings in the box
        list
            list of 1d numpy arrays for the tvu value of the soundings in the box
        list
            list of 1d numpy arrays for the rejected flag of the soundings in the box
        list
            list of 1d numpy arrays for the time of the soundings in the box
        list
            list of 1d numpy arrays for the beam number of the soundings in the box
        """

        head = []
        x = []
        y = []
        z = []
        tvu = []
        rejected = []
        pointtime = []
        beam = []
        self.ping_filter = []
        nv = self.fqpr.multibeam.raw_ping[0]
        polypath = mpl_path.Path(polygon)
        filt = polypath.contains_points(np.vstack([nv.longitude.values, nv.latitude.values]))
        time_sel = nv.time.where(filt, drop=True).values

        if time_sel.any():
            # if selecting swaths of multiple lines, there will be time gaps
            time_gaps = np.where(np.diff(time_sel) > 1)[0]
            if time_gaps.any():
                time_segments = []
                strt = 0
                for gp in time_gaps:
                    time_segments.append(time_sel[strt:gp + 1])
                    strt = gp + 1
                time_segments.append(time_sel[strt:])
            else:
                time_segments = [time_sel]

            for timeseg in time_segments:
                seg_filter = []
                mintime, maxtime = timeseg.min(), timeseg.max()
                for cnt, rp in enumerate(self.fqpr.multibeam.raw_ping):
                    ping_filter = np.logical_and(rp.time >= mintime, rp.time <= maxtime)
                    seg_filter.append([mintime, maxtime, ping_filter])
                    if ping_filter.any():
                        pings = rp.where(ping_filter, drop=True)
                        head.append(np.full_like(pings.acrosstrack.values.ravel(), cnt, dtype=np.int8))
                        x.append(pings.acrosstrack.values.ravel())
                        y.append(pings.alongtrack.values.ravel())
                        z.append(pings.z.values.ravel())
                        tvu.append(pings.tvu.values.ravel())
                        rejected.append(pings.detectioninfo.values.ravel())
                        # have to get time for each beam to then make the filter work
                        pointtime.append((pings.time.values[:, np.newaxis] * np.ones_like(pings.x)).ravel())
                        beam.append((pings.beam.values[np.newaxis, :] * np.ones_like(pings.x, dtype=np.int32)).ravel())
                self.ping_filter.append(seg_filter)
        return head, x, y, z, tvu, rejected, pointtime, beam

    def return_soundings_in_polygon(self, polygon: np.ndarray, geographic: bool = True, full_swath: bool = False):
        """
        Using provided coordinates (in either horizontal_crs projected or geographic coordinates), return the soundings
        and sounding attributes for all soundings within the coordinates.

        Parameters
        ----------
        polygon
            (N, 2) array of points that make up the selection polygon,  (longitude, latitude) in degrees
        geographic
            If True, the coordinates provided are geographic (latitude/longitude)
        full_swath
            If True, only returns the full swaths whose navigation is within the provided box

        Returns
        -------
        np.array
            1d numpy array for the head index of the soundings in the box
        np.array
            1d numpy array for the x coordinate of the soundings in the box
        np.array
            1d numpy array for the y coordinate of the soundings in the box
        np.array
            1d numpy array for the z coordinate of the soundings in the box
        np.array
            1d numpy array for the tvu value of the soundings in the box
        np.array
            1d numpy array for the rejected flag of the soundings in the box
        np.array
            1d numpy array for the time of the soundings in the box
        np.array
            1d numpy array for the beam number of the soundings in the box
        """

        if 'horizontal_crs' not in self.fqpr.multibeam.raw_ping[0].attrs or 'z' not in self.fqpr.multibeam.raw_ping[0].variables.keys():
            raise ValueError('Georeferencing has not been run yet, you must georeference before you can get soundings')
        if full_swath and not geographic:
            raise NotImplementedError('full swath mode can only be used in geographic mode')

        if not geographic:
            proj_polygon = polygon
            trans = Transformer.from_crs(CRS.from_epsg(self.fqpr.multibeam.raw_ping[0].horizontal_crs),
                                         CRS.from_epsg(kluster_variables.epsg_wgs84), always_xy=True)
            polyx, polyy = trans.transform(polygon[:, 0], polygon[:, 1])
            geo_polygon = np.c_[polyx, polyy]
        else:
            geo_polygon = polygon
            trans = Transformer.from_crs(CRS.from_epsg(kluster_variables.epsg_wgs84),
                                         CRS.from_epsg(self.fqpr.multibeam.raw_ping[0].horizontal_crs), always_xy=True)
            polyx, polyy = trans.transform(polygon[:, 0], polygon[:, 1])
            proj_polygon = np.c_[polyx, polyy]

        if not full_swath:
            head, x, y, z, tvu, rejected, pointtime, beam = self.soundings_by_poly(geo_polygon, proj_polygon)
        else:
            head, x, y, z, tvu, rejected, pointtime, beam = self.swaths_by_poly(geo_polygon)

        if len(x) > 1:
            head = np.concatenate(head)
            x = np.concatenate(x)
            y = np.concatenate(y)
            z = np.concatenate(z)
            tvu = np.concatenate(tvu)
            rejected = np.concatenate(rejected)
            pointtime = np.concatenate(pointtime)
            beam = np.concatenate(beam)
        elif len(x) == 1:
            head = head[0]
            x = x[0]
            y = y[0]
            z = z[0]
            tvu = tvu[0]
            rejected = rejected[0]
            pointtime = pointtime[0]
            beam = beam[0]
        else:
            head = None
            x = None
            y = None
            z = None
            tvu = None
            rejected = None
            pointtime = None
            beam = None
        return head, x, y, z, tvu, rejected, pointtime, beam

    def set_variable_by_filter(self, variable_name: str, new_data: Union[np.array, float, int, str], selected_index: list = None):
        """
        ping_filter is set upon selecting points in 2d/3d in Kluster.  See return_soundings_in_polygon.  Here we can take
        those points and set one of the variables with new data.  Optionally, you can include a selected_index that is a list
        of flattened indices to points in the ping_filter that you want to super-select.  See kluster_main.set_pointsview_points_status

        new data are set in memory and saved to disk

        Parameters
        ----------
        variable_name
            name of the variable to set, i.e. 'detectioninfo'
        new_data
            new data to set to the soundings selected by ping_filter for this variable.  Generally used for setting a new
            sounding flag in detectioninfo, where all selected soundings would have new_data = 1 or 2
        selected_index
            super_selection of the ping_filter selection, done in points_view currently when selecting with the mouse
        """

        for cnt, rp in enumerate(self.fqpr.multibeam.raw_ping):
            ping_filter = self.fqpr.subset.ping_filter[cnt]
            data_var = rp[variable_name]
            if selected_index:
                rp_points_idx = selected_index[cnt]
                point_idx = np.unravel_index(np.where(ping_filter)[0][rp_points_idx], data_var.shape)
            else:
                point_idx = np.unravel_index(np.where(ping_filter)[0], data_var.shape)

            unique_time_vals, utime_index = np.unique(point_idx[0], return_inverse=True)
            rp_detect = data_var.isel(time=unique_time_vals).load()
            rp_detect_vals = rp_detect.values
            rp_detect_vals[utime_index, point_idx[1]] = new_data
            rp_detect[:] = rp_detect_vals
            self.fqpr.write('ping', [rp_detect.to_dataset()], time_array=[rp_detect.time], sys_id=rp.system_identifier,
                            skip_dask=True)


def filter_subset_by_detection(ping_dataset: xr.Dataset):
    """
    Get only the non-rejected soundings.  Additionally, drop all the NaN values where we did not get a georeferenced
    answer.  Returns the dataset stacked (sounding=(time, beam)) so all variables are one dimensional.  We do
    this to make the filtering work, as it results in a non square array.

    Parameters
    ----------
    ping_dataset
        one of the raw_ping datasets

    Returns
    -------
    xr.Dataset
        1dim stacked ping dataset
    """

    # get to a 1dim space for filtering
    ping_dataset = ping_dataset.stack({'sounding': ('time', 'beam')})

    # first drop all nans, all the georeference variables (xyz) should have NaNs in the same place
    if 'x' in ping_dataset.variables:
        nan_mask = ~np.isnan(ping_dataset['x'])
        ping_dataset = ping_dataset.isel(sounding=nan_mask)
    elif 'y' in ping_dataset.variables:
        nan_mask = ~np.isnan(ping_dataset['y'])
        ping_dataset = ping_dataset.isel(sounding=nan_mask)
    elif 'z' in ping_dataset.variables:
        nan_mask = ~np.isnan(ping_dataset['z'])
        ping_dataset = ping_dataset.isel(sounding=nan_mask)
    else:  # no georeferenced data found
        print('Warning: Unable to filter by sounding flag, no georeferenced data found')
        pass

    # rejected soundings are where detectioninfo=2
    dinfo = ping_dataset.detectioninfo
    valid_detections = dinfo != 2
    ping_dataset = ping_dataset.isel(sounding=valid_detections)
    ping_dataset = ping_dataset.drop_vars('detectioninfo')
    return ping_dataset


def filter_subset_by_polygon(ping_dataset: xr.Dataset, polygon: np.array):
    """
    Given the provided polygon coordinates, return the part of the ping dataset that is completely within
    the polygon and the part of the dataset that intersects with the polygon

    Parameters
    ----------
    ping_dataset
        one of the multibeam.raw_ping datasets, containing the ping variables
    polygon
        coordinates of a polygon ex: np.array([[lon1, lat1], [lon2, lat2], ...]), first and last coordinate
        must be the same

    Returns
    -------
    xr.Dataset
        1dim flattened bool mask for soundings in a geohash that is completely within the polygon
    xr.Dataset
        1dim flattened bool mask for soundings in a geohash that intersects with the polygon
    """

    if 'geohash' in ping_dataset.variables:
        if 'geohashes' in ping_dataset.attrs:
            inside_mask_lines = {}
            intersect_mask_lines = {}
            gprecision = int(ping_dataset.geohash.dtype.str[2:])  # ex: dtype='|S7', precision=7
            innerhash, intersecthash = polygon_to_geohashes(polygon, precision=gprecision)
            for mline, mhashes in ping_dataset.attrs['geohashes'].items():
                linestart, lineend = ping_dataset.attrs['multibeam_files'][mline]
                mhashes = [x.encode() for x in mhashes]
                inside_geohash = [x for x in innerhash if x in mhashes]
                intersect_geohash = [x for x in intersecthash if x in mhashes]
                if inside_geohash or intersect_geohash:
                    slice_pd = slice_xarray_by_dim(ping_dataset, dimname='time', start_time=linestart, end_time=lineend)
                    ghash = np.ravel(slice_pd.geohash)
                    filt_start = int(np.where(ping_dataset.time == slice_pd.time[0])[0]) * ping_dataset.geohash.shape[1]
                    filt_end = filt_start + ghash.shape[0]
                    if inside_geohash:
                        linemask = np.in1d(ghash, inside_geohash)
                        inside_mask_lines[mline] = [linemask, filt_start, filt_end, linestart, lineend]
                    if intersect_geohash:
                        linemask = np.in1d(ghash, intersect_geohash)
                        intersect_mask_lines[mline] = [linemask, filt_start, filt_end, linestart, lineend]
            return inside_mask_lines, intersect_mask_lines
        else:  # treat dataset as if all the data needs to be brute force checked, i.e. all data intersects with polygon
            print('Warning: Unable to filter by polygon, cannot find the "geohashes" attribute in the ping record')
            return None, None
    else:
        print('Warning: Unable to filter by polygon, geohash variable not found')
        return None, None