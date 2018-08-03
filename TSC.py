#!/usr/bin/env python
#----------------------------------------------------------------------------
# Name:         TSC.py
# Author:       Joel Koltner
# Created:      5/2010
# Copyright:    None
#----------------------------------------------------------------------------
# Author:       Rob King xxx
# Changed:      03/08/2018 ...
# Copyright:    None yyy
# Abstract:     V2.0
#               Ported from Python 2.x to 3.7.0 with corrected deprecated code
#               when errors/warnings were found.
#----------------------------------------------------------------------------
import wx            # pip install -U wxPython
import wx.lib.inspection
import wx.html
import serial        # pip install -U pySerial     
import threading     # pip install -U pyThreading
import time          # pip install -U pyTime

from TSC_wdr import *

TEK_XRES=552 # Screen resolution of scope, X dimension
TEK_YRES=704 # Ditto, Y


# Try to convert a string to an integer, returning a specified value if unsuccessful
def StrToInt(text="",badVal=0):
    try:
        i = int(text)
    except ValueError:
        i = 0
        
    return i
    
# Build a solid bitmap of a given size and color
# For color, pass in something that wx.Brush can use: Either a color name/tuple/etc. or a wx.Colour
def MakeSolidBmp(width=16, height=16, color='blue'):
#    bmp = wx.EmptyBitmap(width,height)
    bmp = wx.Bitmap(width,height)
    dc = wx.MemoryDC(bmp)
    dc.SetBackground(wx.Brush(color))
    dc.Clear()
    dc.SelectObject(wx.NullBitmap)
    return bmp

# WDR: classes

# Dancing dots
class DDots():
    
    def __init__(self, min=3, max=13, c='.'):
        self.min = min
        self.max = max
        self.c = c
        self.num = self.min
        
    def Dots(self):
        dots = self.c*self.num
        self.num += 1
        if self.num>self.max:
            self.num = self.min
        return dots
    
    def Reset(self):
        self.num = self.min
    

# Serial port interface
class SerIface(threading.Thread):
    
    def __init__(self, gui, port=""):
        threading.Thread.__init__(self)
        
        self.connected = False
        # Set up to "change to" initial port
        self.newPort = port # We'll switch over to this port if it's not the same as self.port
        self.newPortF = True # Flag set by GUI when self.newPort has been changed
        self.gui = gui
        self.ltc = gui.GetLogTextCtrl()
        
    # Update status label in GUI
    def SetStatus(self, text):
        wx.CallAfter(self.gui.SetSerStatus,text)
        
    # Thread begins here when started
    def run(self):
        
        self.state = self.OpenPort # F points to current function (state machine-like)
        self.lastState = None
        self.terminate = False # Exit thread when this becomes true
        
        #self.serI = serial.Serial(port=None, baudrate=9600, rtscts=1, timeout=0.25) # Defaults to 8-N-1
        self.serI = serial.Serial(port=None, baudrate=19200, rtscts=1, timeout=0.25) # Defaults to 8-N-1
        self.db = DataByter(self.serI)
        self.dd = DDots()
        
        delay = 0
        while not(self.terminate):
            if delay!=0:
                time.sleep(delay) # ...wait specified time before going to next state
            curState = self.state # Record current state...
            delay = self.state() # Invoke current state...
            self.lastState = curState # (...so that states can see where they came from)
            
        self.serI.close()
        return # Exit thread
    
    # Try to open or change specified serial port        
    def OpenPort(self):
        
        # Check if serial port has changed (GUI sets, we reset)
        if self.newPortF:
            self.newPortF = False;
            if self.newPort != self.serI.port:
                wx.CallAfter(self.ltc.Log,"Serial port set to '%s'\n" % self.newPort)
                try:
                    self.serI.port = self.newPort
                except serial.SerialException:
                    pass # Code below will catch the problem
            
        if self.serI.port=="" or self.serI.port==None:
            self.SetStatus("No serial port specified" + self.dd.Dots())
            return 0.5
        
        # Try to open serial port
        try:
            self.serI.open()
            
#        except serial.SerialException, err:
        except IOError as e:
            self.SetStatus("Unable to open specified port" + self.dd.Dots())
            return 0.5
        
        # Port opened successfully
        self.state = self.WaitForHeader
        return 0
    
    def WaitForHeader(self):

        # Check if serial port has changed (GUI sets, we reset)
        if self.newPortF and self.newPort != self.serI.port: # Only attempt re-open if actual port name has changed
                self.serI.close()
                self.state = self.OpenPort
                return 0
        self.newPortF = False
        
        # Check if this is the first time here
        if self.lastState != self.WaitForHeader: # Yep
            self.serI.flushInput()
            self.textLine = ""

        # Just wait around, collecting individual characters until we hit a line feed... at that point, check for
        # the scope's identifier, and if it looks OK, go with it

        self.SetStatus("Waiting for header" + self.dd.Dots())

        while self.serI.inWaiting() != 0:
            ch = self.serI.read(1)
            if ch == '\x0a':
                break
            self.textLine = ''.join([self.textLine,ch])
            if len(self.textLine) > 100: # Don't let line grow forever if we're just getting garbage
                self.textLine = self.textLine[:-20]
        else: # No more character waiting
            return 0.25 # Return quickly

        #if self.textLine.find("DIGITIZING SAMPLING OSCILLOSCOPE") < 0: # Garbage line
        if  not ((self.textLine.find("CSA803") == 0) or (self.textLine.find("DIGITIZING SAMPLING OSCILLOSCOPE") == 0)): # Garbage        
            self.textLine = ""
            return 0.25 # Return quickly

        # We're good to go!
        self.state = self.GetXRes
        return 0
    
    def GetXRes(self):
        
        # Everything should be on the up-and-up here, with the scope starting to spew data
        #self.xRes = StrToInt(self.serI.readline(size=20))
        self.xRes = StrToInt(self.serI.readline())       
        if self.xRes<1 or self.xRes>1000: # That's not right...
            self.state = self.WaitForHeader
            return 0
        
        self.state = self.GetYRes
        return 0
    
    def GetYRes(self):
        
        self.yRes = StrToInt(self.serI.readline(size=20))
        if self.yRes<1 or self.yRes>1000: # That's not right...
            self.state = self.WaitForHeader
            return 0

        if self.xRes!=552 or self.yRes!=704:
            wx.CallAfter(self.ltc.LogWarning,"Scope attempting to output %dx%d image -- only 552x704 currently supported.\n" % \
                (self.xRes,self.yRes) )
            self.state = self.WaitForHeader
            return 0
            
        self.state = self.GetNull
        return 0
        
    def GetNull(self):
        
        # After the header block, there's a null terminator before the actual data
        n = self.serI.read(1)
        if n != '\x00':
            self.state = self.WaitForHeader
            return 0
        
        self.state = self.WaitForData
        return 0 # Scope pauses for a brief moment after end of title block before startindata -- avoid serial timeout this way
    
    def WaitForData(self):
        # The scope pauses for around a second before beginning the actual data block, so this state just proves a longer
        # timeout that the standard 250ms timeout we've been using (which is too short)

        self.SetStatus("Header received, waiting for data...")
        retries = 20
        while retries>0:
            if self.serI.inWaiting() > 0:
                break
            time.sleep(.100)
            retries -= 1
        else:
            self.state = self.WaitForHeader
            return 0

        # The data comes next... tell the GUI it's time to start a new page
        wx.CallAfter(self.gui.NewPage)
        
        self.state = self.GetData
        return 0
        
    def GetData(self):
        
        pixLeft = totPix = self.xRes * self.yRes # Total pixels we'll acquire
        pixList = [] # List of typles with pixel descriptors
        self.db.Reset()
        
        self.SetStatus("Receiving data (0%)" + self.dd.Dots())
        wx.CallAfter(self.ltc.Log,"Beginning screen capture.\n")
        
        try: # Try to get all the pixels
            
            while pixLeft > 0:
                
                b1 = self.db.GetByte()
                pix0 = b1 & 0x07
                pix1 = (b1 >> 3) & 0x07
                rpt = (b1 >> 6)
                if rpt == 0: # Repeat count actually in next byte
                    rpt = self.db.GetByte()
                    if rpt == 0: # Not supposed to happen
                        wx.CallAfter(self.ltc.LogError,"Invalid data received; capture aborted.\n")
                        self.state = self.WaitForHeader
                        return 0
                    if rpt < 4: # Repeat count >255, LSB in next byte
                        rpt = (rpt << 8) + self.db.GetByte()
                
                pixList.append((pix0,pix1,rpt))
                pixLeft -= rpt*2
                
                if len(pixList) == 25 or pixLeft == 0: # Send a block over to the GUI
                    if self.terminate: # Good time to check if we should quit the thread
                        return 0
                    
                    pd = round(float(totPix-pixLeft)/float(totPix) * 100)
                    self.SetStatus("Receiving data (%d%%)" % pd + self.dd.Dots())
                    wx.CallAfter(self.gui.DrawPixPairs,pixList)
                    pixList = []
                
        except serial.SerialException: # Timed out (or perhaps port closed somehow)
            
            wx.CallAfter(self.ltc.LogError,"Timed out waiting for data; capture aborted.\n")
            self.state = self.WaitForHeader
            return 0

        wx.CallAfter(self.ltc.Log,"Screen capture finished.\n")
        self.state = self.WaitForHeader
        return 0
        

# DataByter is used while the serial interface is retrieving bitmap (pixel) data.  It buffers what's
# coming from the serial port in (hopefully) a semi-efficient manner and returns data one byte at a
# time.  When the GetByte() method is called, the assumption is that there *should* be a byte available,
# so if not a SerialException is thrown.
class DataByter():
    
    def __init__(self, serI):
        self.serI = serI

    def Reset(self):
        self.idx = 0
        self.buf = ""

    def GetByte(self):
        
        # return 0x47 # For performance testing
    
        # Trim off beginning of buffer, if it's getting a bit long
        if self.idx>=100:
            self.buf = self.buf[self.idx:]
            self.idx = 0
            
        # Don't bother making the spendy serial port call if already have something
        if len(self.buf) > self.idx:
            b = self.buf[self.idx]
            self.idx += 1
            return ord(b)
        
        # Get whatever's in the serial port, or hang for at least one character if it's empty
        btg = max(1,self.serI.inWaiting())
        self.buf = "".join([self.buf,self.serI.read(btg)])
        
        # By now there should be something there...
        if len(self.buf) > self.idx:
            b = self.buf[self.idx]
            self.idx += 1
            return ord(b)
            
        # Nothing available
        raise serial.SerialException
        
# Bring up the GUI
class GUI(wx.Frame):
    
    ID_PALETTE_BMBS = 9900 # Starting value for color palette bitmapped buttons
    ID_HELP_WIN = 9908 # ID for help window
    COLOR_SS = 16 # Size of (square) palette color swaths
    defaultPalette = [(0,0,0),(77,77,77),(140,140,140),(160,32,240),(255,255,200),(0,255,0),(0,255,255),(255,255,255)]
    defaultColors = [wx.Colour(*col) for col in defaultPalette] 
    
    def __init__(self, parent, id, title,
        pos = wx.DefaultPosition, size = wx.DefaultSize, style = wx.DEFAULT_FRAME_STYLE ):
        wx.Frame.__init__(self, parent, id, title, pos, size, style)
        self.panel = wx.Panel(self,-1) # Get a nicer background, etc.
        self.mdSzr = MainDlg(parent=self.panel, call_fit=False, set_sizer=True) # Insert main window
        self.sph = None # No serial interface yet
        self.ltc = self.GetLogTextCtrl()
        
        # Read back user preferences
        cfg = wx.Config.Get()
        self.GetSerPortCB().SetValue(cfg.Read("SerPort",""))
        self.palColors = []
        for i in range(0,8):
            keyName = "Col" + str(i)
            defCol = wx.Colour(*self.defaultPalette[i]).GetRGB()
            keyVal = cfg.ReadInt(keyName,defCol)
            c = wx.Colour()
            c.SetRGB(keyVal)
            self.palColors.append(c)
                
        ps = self.panel.paletteSizer
        for anID in range(0,8):
            bmp = MakeSolidBmp(self.COLOR_SS,self.COLOR_SS,self.palColors[anID])
            abb = wx.BitmapButton(self.panel,anID+self.ID_PALETTE_BMBS,bmp)
            #abb.SetToolTipString("Change color mapped to pixel value %d" % anID)
            abb.SetToolTip("Change color mapped to pixel value %d" % anID)
            ps.Add(abb)
            #ps.AddSpacer((10,10))
            ps.AddSpacer(10)
            self.Bind(wx.EVT_BUTTON,self.ChangePalette,source=abb)

        # Set up capture panel
        self.capWin = wx.Window(self.panel,-1,wx.DefaultPosition,(TEK_XRES,TEK_YRES),wx.NO_BORDER)
        #self.panel.capSizer.Add(item=self.capWin, flag=wx.ALL, border=10)
        self.panel.capSizer.Add(self.capWin, flag=wx.ALL, border=10)
        #self.capBmp = wx.EmptyBitmap(TEK_XRES,TEK_YRES)
        self.capBmp = wx.Bitmap(TEK_XRES,TEK_YRES)
        self.NewPage()
        
        # Tell main sizer to perform layer and then set minimum size of us (frame) to it            
        self.mdSzr.SetSizeHints(self) 

        # WDR: handler declarations for GUI
        #wx.EVT_BUTTON(self, ID_PAL_DEFAULTS, self.OnSetPalDefaults)
        #wxPyDeprecationWarning: Call to deprecated item __call__. Use :meth:`EvtHandler.Bind` instead.
        self.Bind(wx.EVT_BUTTON, self.OnSetPalDefaults,source=None,id=ID_PAL_DEFAULTS)
        
        #wx.EVT_BUTTON(self, ID_HELP_BUTTON, self.Help)
        self.Bind(wx.EVT_BUTTON, self.Help,source=None,id=ID_HELP_BUTTON)

        self.Bind(wx.EVT_IDLE,self.OnIdle)
        #wx.EVT_BUTTON(self, ID_CITC_BUTTON, self.OnCopyToClipboard)
        self.Bind(wx.EVT_BUTTON, self.OnCopyToClipboard,source=None,id=ID_CITC_BUTTON)
        
        self.capWin.Bind(wx.EVT_PAINT,self.OnPaintCapWin) # Note that catching self's own EVT_PAINT isn't quite right and doesn't work under Linux
        self.capWin.Bind(wx.EVT_ERASE_BACKGROUND,self.OnEraseCapWin)
        #self.Bind(wx.EVT_SIZE,self.OnSize) # Not needed now that EVT_PAINT goes to the right place!
        self.GetSerPortCB().Bind(wx.EVT_KILL_FOCUS,self.SerPortChange) # KILL_FOCUS isn't a command event, so need to bind to actual widget
        self.Bind(wx.EVT_COMBOBOX,self.SerPortChange,self.GetSerPortCB())
        self.Bind(wx.EVT_CLOSE,self.OnClose)
        
    def OnIdle(self,event):
        if self.needCapPaint:
            self.needCapPaint = False
            self.capWin.Refresh() # Will send paint event to window

    # We specifically don't want to erase the background, as doing so causes flickering
    def OnEraseCapWin(self,event):
        pass
    
    def OnPaintCapWin(self,event):
        dc = wx.BufferedPaintDC(self.capWin, self.capBmp) # Bitmap will be drawn when DC falls out of scope
        #event.Skip() # Make sure everything else gets re-painted too

    def OnClose(self,event):
        # Shut down the serial listener thread, if possible
        if self.sph != None:
            self.sph.terminate = True # Tell serial receiver thread to terminate
            i = 1
            while self.sph.isAlive() and i<=100: # Wait for thread to terminate
                i += 1
                time.sleep(0.025)
                
        # Save user preferences
        cfg = wx.Config.Get()
        cfg.Write("SerPort",self.GetSerPortCB().GetValue())
        for i in range(0,8):
            keyName = "Col" + str(i)
            keyVal = self.palColors[i].GetRGB()
            cfg.WriteInt(keyName,keyVal)
        
        self.Destroy() # Ta ta!
        
# Palette-related items

    def GetPaletteSizer(self):
        return self.panel.paletteSizer
    
    # Palette color entry clicked
    def ChangePalette(self, event):
        pIdx = event.GetId()-self.ID_PALETTE_BMBS
        newColor = wx.GetColourFromUser(None, self.palColors[pIdx])
        #if newColor.Ok() == False: # Dialog cancelled
        if newColor.IsOk() == False: # Dialog cancelled
            return # No
        
        self.ChangePal(pIdx,newColor)
        
    # Change palette color entry -- also attempts to update capture bitmap colors
    # id is 0-7, newColor is a wx.Colour
    def ChangePal(self,id,newColor):

        # Do nothing if color didn't actually change
        if newColor == self.palColors[id]: # Was color actually changed?
            return
        self.ltc.Log("Changing color for pixel value %d to %s\n" % (id, newColor.Get()))

        # Change color in bitmap (...hopefully it's unique!)
        #img = wx.ImageFromBitmap(self.capBmp)
        #wxPyDeprecationWarning: Call to deprecated item ImageFromBitmap. Use bitmap.ConvertToImage instead.
        img = wx.Bitmap.ConvertToImage(self.capBmp)
        
        #img.Replace(*(self.palColors[id].Get() + newColor.Get()))
        img.Replace(*(newColor.Get()),1,1)
        #self.capBmp = wx.BitmapFromImage(img)
        self.capBmp = wx.Bitmap(img)
        
        # Update button
        self.palColors[id] = newColor
        bmp = MakeSolidBmp(self.COLOR_SS, self.COLOR_SS, newColor)
        btn = self.FindWindowById(self.ID_PALETTE_BMBS+id)
        btn.SetBitmapLabel(bmp)
        
        self.needCapPaint = True # Idle will re-draw
        
    def OnSetPalDefaults(self, event):
        for i in range(0,8):
            self.ChangePal(i,self.defaultColors[i])

# Capture panel-releated items

    # Clear image and setup for beginning of a new page
    def NewPage(self):
        self.X = self.Y = 0
        
        cpDC = wx.ClientDC(self.capWin) # We'll be drawing into the capture window...
        dc = wx.BufferedDC(cpDC,self.capBmp) # ...buffer it to avoid flicker/auto-update when falls out of scope
        dc.SetBackground(wx.Brush(self.palColors[0]))
        dc.Clear()
        self.needCapPaint = False # This might be the first time it's actually created
        
    # Draw pixel pairs -- just interate through a list of tuples containing pix1, pix2, and repeat
    def DrawPixPairs(self,pixPairs):

        dc = wx.MemoryDC(self.capBmp)
        p = wx.Pen(colour=(0,0,0), width=1, style=wx.USER_DASH)
        p.SetCap(wx.CAP_BUTT) # Don't mess with the line ends!
        p.SetDashes([1,1]) # Render a pixel, skip a pixel, repeat

        for pp in pixPairs:
            
            (pix1, pix2, rpt) = pp
            numPix = 2*rpt # Total number of pixels we'll be plotting
            
            while numPix>0:
                pltl = min(numPix,TEK_XRES-self.X) # Pixels left this line
                numPix -= pltl
                
                p.SetColour(self.palColors[pix1])
                dc.SetPen(p)
                dc.DrawLine(self.X, self.Y, self.X+pltl, self.Y)
                p.SetColour(self.palColors[pix2])
                dc.SetPen(p)
                dc.DrawLine(self.X+1, self.Y, self.X+1+pltl, self.Y)
                
                self.X += pltl
                if self.X>=TEK_XRES:
                    self.X = 0
                    self.Y += 1
            
        dc.SelectObject(wx.NullBitmap)
        self.needCapPaint = True
        
    def OnCopyToClipboard(self,event):
        d = wx.BitmapDataObject(self.capBmp)
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(d)
            wx.TheClipboard.Flush()
            wx.TheClipboard.Close()
            self.ltc.Log("Image copied to cliboard.\n")
        else:
            self.ltc.LogError("Couldn't open clipboard!\n")
            
#  Serial port stuff
    def GetSerPortCB(self):
        return self.FindWindowById( ID_SERPORT_COMBO )

    def SetSerPortHandler(self,sph):
        self.sph = sph

    def SerPortChange(self, event):
        np = self.GetSerPortCB().GetValue()
        np = np.strip().rstrip() # Remove extraneous whitespace
        self.GetSerPortCB().SetValue(np)
        if self.sph != None:
            self.sph.newPort = np
            self.sph.newPortF = True
        event.Skip()

    def SetSerStatus(self, text):
        self.FindWindowById(ID_SERSTATUS).SetLabel(text)
        

###
       
    def Help(self, event):
        #wx.lib.inspection.InspectionTool().Show()

        helpWin = self.FindWindowById(self.ID_HELP_WIN)
        if helpWin is None:
            frm = wx.Frame(parent=self, id=self.ID_HELP_WIN, title="Help...", size=wx.Size(800,600))
            frm.SetIcon(wx.GetApp().GetAppIcon())
            htmlWin = wx.html.HtmlWindow(parent=frm)
            htmlWin.LoadPage("TSC Help.html")
            frm.Show()
        else:
            helpWin.Raise()

    # WDR: methods for GUI

    def GetLogTextCtrl(self):
        return self.FindWindowById( ID_LOG_TEXTCTRL )

    # WDR: handler implementations for GUI
    
        
#----------------------------------------------------------------------------

class App(wx.App):

    def __init__(self, redirect=True, filename=None):
        wx.App.__init__(self, redirect, filename) # Will call OnInit
    
    def OnInit(self):
        config = wx.Config(appName="Tek Screen Capture")
        wx.Config.Set(config)

        # Bring up the GUI
        self.mainFrame = GUI(parent=None, id=-1, title="Tektronix 1180x Screen Capture Utility")
        self.SetTopWindow(self.mainFrame)
        self.mainFrame.Show(True)
        
        ltc = self.mainFrame.GetLogTextCtrl()
        ltc.Log("Tektronix 1180x Screen Capture Utility\n")
        ltc.Log("By Joel Koltner, May, 2010\n\n")
        
        self.mainFrame.SetIcon(self.GetAppIcon())
        
        # Start the serial listener thread running
        self.seri = SerIface(self.mainFrame,self.mainFrame.GetSerPortCB().GetValue())
        self.seri.start()
        self.mainFrame.SetSerPortHandler(self.seri)
        
        return True

    def OnExit(self):
        #pass
        return 0
    
    def GetAppIcon(self):
        return wx.Icon("TSC Icon.xpm",wx.BITMAP_TYPE_XPM)
    
            
#----------------------------------------------------------------------------

if __name__ == "__main__":
    app = App(redirect=False)
    app.MainLoop()
    
