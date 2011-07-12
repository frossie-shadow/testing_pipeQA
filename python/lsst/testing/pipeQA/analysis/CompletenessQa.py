import re
import numpy as num

import lsst.testing.pipeQA.TestCode as testCode
import QaAnalysis as qaAna
import lsst.testing.pipeQA.figures as qaFig
import lsst.meas.algorithms as measAlg
import lsst.testing.pipeQA.figures.QaFigureUtils as qaFigUtils
import RaftCcdData as raftCcdData

from matplotlib.font_manager import FontProperties

# Until we can make it more robust
hasMinuit = False
try:
    import minuit2
except:
    hasMinuit = False
    

class CompletenessQa(qaAna.QaAnalysis):
    def __init__(self, completenessMagMin, completenessMagMax, **kwargs):
        qaAna.QaAnalysis.__init__(self, **kwargs)
        self.limits = [completenessMagMin, completenessMagMax]
        self.bins   = num.arange(14, 27, 0.5)

        self.description = """
         For each CCD, the top figure shows the counts of 4 classes of
         objects, plotted in histograms as a function of magnitude, for stars
         only.  "Matched" objects are detections that match 1-to-1 with with
         reference catalog (through Source Association); "Blended" objects
         match N-to-1 with the reference catalog; "Orphan" objects do not match
         any entry in the reference catalog, and may include false positives
         and asteroids; while "Unmatched" stars are those present in the
         reference catalog but not detected in the science image.  The measure
         of completeness is represented by (matched + blended) / (matched +
         blended + unmatched), which is the blue line.  The magnitude below
         which the completeness is < 50% is indicated with the crosshairs.  The
         bottom panel shows the same for galaxies only.  Orphans are included
         in both plots.  The summary FPA figure provides a visual
         representation of this photometric depth.
        """
         
    def free(self):
        del self.detector
        del self.filter
        del self.matchListDictSrc

        del self.orphan
        del self.matchedStar
        del self.blendedStar
        del self.undetectedStar
        del self.matchedGalaxy
        del self.blendedGalaxy
        del self.undetectedGalaxy
        del self.depth
        if hasMinuit:
            del self.fit

    def limitingMag(self, raftId, ccdId):
        if hasMinuit:
            try:
                return self.limitingMagMinuit(raftId, ccdId)
            except:
                pass

        matchedStar     = num.array(self.matchedStar.get(raftId, ccdId))
        blendedStar     = num.array(self.blendedStar.get(raftId, ccdId))
        undetectedStar  = num.array(self.undetectedStar.get(raftId, ccdId))

        allStars        = num.concatenate((matchedStar, blendedStar, undetectedStar))
        foundStars      = num.concatenate((matchedStar, blendedStar))
        histAll         = num.histogram(allStars, bins=self.bins)
        histFound       = num.histogram(foundStars, bins=self.bins)

        magbins = 0.5 * (histAll[1][1:] + histAll[1][:-1])
        w       = num.where(histAll[0] != 0)
        x       = magbins[w]
        n       = 1.0 * histFound[0][w]
        d       = 1.0 * histAll[0][w]
        y       = n / d  

        for i in num.arange(len(y) - 1, 1, -1):
            if y[i] <= 0.5 and y[i-1] > 0.5:
                return (0.5 - y[i-1]) / (y[i] - y[i-1]) * (x[i] - x[i-1]) + x[i-1]
        return 0.0
        
    def limitingMagMinuit(self, raftId, ccdId):
        # Model is of the form:
        # 0.5 + -1.0 / num.pi * num.arctan(A * x + B)
        
        import minuit2
        matchStarList   = self.matchStarSrc.get(raftId, ccdId)
        unmatchStarList = self.unmatchCatStar.get(raftId, ccdId)
        
        histStarSrc     = num.histogram(matchStarList, bins = self.bins)
        maxSrcIdx       = num.argsort(histStarSrc[0])[-1]
        histUnmatchStar = num.histogram(unmatchStarList, bins = self.bins)

        magbins   = 0.5 * (histStarSrc[1][1:] + histStarSrc[1][:-1])
        histRatio = num.zeros(len(histStarSrc[0]))

        w     = num.where((histStarSrc[0] + histUnmatchStar[0]) != 0)
        x     = magbins[w]

        # approximate
        d     = 1.0 * histStarSrc[0][w]
        u     = 1.0 * histUnmatchStar[0][w]
        dd    = num.sqrt(d)
        n     = d + u
        y     = d / n
        dy    = dd / n

        idx = num.where(dy != 0)
        x   = x[idx]
        y   = y[idx]
        dy  = dy[idx]
              
        def fcn(A, B):
            model  = 0.5 + -1.0 / num.pi * num.arctan(A * x + B)
            chi    = (model - y) / dy
            return num.sum(chi**2)
        
        m = minuit2.Minuit2(fcn)
        m.values['A'] = 1
        m.values['B'] = -10
        m.migrad()

        mx = num.arange(min(x), max(x), 0.1)
        my = 0.5 + -1.0 / num.pi * num.arctan(m.values['A'] * mx + m.values['B'])
        mindx = num.argsort((num.abs(my-0.5)))[0]

        self.fit.set(raftId, ccdId, [m.values['A'], m.values['B']])
        return mx[mindx]

    def test(self, data, dataId, fluxType = "psf"):
        testSet = self.getTestSet(data, dataId)
        testSet.addMetadata({"Description": self.description})
        
        self.fluxType = fluxType
        self.detector         = data.getDetectorBySensor(dataId)
        self.filter           = data.getFilterBySensor(dataId)
        self.matchListDictSrc = data.getMatchListBySensor(dataId, useRef='src')

        self.orphan           = raftCcdData.RaftCcdVector(self.detector)
        self.matchedStar      = raftCcdData.RaftCcdVector(self.detector)
        self.blendedStar      = raftCcdData.RaftCcdVector(self.detector)
        self.undetectedStar   = raftCcdData.RaftCcdVector(self.detector)
        self.matchedGalaxy    = raftCcdData.RaftCcdVector(self.detector)
        self.blendedGalaxy    = raftCcdData.RaftCcdVector(self.detector)
        self.undetectedGalaxy = raftCcdData.RaftCcdVector(self.detector)
        self.depth            = raftCcdData.RaftCcdData(self.detector)

        if hasMinuit:
            self.fit = raftCcdData.RaftCcdData(self.detector, initValue=[0.0, 0.0]) 
        
        for key in self.detector.keys():
            raftId     = self.detector[key].getParent().getId().getName()
            ccdId      = self.detector[key].getId().getName()
            filterName = self.filter[key].getName()

            if self.matchListDictSrc.has_key(key):
                # Detections
                matchSet = [
                    [self.matchListDictSrc[key]['matched'], self.matchedStar, self.matchedGalaxy],
                    [self.matchListDictSrc[key]['blended'], self.blendedStar, self.blendedGalaxy]
                    ]
                for mset in matchSet:
                    mdict, starvec, galvec = mset
                    
                    stars    = []
                    galaxies = []
                    for m in mdict:
                        sref, s, dist = m
                        if fluxType == "psf":
                            fref  = sref.getPsfFlux()
                            f     = s.getPsfFlux()
                            ferr  = s.getPsfFluxErr()
                        else:
                            fref  = sref.getPsfFlux()
                            f     = s.getApFlux()
                            ferr  = s.getApFluxErr()

                        flags = s.getFlagForDetection()
                        if (fref > 0.0 and f > 0.0):
                            # Use known catalog mag
                            mrefmag  = -2.5*num.log10(fref)
                            star = flags & measAlg.Flags.STAR
                            if num.isfinite(mrefmag):
                                if star > 0:
                                    stars.append(mrefmag)
                                else:
                                    galaxies.append(mrefmag)
                    starvec.set(raftId, ccdId, num.array(stars))
                    galvec.set(raftId, ccdId, num.array(galaxies))
    
                # Non-detections
                undetectedStars = []
                undetectedGalaxies = []
                for nondet in self.matchListDictSrc[key]['undetected']:
                    mag = nondet.getMag(filterName)
                    if nondet.getIsStar():
                        undetectedStars.append(mag)
                    else:
                        undetectedGalaxies.append(mag)
                self.undetectedStar.set(raftId, ccdId, num.array(undetectedStars))
                self.undetectedGalaxy.set(raftId, ccdId, num.array(undetectedGalaxies))
                    
                # Orphans
                orphans = []
                for orphan in self.matchListDictSrc[key]['orphan']:
                    if self.fluxType == "psf":
                        f = orphan.getPsfFlux()
                    else:
                        f = orphan.getApFlux()
                    if f > 0.0:
                        orphans.append(-2.5 * num.log10(f))
                self.orphan.set(raftId, ccdId, num.array(orphans))

                ############ Calculate limiting mag
                
                maxDepth = self.limitingMag(raftId, ccdId)
                self.depth.set(raftId, ccdId, maxDepth)
                
                areaLabel = data.cameraInfo.getDetectorName(raftId, ccdId)
                label = "photometric depth "
                comment = "magnitude where star completeness drops below 0.5"
                test = testCode.Test(label, maxDepth, self.limits, comment, areaLabel=areaLabel)
                testSet.addTest(test)


    def plot(self, data, dataId, showUndefined = False):
        testSet = self.getTestSet(data, dataId)
        testSet.setUseCache(self.useCache)
        isFinalDataId = False
        if len(data.brokenDataIdList) > 0 and data.brokenDataIdList[-1] == dataId:
            isFinalDataId = True

        # fpa figure
        filebase = "completenessDepth"
        depthData, depthMap = testSet.unpickle(filebase, default=[None, None])
        depths = []
        depthFig = qaFig.FpaQaFigure(data.cameraInfo, data=depthData, map=depthMap)
        for raft, ccdDict in depthFig.data.items():
            for ccd, value in ccdDict.items():
                if not self.depth.get(raft, ccd) is None:
                    depth = self.depth.get(raft, ccd)
                    depths.append(depth)
                    depthFig.data[raft][ccd] = depth
                    if num.isfinite(depth):
                        depthFig.map[raft][ccd] = 'mag=%.2f'%(depth)
                    else:
                        depthFig.map[raft][ccd] = 'mag=nan'
                        
        testSet.pickle(filebase, [depthFig.data, depthFig.map])

        blue = '#0000ff'
        red  = '#ff0000'
        
        if False:
            if len(depths) >= 2:
                vmin = max(num.min(depths), self.limits[0])
                vmax = min(num.max(depths), self.limits[1])
            else:
                vmin = self.limits[0]
                vmax = self.limits[1]

            if vmax <= vmin:
                vmin = self.limits[0]
                vmax = self.limits[1]
        else:
            vmin, vmax = 1.0*self.limits[0], 1.0*self.limits[1]

        if not self.delaySummary or isFinalDataId:
            print "plotting FPAs"
            depthFig.makeFigure(showUndefined=showUndefined, cmap="RdBu_r", vlimits=[vmin, vmax],
                                title="Photometric Depth", cmapOver=red, cmapUnder=blue,
                                failLimits=self.limits)
            testSet.addFigure(depthFig, filebase+".png", "Estimate of photometric depth",  navMap=True)

        del depthFig


        # Each CCD
        for raft, ccd in self.depth.raftCcdKeys():
            orphan           = self.orphan.get(raft, ccd)
            matchedStar      = self.matchedStar.get(raft, ccd)
            blendedStar      = self.blendedStar.get(raft, ccd)
            undetectedStar   = self.undetectedStar.get(raft, ccd)
            matchedGalaxy    = self.matchedGalaxy.get(raft, ccd)
            blendedGalaxy    = self.blendedGalaxy.get(raft, ccd)
            undetectedGalaxy = self.undetectedGalaxy.get(raft, ccd)

            print "Plotting ", ccd

            fig = qaFig.QaFigure()
            sp1 = fig.fig.add_subplot(211)
            sp2 = fig.fig.add_subplot(212, sharex = sp1)

            # Stacked histogram
            orphanHist         = num.histogram(orphan, bins=self.bins)
            matchedStarHist    = num.histogram(matchedStar, bins=self.bins)
            blendedStarHist    = num.histogram(blendedStar, bins=self.bins)
            undetectedStarHist = num.histogram(undetectedStar, bins=self.bins)
            # For bar, you send the coordinate of the left corner of the bar
            barbins    = orphanHist[1][:-1]
            width      = 1.0 * (orphanHist[1][1] - orphanHist[1][0])
            orphanBar  = sp1.bar(barbins, orphanHist[0], width=width, color='r', alpha = 0.5, label = 'Orphan', capsize = 1)
            bottom     = orphanHist[0]
            matchedBar = sp1.bar(barbins, matchedStarHist[0], width=width, color='g', alpha=0.5, label='Matched',
                                 bottom=bottom, capsize=1)
            bottom    += matchedStarHist[0]
            blendedBar = sp1.bar(barbins, blendedStarHist[0], width=width, color='cyan', alpha=0.5, label='Blended',
                                 bottom=bottom, capsize=1)
            bottom    += blendedStarHist[0]
            unmatBar   = sp1.bar(barbins, undetectedStarHist[0], width=width, color='b', alpha=0.5, label='Unmatched',
                                 bottom=bottom, capsize=1)

            sp1x2           = sp1.twinx()
            allStars        = num.concatenate((matchedStar, blendedStar, undetectedStar))
            foundStars      = num.concatenate((matchedStar, blendedStar))
            histAll         = num.histogram(allStars, bins=self.bins)
            histFound       = num.histogram(foundStars, bins=self.bins)
            
            magbins = 0.5 * (histAll[1][1:] + histAll[1][:-1])
            w       = num.where(histAll[0] != 0)
            x       = magbins[w]
            n       = 1.0 * histFound[0][w]
            d       = 1.0 * histAll[0][w]
            y       = n / d  
            sp1x2.plot(x, y)
            sp1x2.set_ylim([0.0, 1.2])
            sp1x2.set_ylabel('(Match+Blend)/Tot', fontsize=8)
            sp1x2.axhline(y = 0.5, c='k', linestyle='-', alpha = 0.25)
            sp1x2.axvline(x = self.depth.get(raft, ccd), c='k', linestyle='-', alpha = 0.25)
            qaFigUtils.qaSetp(sp1x2.get_xticklabels(), visible=False)
            qaFigUtils.qaSetp(sp1x2.get_yticklabels(), fontsize = 6)

            sp1.set_ylabel('N Stars', fontsize=10)
            qaFigUtils.qaSetp(sp1.get_xticklabels()+sp1.get_yticklabels(), fontsize = 8)

            ##############

            orphanHist        = num.histogram(orphan, bins=self.bins)
            matchedGalHist    = num.histogram(matchedGalaxy, bins=self.bins)
            blendedGalHist    = num.histogram(blendedGalaxy, bins=self.bins)
            undetectedGalHist = num.histogram(undetectedGalaxy, bins=self.bins)
            orphanBar  = sp2.bar(barbins, orphanHist[0], width=width, color='r', alpha = 0.5, label = 'Orphan', capsize = 1, log=False)
            bottom     = orphanHist[0]
            matchedBar = sp2.bar(barbins, matchedGalHist[0], width=width, color='g', alpha=0.5, label='Matched',
                                 bottom=bottom, capsize=1, log=False)
            bottom    += matchedGalHist[0]
            blendedBar = sp2.bar(barbins, blendedGalHist[0], width=width, color='cyan', alpha=0.5, label='Blended',
                                 bottom=bottom, capsize=1, log=False)
            bottom    += blendedGalHist[0]
            unmatBar   = sp2.bar(barbins, undetectedGalHist[0], width=width, color='b', alpha=0.5, label='Unmatched',
                                 bottom=bottom, capsize=1, log=False)
            
            sp2.set_xlabel('Mag', fontsize=10)
            sp2.set_ylabel('N Gals', fontsize=10)
            qaFigUtils.qaSetp(sp2.get_xticklabels()+sp2.get_yticklabels(), fontsize = 8)
            sp2.legend(numpoints = 1, prop=FontProperties(size='x-small'), loc = 'upper left')
            #sp2.set_ylim(0.75, 999)
            #sp2.semilogy()

            sp1.set_xlim(14, 26)
            label = data.cameraInfo.getDetectorName(raft, ccd)
            fig.fig.suptitle('%s Stacked histogram' % (label), fontsize = 12)
            testSet.addFigure(fig, "completeness.png", "Photometric detections "+label, areaLabel=label)
            del fig


