import psutil
import tempfile
import subprocess
import os
import tables
import time
import numpy as np
from multiprocessing.pool import Pool
from mkidcore.headers import ObsHeader
from mkidcore.corelog import getLogger
from mkidcore.config import yaml, yaml_object


BIN2HDFCONFIGTEMPLATE = ('{x} {y}\n'
                         '{datadir}\n'
                         '{starttime}\n'
                         '{inttime}\n'
                         '{beamfile}\n'
                         '1\n'
                         '{outdir}')


def makehdf(cfgORcfgs, maxprocs=2, polltime=.1, executable_path=''):
    """
    Run b2n2hdf on the config(s). Takes a config or iterable of configs.

    maxprocs(2) keyword may be used to specify the maximum number of processes
    polltime(.1) sets how often processes are checked for output and output logged
    """
    if isinstance(cfgORcfgs, (tuple, list, set)):
        cfgs = tuple(cfgORcfgs)
    else:
        cfgs = (cfgORcfgs,)

    keepconfigs=False

    nproc = min(len(cfgs), maxprocs)
    polltime = max(.01, polltime)

    tfiles=[]
    for cfg in cfgs:
        with tempfile.NamedTemporaryFile('w',suffix='.cfg', delete=False) as tfile:
            tfile.write(BIN2HDFCONFIGTEMPLATE.format(datadir=cfg.datadir, starttime=cfg.starttime,
                                                     inttime=cfg.inttime, beamfile=cfg.beamfile,
                                                     outdir=cfg.outdir, x=cfg.x, y=cfg.y))
            tfiles.append(tfile)

    things = list(zip(tfiles, cfgs))
    procs = []
    while things:
        tfile, cfg = things.pop()
        procs.append(psutil.Popen((os.path.join(executable_path,'bin2hdf'),tfile.name),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  shell=False, cwd=None, env=None, creationflags=0))
        while len(procs) >= 1:
            #TODO consider replacing with https://gist.github.com/bgreenlee/1402841
            for i, proc in enumerate(procs):
                try:
                    out, err = proc.communicate(timeout=polltime)
                    # TODO fix formatting before uncommenting
                    # if out:
                    #     getLogger(__name__ + '.bin2hdf_{}'.format(i)).info(out)
                    if err:
                        getLogger(__name__ + '.bin2hdf_{}'.format(i)).error(err)
                except subprocess.TimeoutExpired:
                    pass
            procs = list(filter(lambda p: p.poll() is None, procs))
    for p in procs:
        p.kill()

    # Postprocess the h5 files
    ncore = min(nproc, len(cfgs))
    getLogger(__name__).info('Postprocessing {} H5 files using {} cores'.format(len(cfgs), ncore))
    if nproc > 1 and len(cfgs) > 1:
        pool = Pool(ncore)
        pool.map(postprocess, cfgs)
    else:
        for c in cfgs:
            postprocess(c)

    # Clean up temp files
    if not keepconfigs:
        getLogger(__name__).info('Cleaning temp files')
    else:
        getLogger(__name__).info('bin2hdf config files left in {}'.format(os.path.dirname(
            tfiles[0])))
    while tfiles and not keepconfigs:
        tfile = tfiles.pop()
        try:
            os.remove(tfile.name)
        except IOError:
            getLogger(__name__).debug('Failed to delete temp file {}'.format(tfile.name))


def postprocess(cfg):
    add_header(cfg)
    time.sleep(.1)
    if cfg.starttime < 1518222559:
        fix_timestamp_bug(cfg.h5file)
    time.sleep(.1)
    # Prior to Ben's speedup of bin2hdf.c the consolidatePhotonTablesCmd step would need to be here
    index_hdf(cfg)


def _correct_timestamps(timestamps):
    """
    Corrects errors in timestamps due to firmware bug present through PAL2017b.

    Parameters
    ----------
    timestamps: numpy array of integers
        List of timestamps from photon list. Must be in original, unsorted order.

    Returns
    -------
    Array of corrected timestamps, dtype is uint32
    """
    timestamps = np.array(timestamps, dtype=np.int64) #convert timestamps to signed values
    photonTimestamps = timestamps%500
    hdrTimestamps = timestamps - photonTimestamps

    unsortedInds = np.where(np.diff(timestamps)<0)[0]+1 #mark locations n where T(n)<T(n-1)

    for ind in unsortedInds:
        indsToIncrement = np.where(hdrTimestamps==hdrTimestamps[ind])[0]
        indsToIncrement = indsToIncrement[indsToIncrement>=ind]
        hdrTimestamps[indsToIncrement] += 500

    correctedTimestamps = hdrTimestamps + photonTimestamps

    if np.any(np.diff(correctedTimestamps)<0):
        correctedTimestamps = _correct_timestamps(correctedTimestamps)

    return np.array(correctedTimestamps, dtype=np.uint32)


def index_hdf(cfg):
    hfile = tables.open_file(cfg.h5file, 'a')
    hfile.set_node_attr('/', 'PYTABLES_FORMAT_VERSION', '2.0')
    hfile.format_version = '2.0'
    filterObj = tables.Filters(complevel=0, complib='lzo')
    photonTable = hfile.root.Photons.PhotonTable
    photonTable.cols.Time.create_csindex(filters=filterObj)
    photonTable.cols.ResID.create_csindex(filters=filterObj)
    photonTable.cols.Wavelength.create_csindex(filters=filterObj)
    photonTable.flush()
    hfile.close()


def fix_timestamp_bug(file):
    noResIDFlag = 2 ** 32 - 1
    hfile = tables.open_file(file, mode='a')
    beamMap = hfile.root.BeamMap.Map.read()
    imShape = np.shape(beamMap)
    for x in range(imShape[0]):
        for y in range(imShape[1]):
            # print('Correcting pixel', x, y, ', resID =', obsfl.beamImage[x,y])
            resID = beamMap[x, y]
            if resID == noResIDFlag:
                getLogger(__name__).info('Table not found for pixel', x, ',', y)
                continue
            photonTable = hfile.get_node('/Photons/' + str(resID))
            photonList = photonTable.read()
            timeList = photonList['Time']
            correctedTimeList = _correct_timestamps(timeList)

            assert len(photonTable) == len(timeList), 'Timestamp list does not match length of photon list!'
            photonTable.modify_column(column=correctedTimeList, colname='Time')
            photonTable.flush()
    hfile.close()


def add_header(cfg, wvlBinStart=700, wvlBinEnd=1500, energyBinWidth=0.1):
    dataDir = cfg.datadir
    firstSec = cfg.starttime
    expTime = cfg.inttime
    beammapFile = cfg.beamfile
    hfile = tables.open_file(cfg.h5file, mode='a')
    hfile.create_group('/', 'header', 'Header')
    headerTable = hfile.create_table('/header', 'header', ObsHeader, 'Header')
    headerContents = headerTable.row
    headerContents['isWvlCalibrated'] = False
    headerContents['isFlatCalibrated'] = False
    headerContents['isSpecCalibrated'] = False
    headerContents['isLinearityCorrected'] = False
    headerContents['isPhaseNoiseCorrected'] = False
    headerContents['isPhotonTailCorrected'] = False
    headerContents['timeMaskExists'] = False
    headerContents['startTime'] = firstSec
    headerContents['expTime'] = expTime
    headerContents['wvlBinStart'] = wvlBinStart
    headerContents['wvlBinEnd'] = wvlBinEnd
    headerContents['energyBinWidth'] = energyBinWidth
    headerContents['target'] = ''
    headerContents['dataDir'] = dataDir
    headerContents['beammapFile'] = beammapFile
    headerContents['wvlCalFile'] = ''
    headerContents.append()
    headerTable.flush()
    hfile.close()


@yaml_object(yaml)
class Bin2HdfConfig(object):
    def __init__(self, datadir='./', beamfile='./default.bmap', starttime=None, inttime=None,
                 outdir='./', x=140, y=146, writeto=None):
        self.datadir = datadir
        self.starttime = starttime
        self.inttime = inttime
        self.beamfile = beamfile
        self.outdir = outdir
        self.x = x
        self.y = y
        if writeto is not None:
            self.write(writeto)

    @property
    def h5file(self):
        return os.path.join(self.outdir, str(self.starttime) + '.h5')

    def write(self, file):
        with open(file, 'w') as wavefile:
            wavefile.write(BIN2HDFCONFIGTEMPLATE.format(datadir=self.datadir, starttime=self.starttime,
                                                        inttime=self.inttime, beamfile=self.beamfile,
                                                        outdir=self.outdir, x=self.x, y=self.y))

    def load(self):
        raise NotImplementedError
