import wx

# LogTextCtrl is just a regular text control that eventually deletes some data so that
# the output doesn't grow without bounds
class LogTextCtrl(wx.TextCtrl):
    
    MAX_LOG_LEN = 10000   # Maximum number of characters allowed
    CULL_LEN = 2500 # Approximate number of characters to dischard when MAX_LOG_LEN exceeded
    
    def Log(self,data):
        self.AppendText(data)
        
        if (self.GetLastPosition() > self.MAX_LOG_LEN):
            xy = self.PositionToXY(self.CULL_LEN) # Figure out what (X,Y) position we're at CULL_LEN characters into the text
            cPos = self.XYToPosition(0,xy[1]+1) # Find character position of beginning of next line (might fail)
            if cPos >= 0: # Didn't fail
                self.Remove(0,cPos)
    
    def LogWarning(self,data):
        
        sp = self.GetLastPosition()
        self.AppendText("WARNING: ")
        ep = self.GetInsertionPoint()-1
        self.SetStyle(sp,ep,wx.TextAttr("YELLOW GREEN"))
        self.Log(data)
        
    def LogError(self,data):
        
        sp = self.GetLastPosition()
        self.AppendText("ERROR: ")
        ep = self.GetInsertionPoint()-1
        self.SetStyle(sp,ep,wx.TextAttr("RED"))
        self.Log(data)
        
        wx.Bell()
       


