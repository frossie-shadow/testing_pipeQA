import sys, os, re, copy

import lsst.daf.persistence             as dafPersist
import lsst.afw.detection               as afwDet
import lsst.afw.image                   as afwImage
import lsst.meas.astrom                 as measAst
import lsst.afw.geom                    as afwGeom
import lsst.afw.cameraGeom              as cameraGeom

import Manifest   as manifest
import CameraInfo as qaCamInfo

import QaDataUtils as qaDataUtils

from QaData import QaData

#######################################################################
#
#
#
#######################################################################
class ButlerQaData(QaData):
    """ """

    #######################################################################
    #
    #######################################################################
    def __init__(self, label, rerun, cameraInfo, dataDir, **kwargs):
        """
        keyword args:
        haveManifest = boolean, verify files in dataDir are present according to manifest
        verifyChecksum = boolean, verify files in dataDir have correct checksum as listed in manifest
        """
        QaData.__init__(self, label, rerun, cameraInfo)
        self.rerun = rerun
        self.dataDir = dataDir


        ###############################################
        # handle keyword args
        ###############################################
        self.kwargs      = kwargs
	self.dataId         = self.kwargs.get('dataId', {})
        self.haveManifest   = self.kwargs.get('haveManifest', False)
        self.verifyChecksum = self.kwargs.get('verifyChecksum', False)

        ###############################################
        # check the manifest, if requested
        # haveManifest = True is a bit slowish
        # verifyChecksum = True is quite slow
        manifest.verifyManifest(self.dataDir, verifyExists=self.haveManifest,
				verifyChecksum=self.verifyChecksum)


        # This (dataId fetching) needs a better design, but will require butler/mapper change, I think.
        #
        # these obscure things refer to the names assigned to levels in the data hierarchy
        # eg. for lsstSim:   dataInfo  = [['visit',1], ['snap', 0], ['raft',0], ['sensor',0]]
        # a level is considered a discriminator if it represents different pictures of the same thing
        # ... so the same object may appear in multiple 'visits', but not on multiple 'sensors'
        # dataInfo is passed in from the derived class as it's specific to each mapper
        
        dataIdRegexDict = {}
        for array in self.dataInfo:
            dataIdName, dataIdDiscrim = array

            # if the user requested eg. visit=1234.*
            # pull that out of kwargs and put it in dataIdRegexDict
            if self.dataId.has_key(dataIdName):
                dataIdRegexDict[dataIdName] = self.dataId[dataIdName]
                

        #######################################
        # get butler
        self.outMapper = self.cameraInfo.getMapper(self.dataDir, rerun=self.rerun)
        self.outButler = dafPersist.ButlerFactory(mapper=self.outMapper).create()

        
        ####################################################
        # make a list of the frames we're asked to care about

        # get all the available raw inputs
        self.availableDataTuples = self.outButler.queryMetadata('raw', self.dataIdNames,
                                                                format=self.dataIdNames)

        # of the data available, get a list of the ones the user actually wants us
        #  to run.  A bit sketchy here ... kwargs contains non-idname info as well.
        self.dataTuples = self._regexMatchDataIds(dataIdRegexDict, self.availableDataTuples)



    def getVisits(self, dataIdRegex):
	""" Return explicit visits matching for a dataIdRegex."""
	visits = []
	dataTuplesToFetch = self._regexMatchDataIds(dataIdRegex, self.dataTuples)
	for dataTuple in dataTuplesToFetch:
	    dataId = self._dataTupleToDataId(dataTuple)
	    visits.append(str(dataId['visit']))
	return set(visits)
    

    #######################################################################
    #
    #######################################################################
    def getSourceSetBySensor(self, dataIdRegex):
        """Get sources for requested data as one sourceSet."""
        
        dataTuplesToFetch = self._regexMatchDataIds(dataIdRegex, self.dataTuples)

        # get the datasets corresponding to the request
        ssDict = {}
        for dataTuple in dataTuplesToFetch:
            dataId = self._dataTupleToDataId(dataTuple)
            dataKey = self._dataTupleToString(dataTuple)
            
            if self.sourceSetCache.has_key(dataKey):
                ssDict[dataKey] = copy.copy(self.sourceSetCache[dataKey])
                continue

            # make sure we actually have the output file
            isWritten = self.outButler.datasetExists('src', dataId)
            if isWritten:
                persistableSourceVector = self.outButler.get('src', dataId)
                sourceSetTmp = persistableSourceVector.getSources()

                if self.outButler.datasetExists('calexp', dataId):

		    calibDict = self.getCalibBySensor(dataId)
                    calib = calibDict[dataKey]
                    
                    fmag0, fmag0err = calib.getFluxMag0()
                    for s in sourceSetTmp:
                        apFlux  = s.getApFlux()
                        psfFlux = s.getPsfFlux()
                        s.setApFlux(apFlux/fmag0)
                        s.setPsfFlux(psfFlux/fmag0)

                self.sourceSetCache[dataKey] = sourceSetTmp
                ssDict[dataKey] = copy.copy(sourceSetTmp)
		self.dataIdLookup[dataKey] = dataId
		
            else:
                print str(dataTuple) + " output file missing.  Skipping."
                
        return ssDict

    def getSourceSet(self, dataIdRegex):

	ssDict = self.getSourceSetBySensor(dataIdRegex)
	ssReturn = []
	for key, ss in ssDict.items():
	    ssReturn += ss
	return ssReturn



    def loadCalexp(self, dataIdRegex):
	
        dataTuplesToFetch = self._regexMatchDataIds(dataIdRegex, self.dataTuples)

        # get the datasets corresponding to the request
        for dataTuple in dataTuplesToFetch:
            dataId = self._dataTupleToDataId(dataTuple)
            dataKey = self._dataTupleToString(dataTuple)
            
            if self.calexpCache.has_key(dataKey):
                continue

	    if self.outButler.datasetExists('calexp', dataId):
		calexp = self.outButler.get('calexp', dataId)
		
		self.wcsCache[dataKey] = calexp.getWcs()
		self.detectorCache[dataKey] = calexp.getDetector()
		self.filterCache[dataKey] = calexp.getFilter()
		self.calibCache[dataKey] = calexp.getCalib()
		
                self.calexpCache[dataKey] = True
		self.dataIdLookup[dataKey] = dataId
		
            else:
                print str(dataTuple) + " calib output file missing.  Skipping."
                


    def getCalexpEntryBySensor(self, cache, dataIdRegex):

        dataTuplesToFetch = self._regexMatchDataIds(dataIdRegex, self.dataTuples)

        # get the datasets corresponding to the request
        entryDict = {}
        for dataTuple in dataTuplesToFetch:
            dataId = self._dataTupleToDataId(dataTuple)
            dataKey = self._dataTupleToString(dataTuple)
	    self.loadCalexp(dataId)
	    if cache.has_key(dataKey):
		entryDict[dataKey] = cache[dataKey]
	    
        return entryDict



    #######################################################################
    # utility to go through a list of data Tuples and return
    #  the ones which match regexes for the corresponding data type
    # so user can say eg. raft='0,\d', visit='855.*', etc
    #######################################################################
    def _regexMatchDataIds(self, dataIdRegexDict, availableDataTuples):
        """ """

        # go through the list of what's available, and compare to what we're asked for
        # Put matches in a list of tuples, eg. [(vis1,sna1,raf1,sen1),(vis2,sna2,raf2,sen2)] 
        dataTuples = []
        for dataTuple in availableDataTuples:

            # start true and fail if any dataId keys fail ... eg. 'visit' doesn't match
            match = True
            for i in range(len(self.dataIdNames)):
                dataIdName = self.dataIdNames[i]   # eg. 'visit', 'sensor', etc
                regexForThisId = dataIdRegexDict.get(dataIdName, '.*') # default to '.*' or 'anything'
                dataId = dataTuple[i]

                # if it doesn't match, this frame isn't to be run.
                if not re.search(str(regexForThisId),  str(dataId)):
                    match = False

            if match:
                dataTuples.append(dataTuple)
                
        return dataTuples
                

    



#######################################################################
#
#
#
#######################################################################
def makeButlerQaData(label, rerun=None, **kwargs):
        
    testbedDir, testdataDir = qaDataUtils.findDataInTestbed(label)

    # make sure LsstSim is last in the list (its 'verifyRegistries()' will pass for all cameras)
    cameraInfos = [
        qaCamInfo.CfhtCameraInfo(),
        qaCamInfo.HscCameraInfo(),
        qaCamInfo.SuprimecamCameraInfo(),
        qaCamInfo.LsstSimCameraInfo(),
        ]

    # try each camera ***in-order***
    # note that LsstSim will look like all other as it uses the same registry for data and calib
    # ... must test it last
    cameraToUse = None
    for cameraInfo in cameraInfos:
        # if the mapper couldn't be found, we can't use this camera
        hasMapper = not cameraInfo.mapperClass is None
        validReg = cameraInfo.verifyRegistries(testdataDir)
        if hasMapper and validReg:
            cameraToUse = cameraInfo
            break

    if cameraToUse is None:
        raise Exception("Can't find registries usable with any mappers.")
    else:
        if rerun is None:
            rerun = cameraToUse.getDefaultRerun()
        return ButlerQaData(label, rerun, cameraToUse, testdataDir, **kwargs)

