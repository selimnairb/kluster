import os
import xarray as xr
import numpy as np
from dask.distributed import Client
from typing import Union

from HSTB.kluster.xarray_conversion import BatchRead
from HSTB.kluster.fqpr_generation import Fqpr
from HSTB.kluster.fqpr_visualizations import FqprVisualizations
from HSTB.kluster.fqpr_surface import BaseSurface


def perform_all_processing(filname: str, navfiles: list = None, outfold: str = None, coord_system: str = 'NAD83',
                           vert_ref: str = 'waterline', **kwargs):
    """
    Use fqpr_generation to process multibeam data on the local cluster and generate a sound velocity corrected,
    georeferenced xyz with uncertainty in csv files in the provided output folder.

    Parameters
    ----------
    filname
        either a list of .all file paths, a single .all file path or a path to a directory with .all files
    navfiles
        list of postprocessed navigation file paths.  If provided, expects either a log file or
        weekstart_year/weekstart_week/override_datum arguments, see import_navigation
    outfold
        full file path to a directory you want to contain all the zarr folders.  Will create this folder
        if it does not exist.
    coord_system
        a valid datum identifier that pyproj CRS will accept
    vert_ref
        the vertical reference point, one of ['ellipse', 'vessel', 'waterline']

    Returns
    -------
    Fqpr
        Fqpr object containing processed data
    """

    fqpr_inst = convert_multibeam(filname, outfold)
    if navfiles is not None:
        fqpr_inst = import_navigation(fqpr_inst, navfiles, **kwargs)
    fqpr_inst = process_multibeam(fqpr_inst, coord_system=coord_system, vert_ref=vert_ref)
    return fqpr_inst


def convert_multibeam(filname: str, outfold: str = None, client: Client = None, auto_append: bool = False):
    """
    Use fqpr_generation to process multibeam data on the local cluster and generate a new Fqpr instance saved to the
    provided output folder.

    Parameters
    ----------
    filname
        either a list of .all file paths, a single .all file path or a path to a directory with .all files
    outfold
        full file path to a directory you want to contain all the zarr folders.  Will create this folder if it does
        not exist.  If not provided will automatically create folder next to lines.
    client
        if you have already created a Client, pass it in here to use it
    auto_append
        set if you want to append to an existing zarr datastore, ask for this explicitly because it is currently a bit
        dangerous, will cause problems if you mix vessels or lines are added out of order

    Returns
    -------
    Fqpr
        Fqpr containing converted source data
    """

    mbes_read = BatchRead(filname, dest=outfold, client=client, auto_append=auto_append)
    fqpr_inst = Fqpr(mbes_read)
    fqpr_inst.read_from_source()
    return fqpr_inst


def import_navigation(fqpr_inst: Fqpr, navfiles: list, errorfiles: list = None, logfiles: list = None,
                      weekstart_year: int = None, weekstart_week: int = None, override_datum: str = None,
                      override_grid: str = None, override_zone: str = None, override_ellipsoid: str = None,
                      max_gap_length: float = 1.0):
    """
    Convenience function for importing post processed navigation from sbet/smrmsg files, for use in georeferencing
    xyz data.  Converted attitude must exist before importing navigation, timestamps are used to figure out what
    part of the new nav to keep.

    Parameters
    ----------
    fqpr_inst
        Fqpr instance containing converted data (converted data must exist for the import to work)
    navfiles:
        list of postprocessed navigation file paths
    errorfiles
        list of postprocessed error file paths.  If provided, must be same number as nav files
    logfiles
        list of export log file paths associated with navfiles.  If provided, must be same number as nav files
    weekstart_year
        if you aren't providing a logfile, must provide the year of the sbet here
    weekstart_week
        if you aren't providing a logfile, must provide the week of the sbet here
    override_datum
        provide a string datum identifier if you want to override what is read from the log or you don't have a log,
        ex: 'NAD83 (2011)'
    override_grid
        provide a string grid identifier if you want to override what is read from the log or you don't have a log,
        ex: 'Universal Transverse Mercator'
    override_zone
        provide a string zone identifier if you want to override what is read from the log or you don't have a log,
        ex: 'UTM North 20 (66W to 60W)'
    override_ellipsoid
        provide a string ellipsoid identifier if you want to override what is read from the log or you don't have a
        log, ex: 'GRS80'
    max_gap_length
        maximum allowable gap in the sbet in seconds, excluding gaps found in raw navigation

    Returns
    -------
    Fqpr
        Fqpr passed in with additional post processed navigation
    """

    fqpr_inst.import_post_processed_navigation(navfiles, errorfiles=errorfiles, logfiles=logfiles,
                                               weekstart_year=weekstart_year, weekstart_week=weekstart_week,
                                               override_datum=override_datum, override_grid=override_grid,
                                               override_zone=override_zone, override_ellipsoid=override_ellipsoid,
                                               max_gap_length=max_gap_length)
    return fqpr_inst


def process_multibeam(fqpr_inst: Fqpr, run_orientation: bool = True, run_beam_vec: bool = True, run_svcorr: bool = True,
                      run_georef: bool = True, svcasts: list = None, use_epsg: bool = False, use_coord: bool = True,
                      epsg: int = None, coord_system: str = 'NAD83', vert_ref: str = 'waterline'):
    """
    Use fqpr_generation to process already converted data on the local cluster and generate sound velocity corrected,
    georeferenced soundings in the same data store as the converted data.

    Parameters
    ----------
    fqpr_inst
        Fqpr instance, must contain converted data
    run_orientation
        perform the get_orientation_vectors step
    run_beam_vec
        perform the get_beam_pointing_vectors step
    run_svcorr
        perform the sv_correct step
    run_georef
        perform the georef_xyz step
    svcasts
        optional list of paths to svp cast files, no need to include if using casts in multibeam file
    use_epsg
        if True, will use the epsg code to build the CRS to use
    use_coord
        if True, will use the coord_system parameter and autodetect UTM zone
    epsg
        epsg code, used if use_epsg is True
    coord_system
        coord system identifier, anything that pyproj supports can be used here, will be used if use_coord is True
    vert_ref
        the vertical reference point, one of ['ellipse', 'vessel', 'waterline']

    Returns
    -------
    Fqpr
        Fqpr passed in with processed xyz soundings
    """

    if not use_epsg:
        epsg = None  # epsg is given priority, so if you don't want to use it, set it to None here
    if not use_coord and not use_epsg and run_georef:
        print('process_multibeam: please select either use_coord or use_epsg to process')

    fqpr_inst.construct_crs(epsg=epsg, datum=coord_system, projected=True)
    if run_orientation:
        fqpr_inst.get_orientation_vectors()
    if run_beam_vec:
        fqpr_inst.get_beam_pointing_vectors()
    if run_svcorr:
        fqpr_inst.sv_correct(add_cast_files=svcasts)
    if run_georef:
        fqpr_inst.georef_xyz(vert_ref=vert_ref)
        fqpr_inst.export_pings_to_dataset()
    return fqpr_inst


def process_and_export_soundings(filname: str, outfold: str = None, coord_system: str = 'NAD83', vert_ref: str = 'waterline'):
    """
    Use fqpr_generation to process multibeam data on the local cluster and generate a sound velocity corrected,
    georeferenced xyz with uncertainty in csv files in the provided output folder.

    Parameters
    ----------
    outfold
        path to output folder where you want the csv files to go.  If None, will be the same folder that you've
        converted your raw data to.
    filname
        either a list of .all file paths, a single .all file path or a path to a directory with .all files
    coord_system
        a valid datum identifier that pyproj CRS will accept
    vert_ref
        the vertical reference point, one of ['ellipse', 'vessel', 'waterline']

    Returns
    -------
    Fqpr
        Fqpr object containing processed xyz soundings
    """

    fqpr_inst = perform_all_processing(filname, outfold=outfold, coord_system=coord_system, vert_ref=vert_ref)
    fqpr_inst.export_pings_to_file()
    return fqpr_inst


def return_georef_xyz(filname: str, coord_system: str = 'NAD83', vert_ref: str = 'waterline'):
    """
    Using fqpr_generation, convert and sv correct multibeam file (or directory of files) and return the georeferenced
    xyz soundings.

    Parameters
    ----------
    filname
        multibeam file path or directory path of multibeam files
    coord_system
        a valid datum identifier that pyproj CRS will accept
    vert_ref
        the vertical reference point, one of ['ellipse', 'vessel', 'waterline']

    Returns
    -------
    Fqpr
        Fqpr object containing processed xyz soundings
    np.array
        2d numpy array (time, beam) of the alongtrack offsets
    np.array
        2d numpy array (time, beam) of the acrosstrack offsets
    np.array
        2d numpy array (time, beam) of the depth offsets
    np.array
        numpy array of unique times of pings
    """

    fqpr_inst = perform_all_processing(filname, coord_system=coord_system, vert_ref=vert_ref)
    u_tms = fqpr_inst.return_unique_times_across_sectors()
    dats, ids, tms = fqpr_inst.reform_2d_vars_across_sectors_at_time(['x', 'y', 'z', 'unc'], u_tms)
    x, y, z, unc = dats

    return fqpr_inst, x, y, z, unc, ids, tms


def reload_data(converted_folder: str, require_raw_data: bool = True, skip_dask: bool = False):
    """
    Pick up from a previous session.  Load in all the data that exists for the session using the provided
    converted_folder.  Expects there to be fqpr generated zarr datastore folders in this folder.

    os.listdir(r'C:/data_dir/converted_093926')\n
    ['attitude.zarr', 'soundings.zarr', 'navigation.zarr', 'ping_389_1_270000.zarr', 'ping_389_1_290000.zarr',
    'ping_394_1_310000.zarr', 'ping_394_1_330000.zarr']\n
    fqpr = reload_data(r'C:/data_dir/converted_093926')

    Parameters
    ----------
    converted_folder
        path to the parent folder containing all the zarr data store folders
    require_raw_data
        if True, raise exception if you can't find the raw data
    skip_dask
        if True, will not start/find the dask client.  Only use this if you are just reading attribution

    Returns
    -------
    Fqpr
        Fqpr object reloaded from disk
    """

    final_paths = return_processed_data_folders(converted_folder)
    if (require_raw_data and final_paths['ping'] and final_paths['attitude'] and final_paths['navigation']) or (final_paths['ping'] or final_paths['soundings']):
        mbes_read = BatchRead(None, skip_dask=skip_dask)
        mbes_read.final_paths = final_paths
        mbes_read.read_from_zarr_fils(final_paths['ping'], final_paths['attitude'], final_paths['navigation'], final_paths['logfile'])
        fqpr_inst = Fqpr(mbes_read)
        fqpr_inst.logger.info('****Reloading from file {}****'.format(converted_folder))
        fqpr_inst.source_dat.xyzrph = fqpr_inst.source_dat.raw_ping[0].xyzrph
        fqpr_inst.source_dat.tpu_parameters = fqpr_inst.source_dat.raw_ping[0].tpu_parameters
        fqpr_inst.generate_starter_orientation_vectors(None, None)
        if 'xyz_crs' in fqpr_inst.source_dat.raw_ping[0].attrs:
            fqpr_inst.construct_crs(epsg=fqpr_inst.source_dat.raw_ping[0].attrs['xyz_crs'])
        try:
            fqpr_inst.soundings_path = final_paths['soundings'][0]
            fqpr_inst.reload_soundings_records(skip_dask=skip_dask)
        except IndexError:
            print('No soundings dataset found')
        try:
            fqpr_inst.ppnav_path = final_paths['ppnav'][0]
            fqpr_inst.reload_ppnav_records(skip_dask=skip_dask)
        except IndexError:
            print('No postprocessed navigation data found')
        fqpr_inst.client = mbes_read.client
    else:
        # not a valid zarr datastore
        print('reload_data: Unable to open FqprProject {}'.format(converted_folder))
        return None

    if fqpr_inst is not None:
        fqpr_inst.logger.info('Successfully reloaded\n'.format(converted_folder))
    return fqpr_inst


def return_svcorr_xyz(filname: str, outfold: str = None, visualizations: bool = True):
    """
    Using fqpr_generation, convert and sv correct multibeam file (or directory of files) and return the sound velocity
    corrected xyz soundings.

    Parameters
    ----------
    filname
        multibeam file path or directory path of multibeam files
    outfold
        full file path to a directory you want to contain all the zarr folders.  Will create this folder if it does not
        exist.
    visualizations
        True if you want the matplotlib animations as well

    Returns
    -------
    Fqpr
        Fqpr object containing svcorrected offsets
    FqprVisualizations
        FqprVisualizations object, returned here to keep the animations alive
    np.array
        2d numpy array (time, beam) of the alongtrack offsets
    np.array
        2d numpy array (time, beam) of the acrosstrack offsets
    np.array
        2d numpy array (time, beam) of the depth offsets
    np.array
        numpy array of unique times of pings
    """

    fqpr_inst = convert_multibeam(filname, outfold)
    fqpr_inst.get_orientation_vectors()
    fqpr_inst.get_beam_pointing_vectors()
    fqpr_inst.sv_correct()

    fqv = None
    if visualizations:
        fqv = FqprVisualizations(fqpr_inst)
        fqv.visualize_beam_pointing_vectors(corrected=False)
        fqv.visualize_orientation_vector()

    u_tms = fqpr_inst.return_unique_times_across_sectors()
    dats, ids, tms = fqpr_inst.reform_2d_vars_across_sectors_at_time(['alongtrack', 'acrosstrack', 'depthoffset'], u_tms)
    x, y, z = dats

    return fqpr_inst, fqv, x, y, z, tms


def generate_new_surface(fqpr_inst: Union[Fqpr, list], resolution: float = 1.0, method: str = 'linear',
                         soundings_per_node: int = 5, output_path: str = None, client: Client = None):
    """
    Using the fqpr_surface BaseSurface class, generate a new single resolution surface with the given resolution for
    the provided converted fqpr data.

    If fqpr_inst is provided and is not a list, generates a surface based on that specific fqpr converted instance.

    If fqpr_inst provided is a list of fqpr instances, will concatenate these instances and build a single surface.

    Returns an instance of the surface class and optionally saves the surface to disk.

    | fqpr = reload_data('C:/data_directory/converted')
    | # generate a new 8 meter surface using the default linear interpolation and the
    | # dask client that was created on reload
    | surf = generate_new_surface(fqpr, resolution=8.0, client=fqpr.client)

    Parameters
    ----------
    fqpr_inst
        instance or list of instances of fqpr_generation.Fqpr class that contains generated soundings data, see
        perform_all_processing or reload_data
    resolution
        resolution of the surface in meters
    method
        one of ['linear', 'nearest', 'cubic']
    soundings_per_node
        threshold for minimum number of soundings per cell
    output_path
        if provided, will save the surface to this path
    client
        optional, either dask client or None if you want to skip dask

    Returns
    -------
    BaseSurface
        surface instance for the given soundings data at the given resolution
    """

    if type(fqpr_inst) is list:
        if not fqpr_inst[0].__getattribute__('soundings'):
            print('generate_new_surface: No georeferenced soundings found')
            return None
        if len(fqpr_inst) == 1:
            fqpr_inst = fqpr_inst[0]
    else:
        if not fqpr_inst.__getattribute__('soundings'):
            print('generate_new_surface: No georeferenced soundings found')
            return None

    try:
        if type(fqpr_inst) is not list:
            bs = BaseSurface(fqpr_inst.soundings.x, fqpr_inst.soundings.y, fqpr_inst.soundings.z, fqpr_inst.soundings.unc,
                             fqpr_inst.soundings.xyz_crs, resolution=resolution)
        else:
            unique_crs = np.unique([f.soundings.xyz_crs for f in fqpr_inst])
            if len(unique_crs) > 1:
                print('Found multiple EPSG codes in the input data, data must be of the same code: {}'.format(unique_crs))
            bs = BaseSurface(xr.concat([f.soundings.x for f in fqpr_inst], dim='sounding'),
                             xr.concat([f.soundings.y for f in fqpr_inst], dim='sounding'),
                             xr.concat([f.soundings.z for f in fqpr_inst], dim='sounding'),
                             xr.concat([f.soundings.unc for f in fqpr_inst], dim='sounding'),
                             int(fqpr_inst[0].soundings.xyz_crs), resolution=resolution)
    except (AttributeError, IndexError):
        print('Expect a list of fqpr instances or a single fqpr instance as input.  Received {}'.format(fqpr_inst))
        return

    bs.construct_base_grid()
    bs.build_histogram(client=client)
    bs.build_surfaces(method=method, count_msk=soundings_per_node)
    if output_path is not None:
        bs.save(output_path)
    return bs


def reload_surface(surface_path: str):
    """
    Simple convenience method for reloading a surface from a path

    | surface_path = 'C:/data_directory/surface.npz'
    | surf = reload_surface(surface_path)

    Parameters
    ----------
    surface_path
        path to the saved surface file

    Returns
    -------
    BaseSurface
        surface loaded from the file path provided

    """
    bs = BaseSurface(from_file=surface_path)
    return bs


def return_processed_data_folders(converted_folder: str):
    """
    After processing, you'll have a directory of folders containing the kluster records.  Use this function to return an
    organized dict of which folders correspond to which records.

    converted_folder = C:/data_dir/converted_093926

    return_processed_data_folders(converted_folder)

    | {'attitude': ['C:/data_dir/converted_093926/attitude.zarr'],
    |  'navigation': ['C:/data_dir/converted_093926/navigation.zarr'],
    |  'ping': ['C:/data_dir/converted_093926/ping_40107_0_260000.zarr',
    |           'C:/data_dir/converted_093926/ping_40107_1_320000.zarr',
    |           'C:/data_dir/converted_093926/ping_40107_2_290000.zarr'],
    |  'soundings': ['C:/data_dir/converted_093926/soundings.zarr'],
    |  'ppnav': [],
    |  'logfile': 'C:/data_dir/converted_093926/logfile_120826.txt'}

    Parameters
    ----------
    converted_folder
        path to the folder containing the kluster processed data folders

    Returns
    -------
    final_paths
        directory paths according to record type (ex: navigation, attitude, etc.)
    """

    final_paths = {'attitude': [], 'navigation': [], 'ping': [], 'soundings': [], 'ppnav': [], 'logfile': []}
    if os.path.isdir(converted_folder):
        for fldr in os.listdir(converted_folder):
            fldrpath = os.path.join(converted_folder, fldr)
            for ky in list(final_paths.keys()):
                if fldr.find(ky) != -1:
                    if os.path.isdir(fldrpath):
                        final_paths[ky].append(fldrpath)
                    elif ky in ['logfile']:
                        final_paths[ky] = fldrpath
    return final_paths


def reprocess_sounding_selection(fqpr_inst: Fqpr, new_xyzrph: dict = None, subset_time: list = None,
                                 turn_off_dask: bool = True, turn_dask_back_on: bool = False,
                                 override_datum: str = None, override_vertical_reference: str = None):
    """
    Designed to feed a patch test tool.  This function will reprocess all the soundings within the given subset
    time and return the xyz values without writing to disk.  If a new xyzrph (dictionary that holds the offsets and
    mounting angles information) is provided, the reprocessing will use those offsets/angles. Presumably after many
    iterations, the patch test tool would provide good offsets/angles that make this sounding selection look good and
    the full dataset can be reprocessed.

    Soundings returned as a list of numpy arrays, with xyz plus the timestamp that you can use to figure out which
    installation parameters entry applies.

    I've found that you can get up to a 6x speed increase by disabling dask.distributed for small datasets, which is
    huge for something like this that might require many iterations with small time ranges.  I've yet to see a way
    to skip the client/scheduler, so we brute force destroy it for now.  This takes a couple seconds, but shouldn't be
    a big deal.

    Parameters
    ----------
    fqpr_inst
        instance of fqpr_generation.Fqpr class containing processed xyz soundings
    new_xyzrph
        keys are translated entries, vals are dicts with timestamps:values
    subset_time
        List of utc timestamps in seconds, used as ranges for times that you want to process.\n
        ex: subset_time=[1531317999, 1531321000] means only process times that are from 1531317999 to 1531321000\n
        ex: subset_time=[[1531317999, 1531318885], [1531318886, 1531321000]] means only process times that are\n
              from either 1531317999 to 1531318885 or 1531318886 to 1531321000
    turn_off_dask
        if True, close the client and destroy it.  Just closing doesn't work, as it retains the scheduler,
        which will try and find workers that don't exist when you run a process
    turn_dask_back_on
        if True, will restart the client by reloading data if the client does not exist
    override_datum
        datum identifier if soundings does not exist, will prefer this over the soundings information
    override_vertical_reference
        vertical reference identifier, will prefer this over the soundings information

    Returns
    -------
    Fqpr
        instance or list of instances of fqpr_generation.Fqpr class that contains generated soundings data
    list
        list of numpy arrays, [x (easting in meters), y (northing in meters), z (depth pos down in meters),
        tstmp (xyzrph timestamp for each sounding)
    """

    if fqpr_inst.soundings is None and (override_datum is None or override_vertical_reference is None):
        raise NotImplementedError('Either fqpr_inst.soundings or override_datum/override_vertical_reference are required for determining the CRS')
    if turn_off_dask and fqpr_inst.client is not None:
        fqpr_inst.client.close()
        fqpr_inst.client = None
        fqpr_inst = reload_data(os.path.dirname(fqpr_inst.source_dat.final_paths['ping'][0]), skip_dask=True)
    if new_xyzrph is not None:
        fqpr_inst.source_dat.xyzrph = new_xyzrph
    if subset_time is not None:
        if type(subset_time[0]) is not list:  # fix for when user provides just a list of floats [start,end]
            subset_time = [subset_time]

    fqpr_inst.get_orientation_vectors(subset_time=subset_time, dump_data=False)
    fqpr_inst.get_beam_pointing_vectors(subset_time=subset_time, dump_data=False)
    fqpr_inst.sv_correct(subset_time=subset_time, dump_data=False)

    if override_datum is not None:
        datum = override_datum
        epsg = None
    else:
        datum = None
        epsg = fqpr_inst.soundings.xyz_crs

    if override_vertical_reference is not None:
        vert_ref = override_vertical_reference
    else:
        vert_ref = fqpr_inst.soundings.vertical_reference

    fqpr_inst.construct_crs(epsg=epsg, datum=datum)
    fqpr_inst.georef_xyz(vert_ref=vert_ref, subset_time=subset_time, dump_data=False)

    soundings = [[], [], [], []]
    for sector in fqpr_inst.intermediate_dat:
        if 'xyz' in fqpr_inst.intermediate_dat[sector]:
            for tstmp in fqpr_inst.intermediate_dat[sector]['xyz']:
                dat = fqpr_inst.intermediate_dat[sector]['xyz'][tstmp]
                for d in dat:
                    x_vals = np.ravel(d[0][0])
                    y_vals = np.ravel(d[0][1])
                    z_vals = np.ravel(d[0][2])
                    idx = ~np.isnan(x_vals)
                    soundings[0].append(x_vals[idx])
                    soundings[1].append(y_vals[idx])
                    soundings[2].append(z_vals[idx])
                    soundings[3].append([tstmp] * len(z_vals[idx]))
        else:
            print('No soundings found for {}'.format(sector))

    soundings = [np.concatenate(s, axis=0) for s in soundings]
    if turn_dask_back_on and fqpr_inst.client is None:
        fqpr_inst = reload_data(os.path.dirname(fqpr_inst.source_dat.final_paths['ping'][0]))
    return fqpr_inst, soundings