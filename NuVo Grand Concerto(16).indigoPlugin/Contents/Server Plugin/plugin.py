#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# NuVo Grand Concerto Plugin for Indigo
# Developed by Jeremy Swancoat
# modified by Monstergerm for 16 Nuvo zones and iTunes Server as possible Music source
# various code refinements
# added support for control of iTunes from Nuvo Keypads
# added support for using Indigo with Nuvo via iTunes plugin or iTunes Local Control plugin
# updated logging system
# added custom state icons for Indigo UI
# added many additional commands to control Nuvo GC system
# added support for display of all metadata info from iTunes (including track info) on Nuvo Keypads
# added writing track info to Indigo variables for use on control pages or triggers
# This plugin benefits from iTunes plugin (for getting some metadata) and iTunes Local Control plugin (for getting playlist name and track info).
# This plugin should continue working after iTunes plugin is deprecated using a combination of iTunes Local Control and Airfoil Pro.
# This plugin is compatible with Python 2.7 and Python 3.10 and requires Indigo 2022.x and higher in its default configuration for Python 3 (Server API v3.0).
# https://forums.indigodomo.com/viewtopic.php?f=134&t=8312

from datetime import datetime
import os
import sys
import platform
import time
import logging
import serial
import requests
import socket
import six
try:
    import indigo
except ImportError:
    pass

# Note the "indigo" module is automatically imported and made available inside
# our global name space by the host process. 

kLogLevelList = ['Detailed Debug', 'Debug', 'Info', 'Warning', 'Error', 'Critical']
statuslist = ("Normal","Idle","Playing","Paused","Fast Forward","Rewind","Play Shuffle","Play Repeat","Play Shuffle Repeat")


##################################################################################################
class Plugin(indigo.PluginBase):

	##############################################################################################
	# Required Methods
	##############################################################################################
	##############################################################################################
	def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
		# Call the base class's init method
		indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

		# ============================ Configure Logging =================================
		# Set the format and level handlers for the logger
		try:
			self.logLevel = int(self.pluginPrefs[u"logLevel"])
		except:
			self.logLevel = logging.INFO
		self.indigo_log_handler.setLevel(self.logLevel)

		# Setting log level of private plugin log handler to only log threaddebug if this is the setting in logging preferences
		log_format = '%(asctime)s.%(msecs)03d\t%(levelname)-10s\t%(name)s.%(funcName)-28s %(msg)s'
		self.plugin_file_handler.setFormatter(logging.Formatter(fmt=log_format, datefmt='%Y-%m-%d %H:%M:%S'))
		if self.logLevel == 5:
			self.plugin_file_handler.setLevel(logging.THREADDEBUG)
		else:
			self.plugin_file_handler.setLevel(logging.DEBUG)
		
		# ================================================================================

		self.conn = None
		self.portEnabled = False
		self.commQueue = []
		self.zonedev = {}      # self.zonedev is a dictionary of the Zone Identifier and the device using it.
		self.inputdev = {}     # self.inputdev is a dictionary of the Source Identifier and the device using it.
		self.inputnuvonet = {} # self.inputnuvonet is a dictionary of Nuvonet Sources like the iPod or MPS-4.
		self.inputname = {}
		self.inputlastst = {}
		self.inputremote = {}
		self.spDir = {}        # self.spDir is a dictionary of Shairport Device IDs and the Source they are assigned to.
		self.varDir = {}       # self.varDir is a dictionary of Indigo Variable IDs and the Source they are assigned to.
		self.kShairportId = "com.jeremyswancoat.indigoplugin.shairportsync"
		
		#self.inputname needs it's keys initialized at least at the start...
		self.inputname['S1'] = ""
		self.inputname['S2'] = ""
		self.inputname['S3'] = ""
		self.inputname['S4'] = ""
		self.inputname['S5'] = ""
		self.inputname['S6'] = ""
		
		indigo.variables.subscribeToChanges()
		self.pluginstartup = True
		self.statlast = {}
					
	########################################
	def __del__(self):
		indigo.PluginBase.__del__(self)
		
	########################################
	def startup(self):
		# startup process for the serial device. Other than open the serial port, there should be none really. It just runs.
		self.logger.debug(u"Startup Called. Log Levels are set to \"{}\".".format(kLogLevelList[int(self.logLevel/10)]))
		
		spacer = " " * 35
		environment_state = u"\n"
		environment_state += spacer + u"="*20 + u" Initializing New Plugin Session " + u"="*54 +"\n"
		environment_state += spacer + u"{0:<20} {1}\n".format("Plugin name:", self.pluginDisplayName)
		environment_state += spacer + u"{0:<20} {1}\n".format("Plugin version:", self.pluginVersion)
		environment_state += spacer + u"{0:<20} {1}\n".format("Plugin ID:", self.pluginId)
		environment_state += spacer + u"{0:<20} {1}\n".format("Plugin Log Level:", kLogLevelList[int(self.logLevel/10)])
		environment_state += spacer + u"{0:<20} {1}\n".format("Indigo version:", indigo.server.version)
		environment_state += spacer + u"{0:<20} {1}\n".format("Python version:", sys.version.replace('\n', ''))
		environment_state += spacer + u"{0:<20} {1}\n".format("Mac OS Version:", platform.mac_ver()[0])
		environment_state += spacer + u"{0:<20} {1}\n".format("Process ID:", os.getpid())
		environment_state += spacer + u"{0:{1}^107}\n".format("", "=")
		self.logger.info(environment_state)

		#set PY2 and PY3 to true or false dependent on the active Python version
		self.PY2 = sys.version_info[0] == 2
		self.PY3 = sys.version_info[0] == 3
		
		if self.conn is None:
			pass
		else:
			self.conn.close()
		self.portEnabled = False

		# critical delay for plugin to properly close and reopen serial port
		time.sleep(0.5)
		
		serialUrl = self.getSerialPortUrl(self.pluginPrefs, u"serialport")
		if serialUrl == "":
			pass
		else:
			self.logger.info("Serial Port URL is " + serialUrl)
			self.conn = self.openSerial(u"NuVo Grand Concerto", serialUrl, 57600, stopbits=1, timeout=0.1, writeTimeout=1)
			
		if self.conn is not None:
			self.portEnabled = True
			self.logger.info("Serial Port Open at " + serialUrl)
		
		for s in range(1, 7):
			srclbl = "S" + str(s)
			self.commQueue.append(srclbl + "ACTIVE?")
			self.commQueue.append(srclbl + "NAME?")

		indigo.server.subscribeToBroadcast(self.kShairportId,u"startingBcast",u"startingBcast")
		indigo.server.subscribeToBroadcast(self.kShairportId,u"endingBcast",u"endingBcast")
		indigo.server.subscribeToBroadcast(self.kShairportId,u"ShairportData",u"receiveBcast")
		
	######################################################################################
	# Indigo Device Start/Stop
	######################################################################################
	def startingBcast(self):
		self.logger.info("Shairport Broadcast Starting")
	
	def endingBcast(self):
		self.logger.info("Shairport Broadcast Stopping")
		
	def receiveBcast(self, arg):
		self.logger.debug(u"-----------Broadcast Received----------")
		self.logger.debug(u"Dev ID: " + str(arg[0]))
		self.logger.debug(u"State: " + str(arg[1]))
		if arg[0] in self.spDir:
			self.logger.debug(str(arg[0]) + " found in spDir")
			inputcode = self.spDir[arg[0]]
			self.logger.debug(str(arg[0]) + " assigned to " + self.inputdev[inputcode].name)
			if inputcode in self.inputdev:
				stateid = arg[1]
				mdata = arg[2]
				if stateid == 'nowplaying':
					if mdata == True:
						self.inputlastst[inputcode] = 0
					else:
						self.inputlastst[inputcode] = round(time.time(),0)
						servdev = self.inputdev[inputcode]
						if servdev.pluginProps["repTrackTime"] == True:
							length = 10 * self.timeToSec(servdev.states["tracklen"])
							prog = 10 * self.timeToSec(servdev.states["trackprog"])
						else:
							length = 0
							prog = 0
						self.commQueue.append(inputcode + "DISPINFO," + str(length) + "," + str(prog) + ",0")
				elif stateid == 'timeDict':
					if mdata['nowplaying'] == True:
						zstate = 2
					else:
						zstate = 0
					length = 10 * int(mdata['tracklen'])
					prog = 10 * int(mdata['progsec'])
					self.commQueue.append(inputcode + "DISPINFO," + str(length) + "," + str(prog) + "," + str(zstate))
				elif stateid == 'clearData':
					self.resetSourceMetaData(inputcode)
				elif stateid == 'bcastDict':
					dev = self.inputdev[inputcode]
					for Ln in range(1, 5):
						primst = dev.pluginProps["spLine" + str(Ln) + "p"]
						secst = dev.pluginProps["spLine" + str(Ln) + "s"]
						primd = mdata[primst]
						secd = mdata[secst]
						if primst == "none":
							scdata = ""
						elif primd != "":
							scdata = primd
						else:
							scdata = secd
						self.commQueue.append(inputcode + "DISPLINE" + str(Ln) + "\"" + scdata + "\"")
					self.inputremote[inputcode]['clientip'] = mdata['clientip']
					self.inputremote[inputcode]['srcremport'] = mdata['srcremport']
					self.inputremote[inputcode]['artoken'] = mdata['artoken']
					self.inputremote[inputcode]['dacpid'] = mdata['dacpid']
			
	def variableUpdated(self, origVar, newVar):
		varid = str(newVar.id)
		if varid in self.varDir:               # this looks for updated variable IDs associated with non-Nuvo net sources.
			inputcode = self.varDir[varid]     # this is the source code, e.g. S6
			dev = self.inputdev[inputcode]     # this is the Indigo source device that has updated variable info
			#self.logger.threaddebug(self.varDir)
			self.logger.debug(u"Variable update triggered")
			mData3last = dev.states["mData3"]  # will be sourcename after metadata have been cleared
			######### sending updates for keypad display lines which have an updated variable #########
			for Ln in range(1, 5):
				if dev.pluginProps["vLine" + str(Ln)] == varid or mData3last == self.inputname[inputcode]:
					vLine = "vLine" + str(Ln)
					varid = int(dev.pluginProps[vLine])
					newvalue = indigo.variables[varid].value  # cannot use str() function
					newvalue = newvalue.encode('latin-1', 'ignore')  # byte object in Python 3, strips all ASCII >255 characters for compatibility with Nuvo
					newvalue = newvalue.decode('latin-1')   # converts byte object back to str object
					newvalue = newvalue.replace("\"","''")    # replaces troublesome double quotations
					self.commQueue.append(inputcode + "DISPLINE" + str(Ln) + "\"" + newvalue + "\"")
					self.logger.debug(u"Variable update found: " + inputcode + u"DISPLINE" + str(Ln) + u"\"" + newvalue + u"\"")
			######### sending track info from variables to Nuvo #########
			varid = int(dev.pluginProps["vDur"])
			nuvoXvalue = indigo.variables[varid].value
			varid = int(dev.pluginProps["vPos"])
			nuvoYvalue = indigo.variables[varid].value
			varid = int(dev.pluginProps["vStat"])
			nuvoZvalue = indigo.variables[varid].value
			self.commQueue.append(inputcode + "DISPINFO," + nuvoXvalue + "," + nuvoYvalue + "," + nuvoZvalue)
			self.logger.debug(u"Sending track update: " + inputcode + u"DISPINFO," + nuvoXvalue + u"," + nuvoYvalue + u"," + nuvoZvalue)
	
	def shutdown(self):
		# close serial port here
		self.logger.debug(u"Shutdown Called")
		if self.conn is None:
			pass
		else:
			self.conn.close()
		self.logger.info(u"Serial Port Closed")
		
	def genSpDevs(self, filter, valuesDict, typeID, targetID):
		devlist = []
		for dev in indigo.devices.iter(self.kShairportId + ".shairport"):
			devlist.append((dev.id, dev.name))
		return devlist

	def genSpMdList(self, filter, valuesDict, typeID, targetID):
		sourcelist = []
		sourcelist.append(("none","None (Leave Blank)"))
		sourcelist.append(("added","Date Added"))
		sourcelist.append(("album","Album"))
		sourcelist.append(("artist","Artist"))
		sourcelist.append(("albumartist","Album Artist"))
		sourcelist.append(("bitrate","Bitrate"))
		sourcelist.append(("bpm","BPM"))
		sourcelist.append(("comment","Comment"))
		sourcelist.append(("devicename","Device Name"))
		sourcelist.append(("filedesc","File Description"))
		sourcelist.append(("format","Format"))
		sourcelist.append(("genre","Genre"))
		sourcelist.append(("modified","Date Modified"))
		sourcelist.append(("name","Title"))
		sourcelist.append(("podcast","Podcast (T/F)"))
		sourcelist.append(("samplerate","Sample Rate"))
		sourcelist.append(("trackcount","Track Count"))
		sourcelist.append(("tracknumber","Track Number"))
		sourcelist.append(("useragent","User Agent"))
		sourcelist.append(("year","Year"))				
		return sourcelist
		
	def genVarMdList(self, filter, valuesDict, typeID, targetID):
		sourcelist = []
		sourcelist.append(("none","None (Leave Blank)"))
		for var in indigo.variables:
			sourcelist.append((var.id, var.name))
		return sourcelist
	
	def genVariTunesList(self, filter, valuesDict, typeID, targetID):
		sourcelist = []
		sourcelist.append(("none","None (Leave Blank)"))
		sourcelist.append(("iTLC","iTunes Local Control"))
		for dev in indigo.devices:
			if dev.model == "iTunes Server":
				sourcelist.append((dev.id, dev.name))
		return sourcelist
	
	def validateDeviceConfigUi(self, valuesDict, typeId, devId):
		# Validate that appropriate selections were made in device creation / modification dialogs.
		# Ensure that Zone is not already used
		errorsDict = indigo.Dict()
		self.logger.debug(u"Validating Device")
		self.logger.debug(u"Type ID: " + typeId)
		
		if typeId == "zone":
			self.logger.debug(u"Zone Selected: " + valuesDict["zoneselect"])
			if valuesDict["zoneselect"] in self.zonedev:
				if self.zonedev[valuesDict["zoneselect"]].id == devId:
					self.logger.debug(u"Zone Available")
				else:
					errorsDict["zoneselect"] = "Zone Already Assigned to Device"
					
		if typeId == "source":
			self.logger.debug(u"Source Selected: " + valuesDict["inputselect"])
			if valuesDict["inputselect"] in self.inputdev:
				if self.inputdev[valuesDict["inputselect"]].id == devId:
					self.logger.debug(u"Input Available")
				else:
					errorsDict["inputselect"] = "Input Already Assigned to Device"

				if valuesDict["supplyMd"] == True:
					if self.inputnuvonet[valuesDict["inputselect"]] == True:
						errorsDict["supplyMd"] = "Source is set up as a NuVo Net source. Cannot supply metadata to this type of source."
					if valuesDict["metadataSourceType"] == "shairport":
						spdeviceid = valuesDict["spDevice"]
						if spdeviceid in self.spDir:
							if self.spDir[spdeviceid] != valuesDict["inputselect"]:
								errorsDict["spDevice"] = "Shairport Device already in use by another source"
						try:
							clearsecint = int(valuesDict["clearsec"]) * 60
							if clearsecint < 0:
								errorsDict["clearsec"] = "Time to Clear Data must be a number greater than zero"
						except:
							errorsDict["clearsec"] = "Time to Clear Data must be a number greater than zero"
													
		if len(errorsDict) > 0:
			return (False, valuesDict, errorsDict)
		else:
			return (True, valuesDict)

	######################################################################################
	# Indigo Device Start/Stop
	######################################################################################
	def deviceStartComm(self, dev):
		self.logger.debug(u"deviceStartComm called")
		if dev.model == "Input Source":		
			if 'onOffStates' not in dev.states:
				dev.stateListOrDisplayStateIdChanged()
				dev.updateStateOnServer(key=u'onOffState', value=True)
		
			if dev.pluginProps["supplyMd"] == True:
				if dev.pluginProps["metadataSourceType"] == "shairport":
					self.spDir[dev.pluginProps["spDevice"]] = dev.pluginProps["inputselect"]
					self.inputremote[dev.pluginProps["inputselect"]] = {}
				elif dev.pluginProps["metadataSourceType"] == "variables":
					for v in range(1, 5):
						vLine = "vLine" + str(v)
						vid = dev.pluginProps[vLine]
						if vid != "none":
							self.varDir[vid] = dev.pluginProps["inputselect"]
					vid = dev.pluginProps["vDur"]
					if vid != "none":
						self.varDir[vid] = dev.pluginProps["inputselect"]
					vid = dev.pluginProps["vPos"]
					if vid != "none":
						self.varDir[vid] = dev.pluginProps["inputselect"]
# 					vid = dev.pluginProps["vRem"]  # We do not need to monitor vRem variable since plugin calculates this value
# 					if vid != "none":
# 						self.varDir[vid] = dev.pluginProps["inputselect"]
					vid = dev.pluginProps["vStat"]
					if vid != "none":
						self.varDir[vid] = dev.pluginProps["inputselect"]
			self.inputdev[dev.pluginProps["inputselect"]] = dev
			self.inputlastst[dev.pluginProps["inputselect"]] = 0
			self.logger.debug(u"Just added: " + dev.pluginProps["inputselect"] + u" to inputdev")
			self.logger.debug(u"Calling Status: " + dev.pluginProps["inputselect"] + u"DISPINFO?")
			self.commQueue.append(dev.pluginProps["inputselect"] + "DISPINFO?")
			self.logger.debug(u"Calling Status: " + dev.pluginProps["inputselect"] + u"DISPLINE?")
			self.commQueue.append(dev.pluginProps["inputselect"] + "DISPLINE?")

		else:
			self.zonedev[dev.pluginProps["zoneselect"]] = dev
			self.logger.debug(u"Just added: " + dev.pluginProps["zoneselect"] + u" to zonedev")
			self.logger.debug(u"Calling Status: " + dev.pluginProps["zoneselect"] + u"STATUS?")
			self.commQueue.append(dev.pluginProps["zoneselect"] + "STATUS?")
		
	def deviceStopComm(self, dev):
		if dev.model == "Input Source":
			del self.inputdev[dev.pluginProps["inputselect"]]
			del self.inputlastst[dev.pluginProps["inputselect"]]
			if dev.pluginProps["supplyMd"] == True:
				if dev.pluginProps["metadataSourceType"] == "shairport":
					del self.spDir[dev.pluginProps["spDevice"]]
					del self.inputremote[dev.pluginProps["inputselect"]]
				elif dev.pluginProps["metadataSourceType"] == "variables":
					for v in range(1, 5):
						vLine = "vLine" + str(v)
						vid = dev.pluginProps[vLine]
						if vid in self.varDir:
							del self.varDir[vid]
					vid = dev.pluginProps["vDur"]
					if vid in self.varDir:
						del self.varDir[vid]
					vid = dev.pluginProps["vPos"]
					if vid in self.varDir:
						del self.varDir[vid]
					vid = dev.pluginProps["vRem"]
					if vid in self.varDir:
						del self.varDir[vid]
					vid = dev.pluginProps["vStat"]
					if vid in self.varDir:
						del self.varDir[vid]
			self.logger.debug(u"Just deleted: " + dev.pluginProps["inputselect"] + u" from inputdev")
		else:
			del self.zonedev[dev.pluginProps["zoneselect"]]
			self.logger.debug(u"Just deleted: " + dev.pluginProps["zoneselect"] + u" from zonedev")
		
	######################################################################################
	# Indigo Pref UI Methods
	######################################################################################
	def validatePrefsConfigUi(self, valuesDict):
		
		errorsDict = indigo.Dict()		
		self.logger.debug(u"Validating Serial Port")
		self.validateSerialPortUi(valuesDict, errorsDict, u"serialport")
				
		if len(errorsDict) > 0:
			return (False, valuesDict, errorsDict)
		return (True, valuesDict)

		
	def closedPrefsConfigUi(self, valuesDict, userCancelled):
		# Basically, when the Config box closes, we want another chance to open the serial port.
		# Since that's all the startup method does, just call it from here.
		
		self.logger.debug(u"closedPrefsConfigUI called")
		# Tell our logging class to reread the config for logging level changes
		self.logLevel = int(self.pluginPrefs[u"logLevel"])  #new routine
		self.indigo_log_handler.setLevel(self.logLevel)  #new routine
		#self.logger.info(u"Log Levels are set to \"{}\".".format(valuesDict['logLevel']))
		self.logger.debug(u"Log Levels are set to \"{}\".".format(kLogLevelList[int(self.logLevel/10)]))

		# Setting log level of private plugin log handler to only log threaddebug if this is the setting in logging preferences
		if valuesDict['logLevel'] == "5":
			self.plugin_file_handler.setLevel(logging.THREADDEBUG)
			self.logger.debug(u"Private Log Handler set to THREADDEBUG")
		else:
			self.plugin_file_handler.setLevel(logging.DEBUG)
			self.logger.debug(u"Private Log Handler set to DEBUG")

		#Obviously, if the box closes by cancelling, then do nothing.
		if userCancelled:
			pass
		else:
			self.conn = None
			self.startup()
		
	######################################################################################
	# Concurrent Thread
	######################################################################################
	def runConcurrentThread(self):
		## This is what runs as the plugin is simply 'running'. 
		## Basically, if a command comes in from the serial device, you read it, parse it and hand it off to
		## whatever device/or variable needs to have its state updated.
		## In the meantime, you have a queue set up which gets loaded with commands from devices which must be fed
		## to the serial interface to be enacted.
		sleeptime = 0.1
		lastupdate = round(time.time(),0)
		try:
			while True:
				if self.portEnabled:
					#self.logger.threaddebug(u"Nuvo Loop Running")
					sleeptime = 0.1
					fromgrandconcerto = 0
					fromgrandconcerto = self.conn.readline()
					if self.PY3:
						fromgrandconcerto = fromgrandconcerto.decode('latin-1')  # properly decodes 0-255 ASCII characters for compatibility with Python
					else:
						fromgrandconcerto = fromgrandconcerto.decode('latin-1').encode('utf-8') # properly decodes 0-255 ASCII characters for compatibility with Python
					
					if len(fromgrandconcerto) > 3:
						fromgrandconcerto = fromgrandconcerto[:-2]  # Removes last two characters (CR and LF)
						sleeptime = 0.001
						if self.PY3:
							self.logger.threaddebug(u"Nuvo loop running: " + fromgrandconcerto)
						else:
							self.logger.threaddebug(u"Nuvo loop running: " + fromgrandconcerto.decode('utf-8'))
						self.parseToServer(fromgrandconcerto)
					if len(self.commQueue) > 0:
						sleeptime = 0.001
						# Sleep is set slow to keep processor use down, but putting 18 commands through with
						# 0.1 sleeptime takes almost 2 seconds, so if there's commands in the queue, drop the sleeptime, and
						# bang them through really fast. Then reset at beginning of loop.
						self.logger.threaddebug("commQueue: " + self.commQueue[0])
						if self.PY3:
							sendcount = self.conn.write(("*" + self.commQueue.pop(0) + "\r").encode("latin-1"))  #properly encodes 0-255 ASCII characters for compatibility with Nuvo display
						else:
							sendcount = self.conn.write("*" + self.commQueue.pop(0) + "\r")
						
					curstamp = round(time.time(),0)
					if curstamp > lastupdate:
						self.refreshTrackTimes()
						lastupdate = round(time.time(),0)
					for inputcode in self.inputlastst:
						if self.inputdev[inputcode].states['mData3'] == self.inputname[inputcode]:
							pass
						else:
							lasttime = self.inputlastst[inputcode]
							clearsec = int(self.inputdev[inputcode].pluginProps["clearsec"]) * 60
							if lasttime == 0:
								pass
							elif curstamp-lasttime > clearsec:
								if self.inputnuvonet[inputcode] == False:  #do not reset metadata display for Nuvonet sources (won't work anyway)
									self.logger.debug(inputcode + u" is not a Nuvo Net Source and we will reset metadata")
									self.resetSourceMetaData(inputcode)
								self.inputlastst[inputcode] = 0
								sleeptime = 0.001
							
				self.sleep(sleeptime)
		except self.StopThread:
			pass	
		
	def stopConcurrentThread(self):
		self.stopThread = True
		
	def menuGetSources(self, filter, valuesDict, typeID, devID):
		sourcelist = []
		for inputcode, inputname in six.iteritems(self.inputname):
			if inputcode in self.inputdev:
				inputname = self.inputdev[inputcode].name
			longinputcode = inputcode.replace("S","SRC")
			sourcelist.append((longinputcode,inputname))
		sourcelist.sort()			
		return sourcelist
		
	def menuGetZones(self, filter, valuesDict, typeID, devID):
		zonelist = []
		for zonecode, servdev in six.iteritems(self.zonedev):
			zonelist.append((zonecode,servdev.name))
		return zonelist
		
	def menuGetZones2(self, filter, valuesDict, typeID, devID):
		zonelist = []
		for zonecode, servdev in six.iteritems(self.zonedev):
			zonelist.append((zonecode,servdev.name))
		zonelist.append(("Z0","* None *"))
		zonelist.sort()
		return zonelist
		
	def resetSourceMetaData(self, inputcode):
		self.logger.debug(u"Resetting Metadata on " + self.inputdev[inputcode].name)
		self.commQueue.append(inputcode + "DISPLINE1\"\"")
		self.commQueue.append(inputcode + "DISPLINE2\"\"")
		self.commQueue.append(inputcode + "DISPLINE3\"" + self.inputname[inputcode] + "\"")
		self.commQueue.append(inputcode + "DISPLINE4\"\"")
		self.commQueue.append(inputcode + "DISPINFO,0,0,0")
		
	def parseToServer(self, fromgc):
		# Somewhat Messy, but just has to test to see what kind of message it is, and then parse correctly.
		# All responses start with a '#', so start by stripping that.
		fromgc = fromgc[1:]
		#self.logger.debug(fromgc)
		# For purposes here, server responses fall into 4 main categories:
		# Zone statements start with a Z
		# Source statements start with an S
		# All Zones Off is simply ALLOFF
		# and then there are miscellaneous system commands we aren't interested in for now.
		if fromgc == "ALLOFF":
			for zonecode, servdev in six.iteritems(self.zonedev):
				self.logger.debug(u"All Zones OFF - " + zonecode + u" called")
				servdev.updateStateOnServer("onOffState", value=False)
				servdev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
		elif fromgc[0] == "Z":
			# Zone statements start with Z but can be one or two digits.
			# Some statements are comma-delimited, but others are not
			if "," in fromgc:
				# Some Zone statements are messy and complicated around config etc. 
				# The ones we're interested in are set up as a comma-delimited list.
				resplist = fromgc.split(",")
				#self.logger.debug("Nuvo raw response: " + (', '.join(resplist)))
				zonecode=resplist[0]
				if zonecode in self.zonedev:
					#If we're using this device we'll parse and process. If not, log and move on.
					self.logger.debug(zonecode + u" found in devices list")
					servdev = self.zonedev[zonecode]
					# On, off, source, volume type statements come in a zone delimited list. Zone actions, like button presses do not.
					#resplist = fromgc.split(",")
					if resplist[1] == "OFF":
						# Off statments are simple and only have two elements in the list. Zone and Off.
						servdev.updateStateOnServer("onOffState", value=False)
						servdev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
						self.logger.info(servdev.name + u" is OFF")
					elif resplist[1] == "ON":
						# Statements for active zones have a bunch of info. Pick it out and send to server. Easy!
						# But first, save the current zone parameters, so you can compare and only put changes into the Event log.
						# This prevents the log from filling full of on/off states and source changes every time you change the volume.
						savedstate = servdev.states["onOffState"]
						savedinput = servdev.states["Input"]
						savedvolume = servdev.states["Volume"]
						#servdev.updateStateOnServer("onOffState", value="on")
						#servdev.updateStateOnServer("Input", value = resplist[2])
						inputcode = resplist[2].replace("SRC","S")
						savedplaystate = self.inputdev[inputcode].states # saved play state when zone turns on
						savedplaystate = savedplaystate['status']
						if inputcode in self.inputdev:
							sname = self.inputdev[inputcode].name
						else:
							sname = self.inputname[inputcode]
						#self.logger.info(servdev.name + " source is " + sname + " and is " + savedplaystate)
						
						if resplist[3] == "MUTE":
							pass
						else:
							calcvol = 79 - int(resplist[3][-2:])
							servdev.updateStateOnServer("Volume", value=calcvol)
						if savedstate == False:
							self.logger.debug(u"Zone state was OFF")
							# if the zone is turning ON and WAS OFF, then report everything...
							# This is probably the only time you report the zone status as 'ON'
							servdev.updateStateOnServer("onOffState", value=True)
							servdev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
							servdev.updateStateOnServer("Input", value = resplist[2])
							self.logger.info(servdev.name + " is ON")
							self.logger.info(servdev.name + u" source is " + sname + u" and is " + savedplaystate)
							if resplist[3] == "MUTE":
								self.logger.info(servdev.name + u" is muted")
							else:
								self.logger.debug(u"Reported Volume is " + resplist[3])
								self.logger.info(servdev.name + u" volume is " + str(calcvol))
						else:
							# Now if the zone was already ON, test the parameters, if it's unchanged, don't log
							if self.pluginstartup == True:
								self.logger.info(servdev.name + u" is ON")
								self.pluginstartup = False
							if savedinput == resplist[2]:
								pass
							else:
								servdev.updateStateOnServer("Input", value = resplist[2])
								self.logger.info(servdev.name + u" source is " + sname + u" and is " + savedplaystate)
							if resplist[3] == "MUTE":
								calcvol = 0
							else:
								calcvol = 79 - int(resplist[3][-2:])
							if savedvolume == calcvol:
								self.logger.info(servdev.name + u": source " + sname + u", volume " + str(calcvol))
								pass
							else:
								if resplist[3] == "MUTE":
									self.logger.info(servdev.name + u" volume is muted")
								else:
									self.logger.info(servdev.name + u": source " + sname + u", volume " + str(calcvol))
						savedstate = None
						savedinput = None
						savedvolume = None

				else:
					#self.logger.warning(zonecode + u" is not yet assigned to a device")
					resplist = ', '.join(resplist)
					self.logger.info("Nuvo raw response: " + resplist) # catches a bunch of Nuvo responses

			else:
				# fromgc is not comma-delimited and has a source associated with
				# Important: Nuvonet source commands (NEXT, PREV, PLAYPAUSE, MACRO) are not received
				zonecode = fromgc[:3]
				zonecode = zonecode.replace("S", "")
				inputcode = fromgc[2:5]  # zone statements can be one or two digits which affects the position of the Source and Command
				if inputcode[0] == "S":
					inputcode = inputcode[0:2]
					command = fromgc[4:]
				else:
					inputcode = inputcode[1:3]
					command = fromgc[5:]
				if zonecode in self.zonedev:
					self.logger.debug(zonecode + u" found in devices list and we are sending a command")
					if "MACRO" in command:
						self.logger.warning("Macro " + command + " called from " + servdev.name + ". (Macros are not supported by Plugin)")
					elif self.inputnuvonet[inputcode] == False:  #only control non-Nuvonet sources
						servdev = self.inputdev[inputcode]
						if servdev.pluginProps["metadataSourceType"] == "shairport":
							self.commandFromZone(zonecode, inputcode, command)
						elif servdev.pluginProps["metadataSourceType"] == "variables":
							if servdev.pluginProps["iTunesServerID"] == "iTLC":
								self.commandFromZone3(zonecode, inputcode, command)
							else:
								self.commandFromZone2(zonecode, inputcode, command)
						self.logger.debug(u"zonecode: " + zonecode)
						self.logger.debug(u"inputcode: " + inputcode)
						self.logger.debug(u"command: " + command)
					else:
						self.logger.info(command + u" button pressed on " + self.zonedev[zonecode].name + u" keypad for iPod source.")
						# apparently this is not working for Nuvonet sources
				else:
					self.logger.warning(zonecode + u" is not yet assigned to a device.")

		elif fromgc[0] == "S":
			# Source statements start with S
			inputcode = fromgc[:2]
			# Some Source statements we care about if the Source is in use or not (device validation, etc.)
			if fromgc[2:8] == "ACTIVE":
				if int(fromgc[-1:]) == 1:
					self.inputnuvonet[inputcode] = True
					self.logger.debug(inputcode + " is a Nuvo Net Source")
				else:
					self.inputnuvonet[inputcode] = False
					self.logger.debug(inputcode + " is not a Nuvo Net Source")
			if fromgc[2:6] == "NAME":
				sysname = fromgc[6:].replace("\"","")
				self.inputname[inputcode] = sysname
				self.logger.debug(inputcode + " system Name is: " + sysname)
			# Statements relevant to active Sources.
			if inputcode in self.inputdev:
				servdev = self.inputdev[inputcode]
				if fromgc[2:10] == "DISPINFO":
					#statuslist = ("Normal","Idle","Playing","Paused","Fast Forward","Rewind","Play Shuffle","Play Repeat","Play Shuffle Repeat")
					resplist = fromgc.split(",")
					self.logger.threaddebug(resplist)
					dur = self.secToTime(float(resplist[1][3:]))
					pos = self.secToTime(float(resplist[2][3:]))
					rem = self.secToTime(float(resplist[1][3:])-float(resplist[2][3:]))
					statno = int(resplist[3][-1:])
					stat = statuslist[statno]
					
					# updates Indigo log with playstatus changes for all sources. Also done during startup. Playstatus changes for Nuvonet sources are not done anywhere else!
					if self.inputnuvonet[inputcode] == True or self.inputnuvonet[inputcode] == False:
						if self.statlast.get(inputcode) == stat:
							pass
						else:
							self.logger.info(servdev.name + " play status is " + stat)
							self.statlast[inputcode] = stat
							if stat in ["Playing","Play Shuffle","Play Repeat","Play Shuffle Repeat"]:
								servdev.updateStateImageOnServer(indigo.kStateImageSel.AvPlaying)
							elif stat == "Paused":
								servdev.updateStateImageOnServer(indigo.kStateImageSel.AvPaused)
							elif stat in ["Fast Forward","Rewind"]:
								servdev.updateStateImageOnServer(indigo.kStateImageSel.TimerOn)
							else:
								servdev.updateStateImageOnServer(indigo.kStateImageSel.AvStopped)
							servdev.updateStateOnServer('onOffState', value=True, uiValue=stat)
					
					if "Play" in stat:
						self.inputlastst[inputcode] = 0
					else:
						self.inputlastst[inputcode] = round(time.time(),0)
					if servdev.pluginProps["repTrackTime"] == True:
						self.logger.threaddebug(u"We are updating device state trackinfo")
						servdev.updateStateOnServer("tracklen", dur)
						servdev.updateStateOnServer("trackprog", pos)
						servdev.updateStateOnServer("trackrem", rem)
						servdev.updateStateOnServer("status", stat)
				elif fromgc[2:10] == "DISPLINE":
					if self.PY2:
						fromgc = fromgc.decode('utf-8')  #PY2 version
					resplist = fromgc.split(",")
					stateid = "mData" + resplist[0][-1:]
					if self.PY3:
						linedata = fromgc.split("\"")[1]
						self.logger.debug(servdev.name + " line " + resplist[0][-1:] + ": " + linedata)
					else:
						linedata = fromgc.split("\"")[1].encode('utf-8')  #PY2 version
						self.logger.debug(servdev.name + " line " + resplist[0][-1:] + ": " + linedata.decode('utf-8'))   #PY2 version
					
					servdev.updateStateOnServer(stateid, linedata)
			else:
				self.logger.debug(inputcode + " is not yet assigned to a device.")
				
	################################################################
	#### These are commands from a zone controlled by Shairport ####
	################################################################

	def commandFromZone(self, zonecode, inputcode, command):
		self.logger.info(command + u" button pressed on " + self.zonedev[zonecode].name + u" keypad.")
		clientip = self.inputremote[inputcode]['clientip']
		artoken = self.inputremote[inputcode]['artoken']
		dacpid = self.inputremote[inputcode]['dacpid']
		srcremport = self.inputremote[inputcode]['srcremport']
		
		dname = self.inputdev[inputcode].name
		
		if command == "PREV":
			action = "previtem"
		elif command == "NEXT":
			action = "nextitem"
		elif command == "PLAYPAUSE":
			action = "playpause"
		else:
			action = "none"
		
		if srcremport == "":
			self.logger.warning(u"DACP Remote Port not available for " + self.inputdev[inputcode].name)
		elif clientip == "":
			self.logger.warning(u"No client IP available for device streaming to " + self.inputdev[inputcode].name)
			self.logger.warning(u"Try disconnecting and reconnection client from Shairport Sync")
		else:
			self.logger.debug(dname + u" IP Address: " + clientip)
			self.logger.debug(dname + u" Port: " + srcremport)
			self.logger.debug(dname + u" DACP ID: " + dacpid)
			self.logger.debug(dname + u" Active Remote Token: " + artoken)
		
			# Get ipv4 address for any ipv6 addresses.
			if ":" in clientip:
				triple = socket.gethostbyaddr(clientip)
				clientip = socket.gethostbyname(triple[0])
		
			url = "http://" + clientip + ":" + srcremport +"/ctrl-int/1/"+action
			self.logger.debug(url)
			
			if action != "none":
				parameters = {'Active-Remote': artoken}
				req = requests.get(url,  headers = parameters)
				req = None
	
	######################################################################################################
	#### These are commands from a zone controlled by iTunes Music Server as source and iTunes plugin ####
	######################################################################################################

	def commandFromZone2(self, zonecode, inputcode, command):
		#self.logger.info(command + u" button pressed on " + self.zonedev[zonecode].name + u" keypad.")  #not necessary to log
		
		dname = self.inputdev[inputcode].name
		servdev = self.inputdev[inputcode]
		deviceId = servdev.pluginProps["iTunesServerID"]
		if not (deviceId == "none" or deviceId == "iTLC"):
			self.logger.debug(u"iTunesServer ID: " + deviceId)
			itunesPlugin = indigo.server.getPlugin("com.perceptiveautomation.indigoplugin.itunes")

			if itunesPlugin.isEnabled():
				if command == 'PREV':
					self.logger.debug(servdev.name + " send PREV")
					itunesPlugin.executeAction("prevTrack", int(deviceId))
				elif command == 'NEXT':
					self.logger.debug(servdev.name + " send NEXT")
					itunesPlugin.executeAction("nextTrack", int(deviceId))
				elif command == "PLAYPAUSE":
					self.logger.debug(self.zonedev[zonecode].name + " send PLAYPAUSE")
					itunesPlugin.executeAction("playPause", int(deviceId))
					action = "playpause"
				else:
					action = "none"
			else:
				self.logger.warning(u"The iTunes plugin needs to be enabled")
		
	
	#######################################################################################################
	#### These are commands from a zone controlled by iTunes as source and iTunes Local Control plugin ####
	#######################################################################################################

	def commandFromZone3(self, zonecode, inputcode, command):
		#self.logger.info(command + u" button pressed on " + self.zonedev[zonecode].name + u" keypad.")  #not  necessary to log
		
		dname = self.inputdev[inputcode].name
		servdev = self.inputdev[inputcode]
		deviceId = servdev.pluginProps["iTunesServerID"]
		if deviceId == "iTLC":
			self.logger.debug(u"iTunes is controlled by iTunes Local Control plugin")
			itunesPlugin = indigo.server.getPlugin("com.morris.itunes-local-control")
			
			if itunesPlugin.isEnabled():				
				if command == 'PREV':
					self.logger.debug(servdev.name + " send PREV")
					itunesPlugin.executeAction("prev")
				elif command == 'NEXT':
					self.logger.debug(servdev.name + " send NEXT")
					itunesPlugin.executeAction("next")
				elif command == "PLAYPAUSE":
					self.logger.debug(self.zonedev[zonecode].name + " send PLAYPAUSE")
					itunesPlugin.executeAction("playpause")
					action = "playpause"
				else:
					action = "none"
			else:
				self.logger.warning(u"The iTunes Local Control plugin needs to be enabled")


	def refreshTrackTimes(self):
		#Loop through all of the defined source devices, and if the user has elected to update the track time info AND
		#the source is actively playing. This command will request the track information for a source from Nuvo every second.
		#This whole routine is not  necessary for Nuvo keypads to display correct and counting track info 
		#but routine is required to update Indigo device state track info.
		for inputcode, dev in self.inputdev.items():
			if dev.pluginProps["repTrackTime"] == True:
				status = dev.states["status"]
				if "Play" in status:
					self.commQueue.append(inputcode + "DISPINFO?")
					self.logger.threaddebug(u"uRequesting " + inputcode + "DISPINFO?")
				else:
					pass
			else:
				pass

	def secToTime(self, secondtenths):
		seconds = int(secondtenths/10)
		hrs = divmod(seconds,3600)[0]
		mins = divmod(divmod(seconds,3600)[1],60)[0]
		secs = divmod(seconds,60)[1]
		
		if hrs == 0:
			tfh = ""
		else:
			tfh = str(hrs) + ":"
		
		if hrs == 0:
			tfm = str(mins) + ":"
		else:
			if mins < 10:
				tfm = "0" + str(mins) + ":"
			else:
				tfm = str(mins) + ":"
				
		if secs < 10:
			tfs = "0" + str(secs)
		else:
			tfs = str(secs)
				
		time = tfh + tfm + tfs
		return time

	def timeToSec(self, timeString):
		timeparts = timeString.split(":")
		if len(timeparts) == 2:
			seconds = (60 * int(timeparts[0])) + int(timeparts[1])
		elif len(timeparts) == 3:
			seconds = (3600 * int(timeparts[0])) + (60 * int(timeparts[1])) + int(timeparts[2])
		else:
			seconds = 0
		return seconds


	######################################################################################
	# Indigo Action Methods
	######################################################################################
	# these actions are for making device changes in the Indigo UI
	def actionControlDimmerRelay(self, action, dev):
		if action.deviceAction == indigo.kDeviceAction.TurnOn:
			self.logger.info(u"Turn ON " + dev.name)
			self.logger.debug(u"Turn On " + dev.pluginProps["zoneselect"])
			self.commQueue.append(dev.pluginProps["zoneselect"] + "ON")
		elif action.deviceAction == indigo.kDeviceAction.TurnOff:
			self.logger.info(u"Turn OFF " + dev.name)
			self.logger.debug(u"Turn Off " + dev.pluginProps["zoneselect"])
			self.commQueue.append(dev.pluginProps["zoneselect"] + "OFF")
		elif action.deviceAction == indigo.kDeviceAction.Toggle:
			self.logger.info(u"Toggle ON/OFF " + dev.name)
			self.logger.debug(u"Toggle " + dev.pluginProps["zoneselect"])
			self.commQueue.append(dev.pluginProps["zoneselect"] + "POWER")
	
	def validateActionConfigUi(self, valuesDict, typeId, devId):
		errorsDict = indigo.Dict()
		self.logger.debug(u"validating Action Config called")

		if typeId == u'setzonevolume':
			try:
				vol = int(valuesDict[u'reqvolume'])
				if vol >79 or vol <-79:
					errorsDict[u'reqvolume'] = "Enter a volume level between 0 and 79, or -79 and +79 for stepwise adjustment."
			except ValueError:
				errorsDict[u'reqvolume'] = "Invalid volume value. Enter a number between 0 and 79, or -79 and +79 for stepwise adjustment."
				
		if typeId == u'setallzonevolumes':
			try:
				for x in range(2, 6):
					reqvolume = "reqvolume" + str(x)
					vol = int(valuesDict[reqvolume])
					if vol >79 or vol <0:
						errorsDict[reqvolume] = "Enter a volume level between 0 and 79."
			except ValueError:
				errorsDict[reqvolume] = "Invalid volume value. Enter a number between 0 and 79."

		if typeId == u'setzonesource':
			try:
 				if "SRC" not in valuesDict[u'reqsource']:
 					raise ValueError
			except ValueError:
				errorsDict[u'reqsource'] = "Please select a Source."

		if typeId == u'setrawcmd':
			try:
				cmd = str(valuesDict[u'rawcmd'])
				# charsToMatch = ('*S', '*Z', '*VER', '*MUTE', '*MSG', '*ALLOFF', '*PAGE', '*CFG', '*G')
				# if not cmd.startswith(charsToMatch):
				#    errorsDict[u'rawcmd'] = "Invalid Nuvo command")
				if cmd[:1] != "*":
					errorsDict[u'rawcmd'] = "Nuvo command needs to start with '*'"					
			except ValueError:
				errorsDict[u'rawcmd'] = "Invalid Nuvo command"


		if len(errorsDict) > 0:
			return (False, valuesDict, errorsDict)
		return (True, valuesDict)

	def setzoneon(self, pluginAction, dev):

		self.logger.info(u"Turn ON " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "ON")
		
	def setzoneoff(self, pluginAction, dev):

		self.logger.info(u"Turn OFF " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "OFF")
		
	def setzonetoggle(self, pluginAction, dev):

		self.logger.info(u"Toggle ON/OFF " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "POWER")
		
	def setZoneVolume(self, pluginAction, dev):
		self.logger.debug(u"setZoneVolume called with arg: " + str(pluginAction.props.get(u"reqvolume")))
		# if '+' or '-' is specified before the volume setting, do not set it directly, rather increment it by that amount
		# so check for that first.
		if pluginAction.props.get(u"reqvolume")[:1] == "-":
			try:
				newVolume = 79 - (dev.states["Volume"] - int(pluginAction.props.get(u"reqvolume")[1:])) 
				self.logger.info(u"Decrease volume of " + dev.name + u" by " + str(pluginAction.props.get(u"reqvolume")[1:]))
			except ValueError:
				self.logger.warning(u"Invalid Volume Level: " + pluginAction.props.get(u"reqvolume"))
				return
		elif pluginAction.props.get(u"reqvolume")[:1] == "+":
			try:
				newVolume = 79 - (dev.states["Volume"] + int(pluginAction.props.get(u"reqvolume")[1:])) 
				self.logger.info(u"Increase volume of " + dev.name + u" by " + str(pluginAction.props.get(u"reqvolume")[1:]))
			except ValueError:
				self.logger.warning(u"Invalid Volume Level: " + pluginAction.props.get(u"reqvolume"))
				return
		else:
			self.logger.info(u"Set volume of " + dev.name + u" to " + str(pluginAction.props.get(u"reqvolume")))
			try:
				newVolume = 79 - int(pluginAction.props.get(u"reqvolume"))
			except ValueError:
				self.logger.warning(u"Invalid Volume Level: " + pluginAction.props.get(u"reqvolume"))
				return
		if not 0 <= newVolume <= 79:
			self.logger.warning(u"Invalid Volume Levels, will be corrected to 0 (min) or 79 (max).")
			if newVolume < 0:
				newVolume = 0
				#reqvolume = 79
			elif newVolume >79:
				newVolume = 79
				#reqvolume = 0

		#self.logger.debug(u"Setting Volume of " + dev.name + u" to " + str(pluginAction.props.get(u"reqvolume")))	
		self.logger.debug(u"Setting Volume of " + dev.name + u" to " + str(newVolume))	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "VOL" + str(newVolume))	
		
	def setallZoneVolumes(self, pluginAction, dev):
		###### this validation section is redundant and could be removed ######
		reqvoldir = {}
		for x in range(2, 6):
			reqvolume = "reqvolume" + str(x)
			try:
				newvolume = int(pluginAction.props.get(reqvolume))
			except ValueError:
				self.logger.warning(u"Invalid Volume Level: " + pluginAction.props.get(reqvolume))
				return				
			if newvolume <0:
				newvolume = "0"
				self.logger.warning(u"Invalid Volume Levels, will be corrected to 0 (max).")
			elif newvolume >79:
				newvolume = "79"
				self.logger.warning(u"Invalid Volume Levels, will be corrected to 79 (min).")
			else:
				newvolume = str(newvolume)
			reqvoldir["reqvolume{0}".format(x)] = newvolume  # a directory of string values with keys reqvolume2 to reqvolume5
		########################################################################

		newvolume = pluginAction.props.get(u"reqvolume6")
		if newvolume is True:
			reqvolume6 = "1"
		else:
			reqvolume6 = "0"
		self.logger.debug(u"setallZoneVolumes called with arg: " + reqvoldir['reqvolume2'] + " " + reqvoldir['reqvolume3'] + " " + reqvoldir['reqvolume4'] + " " + reqvoldir['reqvolume5'] + " " + reqvolume6)
		self.logger.info(dev.pluginProps["zoneselect"] + " " + dev.name + ": MAXVOL" + reqvoldir['reqvolume2'] + ", INIVOL" + reqvoldir['reqvolume3'] + ", PAGEVOL" + reqvoldir['reqvolume4'] + ", PARTYVOL" + reqvoldir['reqvolume5'] + ", VOLRST" + reqvolume6)
		self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "MAXVOL" + reqvoldir['reqvolume2'])
		self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "INIVOL" + reqvoldir['reqvolume3'])
		self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "PAGEVOL" + reqvoldir['reqvolume4'])
		self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "PARTYVOL" + reqvoldir['reqvolume5'])
		self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "VOLRST" + reqvolume6)
		#ZCFG1,MAXVOL0,INIVOL0,PAGEVOL0,PARTYVOL0,VOLRST0
		#use next few lines if above validation is not used
		#self.logger.debug(u"setallZoneVolumes called with arg: " + str(pluginAction.props.get(u"reqvolume2")) + " " + str(pluginAction.props.get(u"reqvolume3")) + " " + str(pluginAction.props.get(u"reqvolume4")) + " " + str(pluginAction.props.get(u"reqvolume5")) + " " + reqvolume6)
		#self.logger.info(dev.pluginProps["zoneselect"] + " " + dev.name + ": MAXVOL" + str(pluginAction.props.get(u"reqvolume2")) + ", INIVOL" + str(pluginAction.props.get(u"reqvolume3")) + ", PAGEVOL" + str(pluginAction.props.get(u"reqvolume4")) + ", PARTYVOL" + str(pluginAction.props.get(u"reqvolume5")) + ", VOLRST" + reqvolume6)
		#self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "MAXVOL" + str(pluginAction.props.get(u"reqvolume2")))
		#self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "INIVOL" + str(pluginAction.props.get(u"reqvolume3")))
		#self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "PAGEVOL" + str(pluginAction.props.get(u"reqvolume4")))
		#self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "PARTYVOL" + str(pluginAction.props.get(u"reqvolume5")))
		#self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "VOLRST" + reqvolume6)
		
	def reqallZoneVolumes(self, pluginAction, dev):
		self.logger.info(u"Requesting volume configurations for " + dev.name)
		self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "VOL?")

	def setvolumeup(self, pluginAction, dev):

		self.logger.debug(u"Turn UP Volume of " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "VOL+")
		
	def setvolumedown(self, pluginAction, dev):

		self.logger.debug(u"Turn DOWN Volume of " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "VOL-")
		
	def setvolumemuteon(self, pluginAction, dev):

		self.logger.debug(u"MUTE " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "MUTEON")
		
	def setvolumemuteoff(self, pluginAction, dev):

		self.logger.debug(u"UNMUTE " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "MUTEOFF")
		
	def setZoneSource(self, pluginAction, dev):
		## changes Source Name from SRC to and back
		inputcode = pluginAction.props.get(u"reqsource").replace("SRC","S")
		if inputcode in self.inputdev:
			sname = self.inputdev[inputcode].name
		else:
			sname = self.inputname[inputcode]
		self.logger.debug(u"Setting Source of " + dev.name + " to " + sname)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + pluginAction.props.get(u"reqsource"))
		
	def setPrev(self, pluginAction, dev):

		self.logger.info(u"Previous Track of " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "prev")
		
	def setNext(self, pluginAction, dev):

		self.logger.info(u"Next Track of " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "next")
		
	def setPlayPause(self, pluginAction, dev):

		self.logger.info(u"Play/Pause of " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "playpause")
		
	def setDNDOn(self, pluginAction, dev):

		self.logger.info(u"Turn ON DND of " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "dndon")
		
	def setDNDOff(self, pluginAction, dev):

		self.logger.info(u"Turn OFF DND of " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "dndoff")
		
	def reqZoneConfig(self, pluginAction, dev):

		self.logger.info(u"Request Configuration of Zone " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "STATUS?")
		
# 	def setDNDConfig(self, pluginAction, dev):
# 
# 		#bitmask (0x01=NoMute, 0x02=NoPage, 0x04=NoParty)
# 		ZCFG1DND0 - No selection
# 		ZCFG1DND1 - No Mute
# 		ZCFG1DND2 - No Page
# 		ZCFG1DND3 - No Mute, No Page
# 		ZCFG1DND4 - No Party
# 		ZCFG1DND5 - No Mute, No Party
# 		ZCFG1DND6 - No Page, No Party
# 		ZCFG1DND7 - No Mute, No Page, No Party

# 		DND Config reports back 0 if nothing is selected, and reports 1 if anything is selected.
# 		So there is something wrong with the API documentation.
# 		Therefore DND configuration cannot be set via the commandline.
# 		self.logger.info(u"Set DND Configuration of Zone " + dev.name)
# 		self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "DND" + "x")

	def setAllOff(self, pluginAction):
		self.commQueue.append("ALLOFF")

	def selectFavorite(self, pluginAction, dev):
		#This code is still active but the XML that calls it is commented out.
		#This code works just fine, but for some reason the GC does not respond to the command
		#as it should. It simply returns '#?'. If I can get it to work, just uncomment the XML and
		#the action becomes available again.
		self.logger.info(u"Setting Favorite of " + dev.name + u" to " + pluginAction.props.get(u"reqfav"))	
		self.commQueue.append(dev.pluginProps["zoneselect"] + "FAV" + pluginAction.props.get(u"reqfav"))

	def setZoneSlaveTo(self, pluginAction, dev):
		masterzone = pluginAction.props.get(u"slavetozone")
		if masterzone == "Z0":
			masterzonename = "None"
		else:
			masterzonename = self.zonedev[masterzone].name
		self.logger.info(u"Slave " + dev.name + " to zone " + masterzonename)	
		self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "SLAVETO" + masterzone[1:])
		#ZCFGzSLAVETOx
		
	def sendTextAlert(self, pluginAction):
		self.logger.debug(u"sendTextAlert called")
		mtype = pluginAction.props.get(u"msgtype")
		mdwell = pluginAction.props.get(u"msgdwell")
		message = pluginAction.props.get(u"messagetext")
		message = self.substitute(message)
		message = message.encode('latin-1', 'ignore')  # strips all ASCII >255 characters for compatibility with Nuvo
		message = message.decode('latin-1')   # converts byte object back to str object
		message = message.replace("\"","''")  # replaces troublesome double quotations

		self.logger.debug(message)
		for x in pluginAction.props.get(u"selectedzones"):
			self.logger.debug(u"Sending Message Command: " + x + u"MSG\"" + message + u"\"," + mtype + u"," + mdwell)
			self.commQueue.append(x + "MSG\"" + message + "\"," + mtype + "," + mdwell)
			
	def speakAnnouncement(self, pluginAction):
		self.logger.debug(u"speakAnnouncement called")
		# First, save current zone parameters
		self.logger.debug(u"Saving Zone Parameters")
		savedstate = {}
		savedinput = {}
		savedvolume = {}
		for zonecode in pluginAction.props.get(u"selectedzones"):
			dev = self.zonedev[zonecode]
			if dev.states["onOffState"] == True:
				savedstate[zonecode] = "ON"
			else:
				savedstate[zonecode] = "OFF"
			self.logger.debug(u"Saved State: "+ zonecode + ": " + str(savedstate[zonecode]))
			savedinput[zonecode] = dev.states["Input"]
			self.logger.debug(u"Saved Input: "+ zonecode + ": " + str(savedinput[zonecode]))
			savedvolume[zonecode] = dev.states["Volume"]
			self.logger.debug(u"Saved Volume: "+ zonecode + ": " + str(int(savedvolume[zonecode])))
				
		# Now, go through all of the zones and switch them to the right input.
		self.logger.debug(u"Setting zones to correct input")
		for zonecode in pluginAction.props.get(u"selectedzones"):
			self.commQueue.append(zonecode + pluginAction.props.get(u"annSource"))
			try:
				newVolume = 79 - int(pluginAction.props.get(u"annvolume"))
			except ValueError:
				self.logger.warning(u"Invalid Volume Level: " + pluginAction.props.get(u"annvolume"))
				return
			self.commQueue.append(zonecode + "VOL" + str(newVolume))
			self.commQueue.append(zonecode + "ON")

		# Make Announcement
		time.sleep(2)
		announcetext = pluginAction.props.get("announcement")
		self.logger.debug(u"Ann Text: " + announcetext)
		announcetext = self.substitute(announcetext)
		self.logger.debug(u"After Sub, Ann Text: " + announcetext)
		self.logger.debug(u"Speaking Now...")
		wait = not pluginAction.props.get(u"manualWait")
		waittime = 0
		if pluginAction.props.get(u"manualWait") == True:
			waittime = int(pluginAction.props.get(u"mantime"))
		indigo.server.speak(announcetext, waitUntilDone = True)
		time.sleep(waittime)
		if pluginAction.props.get(u"airplaydelay") == True:
			time.sleep(2)

		# And finally, reset original parameters
		self.logger.debug(u"Resetting Orig Zone Parameters")
		for zonecode in pluginAction.props.get(u"selectedzones"):
			self.commQueue.append(zonecode + savedstate[zonecode])
			self.commQueue.append(zonecode + savedinput[zonecode])
			origVolume = 79 - int(savedvolume[zonecode])
			self.commQueue.append(zonecode + "VOL" + str(origVolume))

	def pageOn(self, pluginAction):

		self.logger.info(u"Turning ON Page for all active zones.")
		self.commQueue.append("PAGE1")

	def pageOff(self, pluginAction):

		self.logger.info(u"Turning OFF Page for all active zones.")
		self.commQueue.append("PAGE0")

	def configTimeOn(self, pluginAction, dev):

		self.logger.info(u"Turn ON Time display " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "TIME1")

	def configTimeOff(self, pluginAction, dev):

		self.logger.info(u"Turn OFF Time display " + dev.name)	
		self.commQueue.append(dev.pluginProps["zoneselect"].replace("Z", "ZCFG") + "TIME0")

	def updateClock(self, pluginAction):

		self.logger.info(u"Updating the internal clock.")
		time = datetime.now().strftime("%Y,%m,%d,%H,%M")	
		self.commQueue.append("CFGTIME" + time)

	def setRawCmd(self, pluginAction):

		command = str(pluginAction.props.get("rawcmd"))
		command = command.encode('latin-1', 'ignore')  # byte object in Python 3, strips all ASCII >255 characters for compatibility with Nuvo
		command = command.decode('latin-1')   # conversion to str object
		self.logger.info(u"Sending a raw command to Nuvo: " + command)
		self.commQueue.append(command[1:])


