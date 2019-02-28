#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jan 29 16:28:30 2018

@author: clint


GO TO THE ENCLOSING DIRECTORY AND RUN IT FROM THE TERMINAL WITH THE FOLLOWING COMMAND:
python oracle.py

"""

import matplotlib
import numpy as np

matplotlib.use('Qt5Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
# from matplotlib.widgets import Cursor
import sys,os
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import pyqtSignal
from mkidpipeline.hdf.photontable import ObsFile
import mkidpipeline.hdf.binparse as binparse
from scipy.optimize import curve_fit
from scipy import optimize
import os.path
from mkidpipeline.speckle import binned_rician as binnedRE
import mkidpipeline.speckle.optimize_IcIsIr as binfree
from scipy.special import factorial
import time
import datetime





class img_object():
    def __init__(self,filename,verbose = False):
        self.verbose = verbose
        self.filename = filename
        self.n_col, self.n_row = self.get_npixels(self.filename)
        with open(filename, mode='rb') as f:
            self.image = np.transpose(np.reshape(np.fromfile(f,dtype=np.uint16), (self.n_col,self.n_row)))

    def get_npixels(self, filename):
        # 146 row x 140 col for MEC
        # 125 row x 80 col for darkness

        npixels = len(np.fromfile(open(filename, mode='rb'), dtype=np.uint16))
        if self.verbose: print('npixels = ', npixels, '\n')

        if npixels == 10000:  # darkness
            n_col = 80
            n_row = 125
            if self.verbose: print('\n\ncamera is DARKNESS/PICTURE-C\n\n')
        elif npixels == 20440:  # mec
            n_col = 140
            n_row = 146
            if self.verbose: print('\n\ncamera is MEC\n\n')
        else:
            raise ValueError('img does not have 10000 or 20440 pixels')

        return n_col, n_row

    def getPixelCountImage(self, **kwargs):
        return self.image



class subWindow(QMainWindow):
    # set up a signal so that the window closes when the main window closes
    # closeWindow = QtCore.pyqtSignal()
    #
    # replot = pyqtsignal()

    def __init__(self,parent=None):
        super(QMainWindow, self).__init__(parent)
        self.parent=parent

        self.eff_exp_time = .010  # units are s

        self.create_main_frame()
        self.activePixel = parent.activePixel
        self.parent.updateActivePix.connect(self.setActivePixel)
        self.a = parent.a
        self.spinbox_startTime = parent.spinbox_startTime
        self.spinbox_integrationTime = parent.spinbox_integrationTime
        self.spinbox_startLambda = parent.spinbox_startLambda
        self.spinbox_stopLambda = parent.spinbox_stopLambda
        self.image = parent.image
        self.beamFlagMask = parent.beamFlagMask
        self.apertureRadius = 2.27/2   # Taken from Seth's paper (not yet published in Jan 2018)
        self.apertureOn = False
        self.lineColor = 'blue'
        self.minLambda = parent.minLambda
        self.maxLambda = parent.maxLambda

    def create_main_frame(self):
        """
        Makes GUI elements on the window
        """
        self.main_frame = QWidget()

        # Figure
        self.dpi = 100
        self.fig = Figure((3.0, 2.0), dpi=self.dpi)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setParent(self.main_frame)
        self.ax = self.fig.add_subplot(111)

        # create a navigation toolbar for the plot window
        self.toolbar = NavigationToolbar(self.canvas, self)

        # create a vertical box for the plot to go in.
        vbox_plot = QVBoxLayout()
        vbox_plot.addWidget(self.canvas)

        # check if we need effective exposure time controls in the window, and add them if we do.
        try:
            self.spinbox_eff_exp_time
        except:
            pass
        else:
            label_exp_time = QLabel('effective exposure time [ms]')
            button_plot = QPushButton("Plot")

            hbox_expTimeControl = QHBoxLayout()
            hbox_expTimeControl.addWidget(label_exp_time)
            hbox_expTimeControl.addWidget(self.spinbox_eff_exp_time)
            hbox_expTimeControl.addWidget(button_plot)
            vbox_plot.addLayout(hbox_expTimeControl)

            self.spinbox_eff_exp_time.setMinimum(1)
            self.spinbox_eff_exp_time.setMaximum(200)
            self.spinbox_eff_exp_time.setValue(1000*self.eff_exp_time)
            button_plot.clicked.connect(self.plotData)

        vbox_plot.addWidget(self.toolbar)

        # combine everything into another vbox
        vbox_combined = QVBoxLayout()
        vbox_combined.addLayout(vbox_plot)

        # Set the main_frame's layout to be vbox_combined
        self.main_frame.setLayout(vbox_combined)

        # Set the overall QWidget to have the layout of the main_frame.
        self.setCentralWidget(self.main_frame)


    def draw(self):
        # The plot window calls this function
        self.canvas.draw()
        self.canvas.flush_events()


    def setActivePixel(self):
        self.activePixel = self.parent.activePixel
        # if self.parent.image[self.activePixel[0],self.activePixel[1]] ==0: #only plot data from good pixels
        #    self.lineColor = 'red'
        # else:
        #    self.lineColor = 'blue'
        try:
            self.plotData() # put this in a try statement in case it doesn't work. This way it won't kill the whole gui.
        except:
            pass


    def plotData(self):
        # just create a dummy function that we'll redefine in the child classes
        # this way the signal to update the plots is handled entirely
        # by this subWindow base class
        return

    def get_photon_list(self):
        # use this function to make the call to the correct obsfile method
        if self.apertureOn == True:
            photonList,aperture = self.a.getCircularAperturePhotonList(self.activePixel[0], self.activePixel[1], radius = self.apertureRadius, firstSec = self.spinbox_startTime.value(), integrationTime=self.spinbox_integrationTime.value(), wvlStart = self.spinbox_startLambda.value(), wvlStop=self.spinbox_stopLambda.value(), flagToUse=0)

        else:
            wvlStart=self.spinbox_startLambda.value()
            wvlStop=self.spinbox_stopLambda.value()
            t1 = time.time()

            # it's WAY faster to not specify start/stop wavelengths. If that cut isn't
            # necessary, don't specify those keywords.
            if wvlStart==self.minLambda and wvlStop==self.maxLambda:
                photonList = self.a.getPixelPhotonList(self.activePixel[0], self.activePixel[1], firstSec = self.spinbox_startTime.value(), integrationTime=self.spinbox_integrationTime.value())
                cmd = 'photonList = self.a.getPixelPhotonList(self.activePixel[0], self.activePixel[1], firstSec = self.spinbox_startTime.value(), integrationTime=self.spinbox_integrationTime.value())'
            elif wvlStart==self.minLambda:
                photonList = self.a.getPixelPhotonList(self.activePixel[0], self.activePixel[1], firstSec = self.spinbox_startTime.value(), integrationTime=self.spinbox_integrationTime.value(), wvlStart=self.spinbox_startLambda.value())
                cmd = 'photonList = self.a.getPixelPhotonList(self.activePixel[0], self.activePixel[1], firstSec = self.spinbox_startTime.value(), integrationTime=self.spinbox_integrationTime.value(), wvlStart=self.spinbox_startLambda.value())'
            elif wvlStop==self.maxLambda:
                photonList = self.a.getPixelPhotonList(self.activePixel[0], self.activePixel[1], firstSec = self.spinbox_startTime.value(), integrationTime=self.spinbox_integrationTime.value(), wvlStop=self.spinbox_stopLambda.value())
                cmd = 'photonList = self.a.getPixelPhotonList(self.activePixel[0], self.activePixel[1], firstSec = self.spinbox_startTime.value(), integrationTime=self.spinbox_integrationTime.value(), wvlStop=self.spinbox_stopLambda.value())'
            else:
                photonList = self.a.getPixelPhotonList(self.activePixel[0], self.activePixel[1], firstSec = self.spinbox_startTime.value(), integrationTime=self.spinbox_integrationTime.value(), wvlStart=self.spinbox_startLambda.value(),wvlStop=self.spinbox_stopLambda.value())
                cmd = 'photonList = self.a.getPixelPhotonList(self.activePixel[0], self.activePixel[1], firstSec = self.spinbox_startTime.value(), integrationTime=self.spinbox_integrationTime.value(), wvlStart=self.spinbox_startLambda.value(),wvlStop=self.spinbox_stopLambda.value())'
            t2 = time.time()

            print('\ncmd = ' + cmd)
            print('\nTime to getPixelPhotonList(): ', t2 - t1)

        return photonList



class timeStream(subWindow):
    # this class inherits from the subWindow class.
    def __init__(self,parent):

        self.spinbox_eff_exp_time = QDoubleSpinBox()  # make sure that the parent class will know that we need an eff_exp_time control

        # call the init function from the superclass 'subWindow'.
        super(timeStream, self).__init__(parent)
        self.setWindowTitle("Light Curve")
        self.plotData()
        self.draw()





    def plotData(self):
        self.ax.clear()

        self.photonList = self.get_photon_list()

        self.eff_exp_time = self.spinbox_eff_exp_time.value()/1000
        if type(self.a).__name__ == 'ObsFile':
            self.lightCurveIntensityCounts, self.lightCurveIntensity, self.lightCurveTimes = binnedRE.getLightCurve(self.photonList['Time']/1e6,self.spinbox_startTime.value(),self.spinbox_startTime.value()+self.spinbox_integrationTime.value(),self.eff_exp_time)
        else:
            self.lightCurveIntensityCounts, self.lightCurveIntensity, self.lightCurveTimes = binnedRE.getLightCurve(
                self.photonList['Time'] / 1e6, 0, self.spinbox_integrationTime.value(), self.eff_exp_time)

        self.ax.plot(self.lightCurveTimes,self.lightCurveIntensity,color = self.lineColor)
        self.ax.set_xlabel('time [seconds]')
        self.ax.set_ylabel('intensity [cps]')
        self.ax.set_title('pixel ({},{})' .format(self.activePixel[0],self.activePixel[1]))
        self.draw()




class intensityHistogram(subWindow):
    # this class inherits from the subWindow class.
    def __init__(self,parent):

        self.spinbox_eff_exp_time = QDoubleSpinBox()  #make sure that the parent class will know that we need an eff_exp_time control

        # call the init function from the superclass 'subWindow'.
        super(intensityHistogram, self).__init__(parent)
        self.setWindowTitle("Intensity Histogram")
        self.plotData()
        self.draw()


    def plotData(self):

        sstep = 1

        self.ax.clear()

        self.photonList = self.get_photon_list()
        ts = self.photonList['Time']/1e6  # timestamps in seconds
        dt = (ts[1:] - ts[:-1])
        deadtime = 0

        self.eff_exp_time = self.spinbox_eff_exp_time.value()/1000

        if type(self.a).__name__ == 'ObsFile':
            self.lightCurveIntensityCounts, self.lightCurveIntensity, self.lightCurveTimes = binnedRE.getLightCurve(ts,self.spinbox_startTime.value(),self.spinbox_startTime.value()+self.spinbox_integrationTime.value(),self.eff_exp_time)
        else:
            self.lightCurveIntensityCounts, self.lightCurveIntensity, self.lightCurveTimes = binnedRE.getLightCurve(
                self.photonList['Time'] / 1e6, 0, self.spinbox_integrationTime.value(), self.eff_exp_time)

        self.intensityHist, self.bins = binnedRE.histogramLC(self.lightCurveIntensityCounts)

        Nbins = max(30,len(self.bins))

        self.ax.bar(self.bins,self.intensityHist)
        self.ax.set_xlabel('intensity, counts per {:.3f} sec'.format(self.eff_exp_time))
        self.ax.set_ylabel('frequency')
        self.ax.set_title('pixel ({},{})' .format(self.activePixel[0],self.activePixel[1]))

        if np.sum(self.lightCurveIntensityCounts) > 0:
            mu = np.mean(self.lightCurveIntensityCounts)
            var = np.var(self.lightCurveIntensityCounts)

            # k = np.arange(Nbins)
            # poisson= np.exp(-mu)*np.power(mu,k)/factorial(k)
            # self.ax.plot(np.arange(len(poisson)),poisson,'.-c',label = 'Poisson')

            # Ic_final,Is_final,covMatrix = binnedRE.fitBlurredMR(self.bins,self.intensityHist,self.eff_exp_time)

            # self.ax.plot(np.arange(Nbins, step=sstep),binnedRE.blurredMR(np.arange(Nbins, step=sstep),Ic_final,Is_final),'.-k',label = 'blurred MR from curve_fit. Ic,Is = {:.2f}, {:.2f}'.format(Ic_final/self.eff_exp_time,Is_final/self.eff_exp_time))

            # get the bin-free fit of Ic, Is Ip
            I = 1 / np.mean(dt)
            p0 = I * np.ones(3) / 3.
            p1 = optimize.minimize(binfree.loglike, p0, (dt, deadtime),
                                   method='Newton-CG', jac=binfree._jacobean, hess=binfree._hessian).x

            self.ax.plot(np.arange(Nbins, step = sstep), binnedRE.loglike_planet_blurredMR(np.arange(Nbins, step = sstep), p1[0]*self.eff_exp_time, p1[2]*self.eff_exp_time, p1[2]*self.eff_exp_time)[1], 'k.-', label = f'bin-free Ic, Is, Ip = {p1[0]:.2}, {p1[1]:.2}, {p1[2]:.2}')

            try:
                IIc = np.sqrt(mu**2 - var + mu)
            except:
                pass
            else:
                IIs = mu - IIc
                self.ax.plot(np.arange(Nbins, step=sstep),binnedRE.blurredMR(np.arange(Nbins, step=sstep),IIc,IIs),'.-b',label = r'blurred MR from $\sigma$ and $\mu$. Ic,Is = {:.2f}, {:.2f}'.format(IIc/self.eff_exp_time,IIs/self.eff_exp_time))

            self.ax.set_title('pixel ({},{})' .format(self.activePixel[0],self.activePixel[1]))

            self.ax.legend()

        self.draw()






class spectrum(subWindow):
    # this class inherits from the subWindow class.
    def __init__(self,parent):
        # call the init function from the superclass 'subWindow'.
        super(spectrum, self).__init__(parent)
        self.setWindowTitle("Spectrum")
        self.plotData()
        self.draw()



    def plotData(self):
        self.ax.clear()
        temp = self.a.getPixelSpectrum(self.activePixel[0], self.activePixel[1], firstSec = self.spinbox_startTime.value(), integrationTime=self.spinbox_integrationTime.value())

        self.spectrum = temp['spectrum']
        self.wvlBinEdges = temp['wvlBinEdges']
        # self.effIntTime = temp['effIntTime']
        self.rawCounts = temp['rawCounts']

        self.wvlBinCenters = np.diff(self.wvlBinEdges)/2 + self.wvlBinEdges[:-1]


        self.ax.plot(self.wvlBinCenters,self.spectrum,'-o')
        self.ax.set_xlabel('wavelength [nm]')
        self.ax.set_ylabel('intensity [counts]')
        self.ax.set_title('pixel ({},{})' .format(self.activePixel[0],self.activePixel[1]))
        self.draw()




class pulseHeightHistogram(subWindow):
    # this class inherits from the subWindow class.
    def __init__(self,parent):
        # call the init function from the superclass 'subWindow'.
        super(pulseHeightHistogram, self).__init__(parent)
        self.setWindowTitle("Pulse Heights")
        self.plotData()
        self.draw()



    def plotData(self):
        self.ax.clear()

        pulseHeights = self.a.getPixelPhotonList(self.activePixel[0], self.activePixel[1])['Wavelength']

        hist,binEdges = np.histogram(pulseHeights,bins=100)

        binCenters = np.diff(binEdges)/2 + binEdges[:-1]


        self.ax.bar(binCenters,hist)
        self.ax.set_xlabel('raw phase [uncalibrated degrees]')
        self.ax.set_ylabel('[counts]')
        self.ax.set_title('pixel ({},{})' .format(self.activePixel[0],self.activePixel[1]))
        self.draw()














#####################################################################################






class main_window(QMainWindow):
    updateActivePix = pyqtSignal()

    def __init__(self,*argv,parent=None):
        QMainWindow.__init__(self,parent=parent)
        self.initialize_empty_arrays()
        self.setWindowTitle('oracle')
        self.resize(600,850)  # (600,850 works for clint's laptop screen. Units are pixels I think.)
        self.create_main_frame()
        self.create_status_bar()
        self.createMenu()
        self.plot_noise_image()
        if len(argv[0]) > 1:
            if os.path.isfile(argv[0][1]):
                self.filename = argv[0][1]
                if self.filename.endswith(".h5"):
                    self.load_data_from_h5(self.filename)
                elif self.filename.endswith(".img"):
                    print('handling of img files coming soon!')
                    self.load_log_filenames(self.filename)
                    self.load_data_from_img(self.filename)
                    self.load_filenames(self.filename)
                elif self.filename.endswith(".bin"):
                    self.load_log_filenames(self.filename)
                    self.load_data_from_bin(self.filename)
                    self.load_filenames(self.filename)
                else:
                    print('unrecognized file extension')
            else:
                print('file does not exist: \n', argv[0][1])


    def initialize_empty_arrays(self,n_col = 10,n_row = 10):
        self.n_col = n_col
        self.n_row = n_row
        self.IcMap = np.zeros(self.n_row*self.n_col).reshape((self.n_row,self.n_col))
        self.IsMap = np.zeros(self.n_row*self.n_col).reshape((self.n_row,self.n_col))
        self.IcIsMap = np.zeros(self.n_row*self.n_col).reshape((self.n_row,self.n_col))
        self.rawCountsImage = np.zeros(self.n_row*self.n_col).reshape((self.n_row,self.n_col))
        self.hotPixMask = np.zeros(self.n_row*self.n_col).reshape((self.n_row,self.n_col))
        self.hotPixCut = 2300
        self.image = np.zeros(self.n_row*self.n_col).reshape((self.n_row,self.n_col))
        self.activePixel = [0,0]
        self.sWindowList = []
        self.path = '/'
        self.filename_extension = ''


    def load_data_from_h5(self,*args):
        # a = ObsFile('/Users/clint/Documents/mazinlab/ScienceData/PAL2017b/20171004/1507175503.h5')
        if os.path.isfile(self.filename):
            try:
                self.a = ObsFile(self.filename)
            except:
                print('darkObsFile failed to load file. Check filename.\n',self.filename)
            else:
                print('data loaded from .h5 file')
                self.filename_label.setText(self.filename)
                self.initialize_empty_arrays(len(self.a.beamImage),len(self.a.beamImage[0]))
                self.beamFlagImage = np.transpose(self.a.beamFlagImage.read())
                self.beamFlagMask = self.beamFlagImage==0  #make a mask. 0 for good beam map
                self.makeHotPixMask()
                self.radio_button_beamFlagImage.setChecked(True)
                self.call_plot_method()
                # set the max integration time to the h5 exp time in the header
                self.expTime = self.a.getFromHeader('expTime')
                self.wvlBinStart = self.a.getFromHeader('wvlBinStart')
                self.wvlBinEnd = self.a.getFromHeader('wvlBinEnd')

                # set the max and min values for the lambda spinboxes
                # check if the data is wavecaled and set the limits on the spinboxes accordingly
                if self.a.getFromHeader('isWvlCalibrated'):
                    self.minLambda = self.wvlBinStart
                    self.maxLambda = self.wvlBinEnd
                else:
                    self.minLambda = -200
                    self.maxLambda = 200
                    self.label_startLambda.setText('start phase [uncal degrees]')
                    self.label_stopLambda.setText('stop phase [uncal degrees]')

                self.spinbox_stopLambda.setMinimum(self.minLambda)
                self.spinbox_startLambda.setMaximum(self.maxLambda)
                self.spinbox_stopLambda.setMaximum(self.maxLambda)
                self.spinbox_startLambda.setMinimum(self.minLambda)
                self.spinbox_startLambda.setValue(self.minLambda)
                self.spinbox_stopLambda.setValue(self.maxLambda)

                # set the max value of the integration time spinbox
                self.spinbox_startTime.setMinimum(0)
                self.spinbox_startTime.setMaximum(self.expTime)
                self.spinbox_integrationTime.setMinimum(0)
                self.spinbox_integrationTime.setMaximum(self.expTime)
                self.spinbox_integrationTime.setValue(self.expTime)


    def load_data_from_bin(self, filename):
        img_size = (146,140) # TODO: get rid of this hard coding

        if os.path.isfile(self.filename):
            try:
                self.a = binparse.ParsedBin([self.filename], img_size)
            except:
                print("coudn't load bin file")
            else:
                self.radio_button_rawCounts.setChecked(True)
                self.plot_count_image()
                self.filename_label.setText(self.filename)

            self.beamFlagMask = np.zeros(img_size[0]*img_size[1]).reshape(img_size)  # make a mask. 0 for good beam map
            
            
            
    def load_data_from_img(self, filename):
        if os.path.isfile(self.filename):
            try:
               self.a = img_object(self.filename)
            except:
               print("coudn't load img file")
            else:
               self.radio_button_rawCounts.setChecked(True)
               self.plot_count_image()
               self.filename_label.setText(self.filename)
        


    def spinbox_starttime_value_change(self):
        if type(self.a).__name__ == 'ParsedBin' or type(self.a).__name__ == 'img_object':
            try:
                filename = self.file_list_raw[np.where(self.timestamp_list==self.spinbox_startTime.value())[0][0]]
            except:
                print('filename does not exist in self.file_list_Raw')
                self.updateLogLabel(file_exists=False)
            else:
                self.filename = filename
                if type(self.a).__name__ == 'ParsedBin':
                    self.load_data_from_bin(self.filename)
                elif type(self.a).__name__ == 'img_object':
                    self.load_data_from_img(self.filename)
                self.updateLogLabel()






    def plotBeamImage(self):
        # check if obsfile object exists
        try:
            self.a
        except:
            print('\nNo obsfile object defined. Select H5 file to load.\n')
            return
        else:
            # clear the axes
            self.ax1.clear()

            self.image = self.beamFlagImage

            self.cbarLimits = np.array([np.amin(self.image),np.amax(self.image)])

            self.ax1.imshow(self.image,interpolation='none')
            self.fig.cbar.set_clim(np.amin(self.image),np.amax(self.image))
            self.fig.cbar.draw_all()

            self.ax1.set_title('beam flag image')

            self.ax1.axis('off')

            # self.cursor = Cursor(self.ax1, useblit=True, color='red', linewidth=.5)

            self.draw()




    def update_color_bar_limit(self):
        self.ax1.clear()

        if self.checkbox_colorbar_auto.isChecked():
            # colorbar auto
            self.cbarLimits = np.array([0, np.amax(self.image)])
            self.fig.cbar.set_clim(self.cbarLimits[0], self.cbarLimits[1])
            self.fig.cbar.draw_all()
        else:
            # colorbar manual
            self.cbarLimits = np.array([0, self.spinbox_colorBarMax.value()])
            self.fig.cbar.set_clim(self.cbarLimits[0], self.cbarLimits[1])
            self.fig.cbar.draw_all()
        self.ax1.imshow(self.image, interpolation='none', vmin=self.cbarLimits[0], vmax=self.cbarLimits[1])
        self.draw()





    def plot_count_image(self,*args):
        # check if file object exists
        try:
            self.a
        except:
            print('\nNo obsfile object defined. Select H5 file to load.\n')
            return
        else:
            # clear the axes
            self.ax1.clear()

            if type(self.a).__name__ == 'ObsFile':
                t1 = time.time()
                temp = self.a.getPixelCountImage(firstSec=self.spinbox_startTime.value(),
                                                 integrationTime=self.spinbox_integrationTime.value(), applyWeight=False, flagToUse=0,
                                                 wvlStart=self.spinbox_startLambda.value(),
                                                 wvlStop=self.spinbox_stopLambda.value())
                print('\nTime for getPixelCountImage = ', time.time() - t1)
                self.rawCountsImage = np.transpose(temp['image'])
                self.image = self.rawCountsImage
                self.image[np.where(np.logical_not(np.isfinite(self.image)))] = 0
                self.image = 1.0 * self.image / self.spinbox_integrationTime.value()
            elif type(self.a).__name__ == 'ParsedBin':
                self.image = self.a.getPixelCountImage()
            elif type(self.a).__name__ == 'img_object':
                self.image = self.a.getPixelCountImage()
            else:
                print('unrecognized object type: type(self.a).__name__ = ',type(self.a).__name__)

            # colorbar auto
            if self.checkbox_colorbar_auto.isChecked():
                self.cbarLimits = np.array([0, np.amax(self.image)])
                self.fig.cbar.set_clim(self.cbarLimits[0], self.cbarLimits[1])
                self.fig.cbar.draw_all()
            else:
                self.cbarLimits = np.array([0, self.spinbox_colorBarMax.value()])
                self.fig.cbar.set_clim(self.cbarLimits[0], self.cbarLimits[1])
                self.fig.cbar.draw_all()

            self.ax1.imshow(self.image,interpolation='none',vmin = self.cbarLimits[0],vmax = self.cbarLimits[1])

            self.ax1.set_title('Raw counts')

            self.ax1.axis('off')

            # TODO: fix the cursor. It was running super slow, so I turned it off.
            # self.cursor = Cursor(self.ax1, useblit=True, color='red', linewidth=.5)


            self.draw()



    def plot_ssd_image(self):
        # check if obsfile object exists
        try:
            self.a
        except:
            print('\nNo obsfile object defined. Select H5 file to load.\n')
            return
        else:
            self.ax1.clear() # clear the axes

            for col in range(self.n_col):
                print(f'column: {col}')
                for row in range(self.n_row):

                    self.photonList = self.a.getPixelPhotonList(col, row, firstSec=self.spinbox_startTime.value(),
                                                           integrationTime=self.spinbox_integrationTime.value(),
                                                           wvlStart=self.spinbox_startLambda.value(),
                                                           wvlStop=self.spinbox_stopLambda.value())
                    if len(self.photonList) == 0:
                        # skip this pixel and move on to the next one
                        continue

                    ts = self.photonList['Time'] / 1e6  # timestamps in seconds
                    dt = (ts[1:] - ts[:-1])
                    deadtime = 0

                    # get the bin-free fit of Ic, Is Ip
                    I = 1 / np.mean(dt)
                    p0 = I * np.ones(3) / 3.
                    Ic, Is, Ip = optimize.minimize(binfree.loglike, p0, (dt, deadtime),
                                           method='Newton-CG', jac=binfree._jacobean, hess=binfree._hessian).x

                    self.Ic_map[row][col] = Ic
                    self.Is_map[row][col] = Is
                    self.Ip_map[row][col] = Ip

            if self.radio_button_ic.isChecked():
                self.image = self.Ic_map
            elif self.radio_button_is.isChecked():
                self.image = self.Is_map
            elif self.radio_button_ip.isChecked():
                self.image = self.Ip_map
            elif self.radio_button_ic_is.isChecked():
                self.image = self.Ic_map/self.IsMap
            else:
                print('not sure how we got here')
                return


            # self.image[np.where(np.logical_not(np.isfinite(self.image)))]=0
            # self.image = self.rawCountsImage*self.beamFlagMask
            # self.image = self.rawCountsImage*self.beamFlagMask*self.hotPixMask
            # self.image = 1.0*self.image/self.spinbox_integrationTime.value()

            # self.cbarLimits = np.array([np.amin(self.image),np.amax(self.image)])

            self.ax1.imshow(self.image,interpolation='none',vmin = self.cbarLimits[0],vmax = self.cbarLimits[1])

            self.fig.cbar.set_clim(self.cbarLimits[0],self.cbarLimits[1])
            self.fig.cbar.draw_all()

            self.ax1.set_title('SSD image')

            self.ax1.axis('off')

            # self.cursor = Cursor(self.ax1, useblit=True, color='red', linewidth=.5)

            self.draw()




    def plot_noise_image(self,*args):
        # clear the axes
        self.ax1.clear()

        # debugging- generate some noise to plot
        self.image = np.random.randn(self.n_row,self.n_col)

        self.foo = self.ax1.imshow(self.image,interpolation='none')
        self.cbarLimits = np.array([np.amin(self.image),np.amax(self.image)])
        self.fig.cbar.set_clim(self.cbarLimits[0],self.cbarLimits[1])
        self.fig.cbar.draw_all()

        self.ax1.set_title('some generated noise...')

        self.ax1.axis('off')

        # self.cursor = Cursor(self.ax1, useblit=True, color='red', linewidth=.5)

        self.draw()



    def call_plot_method(self):
        if self.radio_button_ic.isChecked() or self.radio_button_is.isChecked() or self.radio_button_ip.isChecked() or self.radio_button_ic_is.isChecked():
            self.plot_ssd_image()
        elif self.radio_button_beamFlagImage.isChecked() == True:
            self.plotBeamImage()
        elif self.radio_button_rawCounts.isChecked() == True:
            self.plot_count_image()
        else:
            self.plot_noise_image()




    def makeHotPixMask(self):
        # if self.hotPixMask[row][col] = 0, it's a hot pixel. If 1, it's good.
        temp = self.a.getPixelCountImage(firstSec = 0, integrationTime=1,applyWeight=False,flagToUse = 0)
        rawCountsImage = np.transpose(temp['image'])
        for col in range(self.n_col):
            for row in range(self.n_row):
                if rawCountsImage[row][col] < self.hotPixCut:
                    self.hotPixMask[row][col] = 1




    def create_main_frame(self):
        """
        Makes GUI elements on the window
        """
        # Define the plot window.
        self.main_frame = QWidget()
        self.dpi = 100
        self.fig = Figure((5.0, 10.0), dpi=self.dpi, tight_layout=True) #define the figure, set the size and resolution
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setParent(self.main_frame)
        self.ax1 = self.fig.add_subplot(111)
        self.foo = self.ax1.imshow(self.image,interpolation='none')
        self.fig.cbar = self.fig.colorbar(self.foo)


        button_plot = QPushButton("Plot image")
        button_plot.setEnabled(True)
        button_plot.setToolTip('Click to update image.')
        button_plot.clicked.connect(self.call_plot_method)

        # spinboxes for the start & stop times
        self.spinbox_startTime = QDoubleSpinBox()
        self.spinbox_integrationTime = QDoubleSpinBox()

        # labels for the start/stop time spinboxes
        label_startTime = QLabel('start time')
        label_integrationTime = QLabel('integration time')

        # spinboxes for the start & stop wavelengths
        self.spinbox_startLambda = QDoubleSpinBox()
        self.spinbox_stopLambda = QDoubleSpinBox()

        # labels for the start/stop time spinboxes
        self.label_startLambda = QLabel('start wavelength [nm]')
        self.label_stopLambda = QLabel('stop wavelength [nm]')

        # label for the filenames
        self.filename_label = QLabel('no file loaded')

        # label for the active pixel
        self.activePixel_label = QLabel('Active Pixel ({},{}) {}'.format(self.activePixel[0],self.activePixel[1],self.image[self.activePixel[1],self.activePixel[0]]))

        # make the radio buttons
        self.radio_button_ic = QRadioButton("Ic")
        self.radio_button_is = QRadioButton("Is")
        self.radio_button_ip = QRadioButton("Ip")
        self.radio_button_ic_is = QRadioButton("Ic/Is")
        self.radio_button_beamFlagImage = QRadioButton("Beam Flag Image")
        self.radio_button_rawCounts = QRadioButton("Raw Counts")
        self.radio_button_rawCounts.setChecked(True)

        # make a label to display timestamp in human readable format
        self.label_log = QLabel('foobar!')

        # make a checkbox for the colorbar autoscale
        self.checkbox_colorbar_auto = QCheckBox()
        self.checkbox_colorbar_auto.setChecked(False)
        self.checkbox_colorbar_auto.stateChanged.connect(self.update_color_bar_limit)

        label_checkbox_colorbar_auto = QLabel('Auto colorbar')

        self.spinbox_colorBarMax = QSpinBox()
        self.spinbox_colorBarMax.setRange(1, 2500)
        self.spinbox_colorBarMax.setValue(2000)
        self.spinbox_colorBarMax.valueChanged.connect(self.update_color_bar_limit)

        # create a vertical box for the plot to go in.
        vbox_plot = QVBoxLayout()
        vbox_plot.addWidget(self.canvas)

        # create a v box for the timespan spinboxes
        vbox_timespan = QVBoxLayout()
        vbox_timespan.addWidget(label_startTime)
        vbox_timespan.addWidget(self.spinbox_startTime)
        vbox_timespan.addWidget(label_integrationTime)
        vbox_timespan.addWidget(self.spinbox_integrationTime)

        # create a v box for the wavelength spinboxes
        vbox_lambda = QVBoxLayout()
        vbox_lambda.addWidget(self.label_startLambda)
        vbox_lambda.addWidget(self.spinbox_startLambda)
        vbox_lambda.addWidget(self.label_stopLambda)
        vbox_lambda.addWidget(self.spinbox_stopLambda)

        # create an h box for the buttons
        hbox_buttons = QHBoxLayout()
        hbox_buttons.addWidget(button_plot)

        # create an h box for the time and lambda v boxes
        hbox_time_lambda = QHBoxLayout()
        hbox_time_lambda.addLayout(vbox_timespan)
        hbox_time_lambda.addLayout(vbox_lambda)

        # create a v box combining spinboxes and buttons
        vbox_time_lambda_buttons = QVBoxLayout()
        vbox_time_lambda_buttons.addLayout(hbox_time_lambda)
        vbox_time_lambda_buttons.addLayout(hbox_buttons)

        #make a vbox for the autoscale colorbar
        hbox_autoscale = QHBoxLayout()
        hbox_autoscale.addWidget(label_checkbox_colorbar_auto)
        hbox_autoscale.addWidget(self.checkbox_colorbar_auto)
        hbox_autoscale.addWidget(self.spinbox_colorBarMax)

        # create a v box for the radio buttons
        vbox_radio_buttons = QVBoxLayout()
        vbox_radio_buttons.addLayout(hbox_autoscale)
        vbox_radio_buttons.addWidget(self.radio_button_ic)
        vbox_radio_buttons.addWidget(self.radio_button_is)
        vbox_radio_buttons.addWidget(self.radio_button_ip)
        vbox_radio_buttons.addWidget(self.radio_button_ic_is)
        vbox_radio_buttons.addWidget(self.radio_button_beamFlagImage)
        vbox_radio_buttons.addWidget(self.radio_button_rawCounts)

        # create a h box for the log label
        vbox_log_label = QVBoxLayout()
        vbox_log_label.addWidget(self.label_log)

        # create a h box combining the spinboxes, buttons, radio buttons, human readable timestamp
        hbox_controls = QHBoxLayout()
        hbox_controls.addLayout(vbox_time_lambda_buttons)
        hbox_controls.addLayout(vbox_radio_buttons)
        hbox_controls.addLayout(vbox_log_label)

        # create a v box for showing the files that are loaded in memory
        vbox_filenames = QVBoxLayout()
        vbox_filenames.addWidget(self.filename_label)
        vbox_filenames.addWidget(self.activePixel_label)


        # Now create another vbox, and add the plot vbox and the button's hbox to the new vbox.
        vbox_combined = QVBoxLayout()
        vbox_combined.addLayout(vbox_plot)
        vbox_combined.addLayout(hbox_controls)
        vbox_combined.addLayout(vbox_filenames)

        # Set the main_frame's layout to be vbox_combined
        self.main_frame.setLayout(vbox_combined)

        # Set the overall QWidget to have the layout of the main_frame.
        self.setCentralWidget(self.main_frame)

        # set up the pyqt5 events
        cid = self.fig.canvas.mpl_connect('motion_notify_event', self.hover_canvas)
        cid2 = self.fig.canvas.mpl_connect('button_press_event', self.mouse_pressed)
        cid3 = self.fig.canvas.mpl_connect('scroll_event', self.scroll_ColorBar)


        self.logPath = '/'


    def draw(self):
        # The plot window calls this function
        self.canvas.draw()
        self.canvas.flush_events()


    def hover_canvas(self,event):
        if event.inaxes is self.ax1:
            col = int(round(event.xdata))
            row = int(round(event.ydata))
            if row < self.n_row and col < self.n_col:
                self.status_text.setText('({:d},{:d}) {}'.format(col,row,self.image[row,col]))

    def scroll_ColorBar(self,event):
        if event.inaxes is self.fig.cbar.ax:
            stepSize = 0.1  #fractional change in the colorbar scale
            if event.button == 'up':
                self.cbarLimits[1] *= (1 + stepSize)   #increment by step size
                self.fig.cbar.set_clim(self.cbarLimits[0],self.cbarLimits[1])
                self.fig.cbar.draw_all()
                self.ax1.imshow(self.image,interpolation='none',vmin = self.cbarLimits[0],vmax = self.cbarLimits[1])
            elif event.button == 'down':
                self.cbarLimits[1] *= (1 - stepSize)   #increment by step size
                self.fig.cbar.set_clim(self.cbarLimits[0],self.cbarLimits[1])
                self.fig.cbar.draw_all()
                self.ax1.imshow(self.image,interpolation='none',vmin = self.cbarLimits[0],vmax = self.cbarLimits[1])
            else:
                pass

        self.draw()




    def mouse_pressed(self,event):
        # print('\nclick event registered!\n')
        if event.inaxes is self.ax1:  #check if the mouse-click was within the axes.
            # print('%s click: button=%d, x=%d, y=%d, xdata=%f, ydata=%f' %('double' if event.dblclick else 'single', event.button,event.x, event.y, event.xdata, event.ydata))

            if event.button == 1:
                # print('\nit was the left button that was pressed!\n')
                col = int(round(event.xdata))
                row = int(round(event.ydata))
                self.activePixel = [col,row]
                self.activePixel_label.setText('Active Pixel ({},{}) {}'.format(self.activePixel[0],self.activePixel[1],self.image[self.activePixel[1],self.activePixel[0]]))

                self.updateActivePix.emit()  # emit a signal for other plots to update

            elif event.button == 3:
                print('\nit was the right button that was pressed!\n')

        elif event.inaxes is self.fig.cbar.ax:   #reset the scale bar
            if event.button == 1:
                self.cbarLimits = np.array([np.amin(self.image),np.amax(self.image)])
                self.fig.cbar.set_clim(self.cbarLimits[0],self.cbarLimits[1])
                self.fig.cbar.draw_all()
                self.ax1.imshow(self.image,interpolation='none',vmin = self.cbarLimits[0],vmax = self.cbarLimits[1])
                self.draw()
        else:
            pass





    def create_status_bar(self):
        # Using code from ARCONS-pipeline as an example:
        # ARCONS-pipeline/util/popup.py
        self.status_text = QLabel("")
        self.statusBar().addWidget(self.status_text, 1)


    def createMenu(self):
        # Using code from ARCONS-pipeline as an example:
        # ARCONS-pipeline/util/quicklook.py
        self.menubar = self.menuBar()
        self.fileMenu = self.menubar.addMenu("&File")

        open_h5_file_button = QAction(QIcon('exit24.png'), 'Open H5 File', self)
        open_h5_file_button.setShortcut('Ctrl+O')
        open_h5_file_button.setStatusTip('Open an H5 File')
        open_h5_file_button.triggered.connect(self.get_h5_file_name_from_user)
        self.fileMenu.addAction(open_h5_file_button)

        open_bin_file_button = QAction(QIcon('exit24.png'), 'Open bin File', self)
        open_bin_file_button.setShortcut('Ctrl+b')
        open_bin_file_button.setStatusTip('Open a bin File')
        open_bin_file_button.triggered.connect(self.get_bin_file_name_from_user)
        self.fileMenu.addAction(open_bin_file_button)

        exitButton = QAction(QIcon('exit24.png'), 'Exit', self)
        exitButton.setShortcut('Ctrl+Q')
        exitButton.setStatusTip('Exit application')
        exitButton.triggered.connect(self.close)
        self.fileMenu.addAction(exitButton)

        # make a menu for plotting
        self.plotMenu = self.menubar.addMenu("&Plot")
        plotLightCurveButton = QAction('Light Curve', self)
        plotLightCurveButton.triggered.connect(self.makeTimestreamPlot)
        plotIntensityHistogramButton = QAction('Intensity Histogram',self)
        plotIntensityHistogramButton.triggered.connect(self.makeIntensityHistogramPlot)
        plotSpectrumButton = QAction('Spectrum',self)
        plotSpectrumButton.triggered.connect(self.makeSpectrumPlot)
        plotPhaseHistButton = QAction('Phase Height Histogram',self)
        plotPhaseHistButton.triggered.connect(self.makePulseHeightHistogramPlot)
        self.plotMenu.addAction(plotLightCurveButton)
        self.plotMenu.addAction(plotIntensityHistogramButton)
        self.plotMenu.addAction(plotSpectrumButton)
        self.plotMenu.addAction(plotPhaseHistButton)

        self.menubar.setNativeMenuBar(False) # This is for MAC OS

    def get_h5_file_name_from_user(self):
        # look at this website for useful examples
        # https://pythonspot.com/pyqt5-file-dialog/
        try:def_loc = os.environ['MKID_DATA_DIR']
        except KeyError:def_loc='.'
        filename, _ = QFileDialog.getOpenFileName(self, 'Select One File', def_loc,filter = '*.h5')

        self.filename = filename
        self.load_data_from_h5(self.filename)


    def get_bin_file_name_from_user(self):
        try:def_loc = os.environ['MKID_DATA_DIR']
        except KeyError:def_loc='.'
        filename, _ = QFileDialog.getOpenFileName(self, 'Select One File', def_loc,filter = '*.bin')

        self.filename = filename
        self.load_bin_filenames(self.filename)


    def load_filenames(self, filename):
        print('loading filenames\n')

        self.path = os.path.dirname(filename)
        _, self.filename_extension = os.path.splitext(filename)
        file_list_raw = []
        timestamp_list = np.array([],dtype=int)
        ii = 0
        for file in os.listdir(self.path):
            if file.endswith(self.filename_extension):
                file_list_raw = file_list_raw + [os.path.join(self.path, file)]
                timestamp_list = np.append(timestamp_list, np.fromstring(file[:-4], dtype=int, sep=' ')[0])
            else:
                continue
            ii += 1

        # the files may not be in chronological order, so let's enforce it
        file_list_raw = np.asarray(file_list_raw)
        file_list_raw = file_list_raw[np.argsort(timestamp_list)]
        timestamp_list = np.sort(np.asarray(timestamp_list))

        self.file_list_raw = file_list_raw
        self.timestamp_list = timestamp_list

        print('\nfound {:d} '.format(len(self.timestamp_list)) + self.filename_extension + ' files\n')
        print('first timestamp: {:d}'.format(self.timestamp_list[0]))
        print('last timestamp:  {:d}\n'.format(self.timestamp_list[-1]))

        self.initialize_spinbox_values(filename)


    def initialize_spinbox_values(self, filename):
        # set the max and min values for the lambda spinboxes
        self.minLambda = -200
        self.maxLambda = 200
        self.label_startLambda.setText('start phase [uncal degrees]')
        self.label_stopLambda.setText('stop phase [uncal degrees]')
        self.spinbox_stopLambda.setMinimum(self.minLambda)
        self.spinbox_startLambda.setMaximum(self.maxLambda)
        self.spinbox_stopLambda.setMaximum(self.maxLambda)
        self.spinbox_startLambda.setMinimum(self.minLambda)
        self.spinbox_startLambda.setValue(self.minLambda)
        self.spinbox_stopLambda.setValue(self.maxLambda)

        # set the max value of the integration time spinbox
        if type(self.a).__name__ == 'ParsedBin' or type(self.a).__name__ == 'img_object':
            self.spinbox_startTime.setMinimum(self.timestamp_list[0])
            self.spinbox_startTime.setMaximum(self.timestamp_list[-1])
        self.spinbox_startTime.valueChanged.connect(self.spinbox_starttime_value_change)
        self.spinbox_startTime.setValue(np.fromstring(os.path.basename(filename)[:-4], dtype=int, sep=' ')[0])

        self.spinbox_integrationTime.setMinimum(0)
        self.spinbox_integrationTime.setMaximum(1)
        self.spinbox_integrationTime.setValue(1)


    def updateLogLabel(self, file_exists = True):

        timestamp = self.spinbox_startTime.value()

        # check if self.logTimestampList has more than zero entries. If not, return.
        if len(self.logTimestampList) == 0:
            text = datetime.datetime.fromtimestamp(timestamp).strftime(
                '%Y-%m-%d %H:%M:%S\n\n') + 'no log file found.\n Check log file path.'
            self.label_log.setText(text)
            return

        # check if the file exists, if not then return
        if not file_exists:
            text = datetime.datetime.fromtimestamp(timestamp).strftime(
                '%Y-%m-%d %H:%M:%S\n\n') + 'no .bin file found'
            self.label_log.setText(text)
            return

        # check if a nearby log file exists, then pick the closest one
        diffs = timestamp - self.logTimestampList
        if np.sum(np.abs(diffs) < 3600) == 0:  # nearby means within 1 hour.
            text = datetime.datetime.fromtimestamp(timestamp).strftime(
                '%Y-%m-%d %H:%M:%S\n\n') + 'nearest log is ' + str(np.amin(diffs)) + '\nseconds away from bin'
            self.label_log.setText(text)
            return

        diffs[np.where(diffs < 0)] = np.amax(diffs)

        logLabelTimestamp = self.logTimestampList[np.argmin(diffs)]

        labelFilename = self.logFilenameList[np.where(self.logTimestampList == logLabelTimestamp)[0][0]]

        # print('labelFilename is ', os.path.join(os.environ['MKID_RAW_PATH'],labelFilename))
        # fin=open(os.path.join(os.environ['MKID_RAW_PATH'],labelFilename),'r')
        with open(os.path.join(self.logPath, labelFilename), 'r') as fin:
            text = 'data timestamp:\n' + datetime.datetime.fromtimestamp(timestamp).strftime(
                '%Y-%m-%d %H:%M:%S') + '\n\nLogfile time:\n' + datetime.datetime.fromtimestamp(
                logLabelTimestamp).strftime('%Y-%m-%d %H:%M:%S\n') + '\n' + labelFilename[:-4] + '\n' + fin.read()
            self.label_log.setText(text)


    def load_log_filenames(self,filename):
        # check if directory exists
        self.logPath = os.path.dirname(filename)
        if not os.path.exists(self.logPath):
            text = 'log file path not found.\n Check log file path.'
            self.label_log.setText(text)

            self.logTimestampList = np.asarray([])
            self.logFilenameList = np.asarray([])

            return

        # load the log filenames
        print('loading log filenames\n')
        logFilenameList = []
        logTimestampList = []

        for logFilename in os.listdir(self.logPath):

            if logFilename.endswith("telescope.log"):
                continue
            elif logFilename.endswith(".log"):
                logFilenameList.append(logFilename)
                logTimestampList.append(np.fromstring(logFilename[:10], dtype=int, sep=' ')[0])

        # the files may not be in chronological order, so let's enforce it
        logFilenameList = np.asarray(logFilenameList)
        logFilenameList = logFilenameList[np.argsort(logTimestampList)]
        logTimestampList = np.sort(np.asarray(logTimestampList))

        self.logTimestampList = np.asarray(logTimestampList)
        self.logFilenameList = logFilenameList



    def makeTimestreamPlot(self):
        sWindow = timeStream(self)
        sWindow.show()
        self.sWindowList.append(sWindow)

    def makeIntensityHistogramPlot(self):
        sWindow = intensityHistogram(self)
        sWindow.show()
        self.sWindowList.append(sWindow)

    def makeSpectrumPlot(self):
        sWindow = spectrum(self)
        sWindow.show()
        self.sWindowList.append(sWindow)

    def makePulseHeightHistogramPlot(self):
        sWindow = pulseHeightHistogram(self)
        sWindow.show()
        self.sWindowList.append(sWindow)


if __name__ == "__main__":
    a = QApplication(sys.argv)
    foo = main_window(sys.argv)
    foo.show()
    sys.exit(a.exec_())
