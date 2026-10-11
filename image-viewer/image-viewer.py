#!/usr/bin/env python3

""" image-viewer.py

** https://github.com/rhuys/pyhuys.git - Created by Roeland Huys, 2026 **

simple window to view an image from Obsidian
You can choose a new image by copying the Obsidian path to the clipboard

simply copy an image link to and the viewer will show the image on 2 screens: a small viewer, and a large viewer on a second screen if available.
you can use following links:
- "copy path from systme root" like /Users/roeland/Documents/Roeland/RPG/werewolf/Attachments/Pasted image 20260307172333.png
- "obsidian link" like ![[Pasted image 20260126201639.png|300]]

keyboard controls: left/right to navigate images, up/down to rotate, space to clear image, esc to quit
Usage: image-viewer.py <image-folder-path>

Hint: move this to another screen and make it full-screen       

HOW TO USE WITH OBSIDIAN:

In obsidian, install following community plugin: "Shell commands"
Create a new shell command with following content:  
    zsh -l -c "python3 ~/Documents/Roeland/Programming/Python/small_projects/image-viewer.py {{vault_path}}/Attachments"

Bind it to a hotkey like F12.
Then, when you are in Obsidian, you can press the hotkey to launch the viewer for the current vault.
Later, you can copy an image link to the clipboard to view it.

"""

from dataclasses import dataclass
from json import tool
import wx # pip install wxpython
from pyhuys.gui.wx_tools import Rect, WxFrame
import pyperclip # 
import re
import sys
from pathlib import Path

class ImagePanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)

        self.wx_image = None     # will contain the original wx.Image 
        self.wx_bitmap = None    # will contain the bitmap to draw (scaled image)
        self.image_rect = None   # x, y, width, height

        self.text = ""

        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, self.on_resize)

    def on_resize(self, event):
        self.set_image()
        event.Skip()

    def set_image(self, wx_image = None):
        """update the image with the dimensions of the window"""
        self.wx_image = wx_image or self.wx_image

        # create the scaled bitmap
        client_width, client_height = self.GetClientSize()
        
        if self.wx_image and client_width > 0 and client_height > 0:
            self.image_rect = Rect(0,0, self.wx_image.GetWidth(), self.wx_image.GetHeight())
            self.image_rect.scale_to(client_width, client_height, keep_aspect=True, centered=True)

            scaled_image = self.wx_image.Scale(self.image_rect.w, self.image_rect.h, wx.IMAGE_QUALITY_HIGH)
            self.wx_bitmap = wx.Bitmap(scaled_image)
        else:
            self.wx_bitmap = None
        self.Refresh()

    def set_text(self, text):
        """do not show image, but show text instead"""
        self.text = text
        self.wx_image = None
        self.wx_bitmap = None
        self.Refresh()

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(wx.BLACK))
        dc.Clear()
        if self.wx_bitmap:
            dc.DrawBitmap(self.wx_bitmap, self.image_rect.x, self.image_rect.y, True)
        elif self.text:
            dc.SetTextForeground(wx.WHITE)
            dc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            rect = self.GetClientRect()
            dc.DrawLabel(self.text, rect, wx.ALIGN_CENTER)

class ViewerWindow(wx.Frame):
    def __init__(self, parent, title, **varargs):
        super().__init__( parent=None, title="", **varargs)
        self.parent = parent
        self.is_max_viewer = False

        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.image_panel = ImagePanel(self)
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.image_panel, 1, wx.EXPAND)
        self.SetSizer(self.sizer)
        
        self.Show()

    def on_close(self, event):
        # closing the viewer also closes the main window
        if self.parent:  
            self.parent.viewer_window = None
            self.parent.Close()
        self.Destroy()

    def max_viewer(self):
        # set "max_viewer" mode and maximize the viewer on the second screen if available
        if wx.Display.GetCount() >= 2:
            display = wx.Display(1)
        else:
            display = wx.Display(0)

        # set as max viewer
        self.is_max_viewer = True

        geometry = display.GetGeometry()

        self.ShowFullScreen(False)
        self.SetPosition((geometry.x+10, geometry.y+10))
        self.SetSize(geometry.width-20, geometry.height-20)   

        self.Show()
        self.Raise()
        # Let Cocoa settle, then fullscreen
        wx.CallLater( 200, lambda: self.ShowFullScreen(True, wx.FULLSCREEN_ALL) )

class MainWindow(ViewerWindow):
    def __init__(self, obsidian_image_path: Path):
        super().__init__(None, title="Main Viewer", style= wx.DEFAULT_FRAME_STYLE | wx.STAY_ON_TOP)

        self.obsidian_image_path = obsidian_image_path
        self.image_index = 0

        w = self.make_buttons()

        self.SetSize(w, 300)

        self.image_filenames = []  # list of image filenames
        self.images = []  # list of wx_image objects
        self.images_rotated = []  # list of rotation angles
        self.image_index = 0  # current index in the list

        self.timer = None
        self.init_clipboard_sniffer()
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.viewer_window = ViewerWindow(self, "Image Viewer", size=(600, 400), pos=(100,100), style= wx.NO_BORDER| wx.FRAME_NO_TASKBAR)

        self.no_image()
        self.Show()

    def on_close(self, event):
        # closing the main window also closes the viewer
        self.timer.Stop()
        if self.viewer_window: self.viewer_window.Destroy()
        self.Destroy()
        event.Skip()

    def init_clipboard_sniffer(self):
        pyperclip.copy("")  # clear clipboard to avoid loading at start
        self.prev_clipboard_text = ""
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        self.timer.StartOnce(200)

    def on_timer(self, event):
        """check the clipboard, if it contains a valid image from Obsidian, load it"""
        clipboard = pyperclip.paste()
        if clipboard: 
            clipboard_text = clipboard.strip()

            if clipboard_text != self.prev_clipboard_text:
                self.prev_clipboard_text = clipboard_text
                self.load_image(clipboard_text)

        self.timer.StartOnce(200)

    def load_image(self, clipboard_text):

        image_filename = None

        # first check if file exists
        if Path(clipboard_text).exists():
            image_filename = clipboard_text
        
        else:
            # check if the clipboard text contains an Obsidian image link, and extract the filename
            match = re.search(r'!\[\[([^|\]]+)', clipboard_text)
            if match:
                image_filename = self.obsidian_image_path / match.group(1)

        if not image_filename: 
            print("No valid image found in clipboard:", clipboard_text)
            return

        wx_image = wx.Image( str(image_filename), wx.BITMAP_TYPE_ANY)

        # if the image already exists in the list of images, remove the old one
        if image_filename in self.image_filenames:
            i = self.image_filenames.index(image_filename)
            del self.image_filenames[i]
            del self.images[i]

        # append the image to the end
        self.image_filenames.append(image_filename)
        self.images.append(wx_image)

        # set current image index to end
        self.image_index = len(self.image_filenames) - 1

        # Load and display the new image
        self.image_panel.set_image(self.images[-1])
        self.viewer_window.image_panel.set_image(self.images[-1])

        print("Loaded image:", image_filename)

    def select_image(self, image_index : int, rotate=False):
        """select another image in the list"""
        if self.image_filenames:

            image_index = min(max(image_index, 0), len(self.image_filenames) - 1)
            self.image_index = image_index

            wx_image = self.images[image_index]
            if rotate:
                wx_image = wx_image.Rotate90()
                self.images[image_index] = wx_image
            self.image_panel.set_image(wx_image)
            
            if self.viewer_window:
                self.viewer_window.image_panel.set_image(wx_image)
        else:
            self.no_image()

    def no_image(self):
        txt = "No image loaded.\nCopy an Obsidian image link to the clipboard.\nFolder: " + str(self.obsidian_image_path)
        self.image_panel.set_text(txt)
        if self.viewer_window:
            self.viewer_window.image_panel.set_text(txt)

    def max_viewer(self):
        if self.viewer_window: 
            self.viewer_window.max_viewer()

    def new_button(self, label, on_click = None, size=(40,30), tooltip=None, spacing_x=1, spacing_y = 2, **args):
        self.button_x += spacing_x
        btn = wx.Button(self.image_panel, label=label, pos=(self.button_x,spacing_y), size=size, **args)
        if on_click: btn.Bind(wx.EVT_BUTTON, on_click)
        if tooltip: btn.SetToolTip(tooltip)
        self.button_x += size[0]
        return btn
        
    def make_buttons(self):
        self.button_x = 5
        self.new_button("←", on_click=lambda evt: self.select_image(self.image_index - 1), tooltip="Previous image (key: ←)")
        self.new_button("→", on_click=lambda evt: self.select_image(self.image_index + 1), tooltip="Next image (key: →)")
        self.new_button("1st", on_click=lambda evt: self.select_image(0), tooltip="First image (key: Home)")
        self.new_button("Last", on_click=lambda evt: self.select_image(len(self.image_filenames) - 1), tooltip="Last image (key: End)")
        self.new_button("Rot", on_click=lambda evt: self.select_image(self.image_index, rotate=True), tooltip="Rotate image (key: Up)")
        self.new_button("X", on_click=lambda evt: self.no_image(), tooltip="Clear image (key: Space)")
        self.new_button("MAX", on_click=lambda evt: self.max_viewer(), tooltip="Move viewer to other screen and maximize (key: enter)")
        return self.button_x + 2
    
    def on_key(self, event):
        global obsidian_image_path
        keycode = event.GetKeyCode()

        if keycode == wx.WXK_LEFT:
            # Previous image
            self.select_image(self.image_index - 1)

        elif keycode == wx.WXK_RIGHT:
            # Next image
            self.select_image(self.image_index + 1)

        elif keycode == wx.WXK_HOME:
            # First image
            self.select_image(0)

        elif keycode == wx.WXK_END:
            # Last image
            self.select_image(len(self.image_filenames) - 1)

        elif keycode == wx.WXK_UP :
            # Last image
            self.select_image(0, rotated=True)

        elif keycode == wx.WXK_SPACE:
            # Show text instead of image
            self.no_image()

        elif keycode == wx.WXK_ESCAPE:
            self.Close()

        elif keycode == wx.WXK_RETURN or keycode == wx.WXK_NUMPAD_ENTER:
            self.max_viewer()

        else:
            event.Skip()

if __name__ == "__main__":
    obsidian_image_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    if not obsidian_image_path:
        print("image-viewer.py:  an image viewer for Obsidian")
        print("simply copy an Obsidian image link to the clipboard to view it here.")
        print("keyboard controls: left/right to navigate images, up/down to rotate, space to clear image, esc to quit")
        print("Usage: image-viewer.py <image-folder-path>")
        sys.exit(1)

    app = wx.App(False)
    frame = MainWindow(obsidian_image_path)
    app.MainLoop()