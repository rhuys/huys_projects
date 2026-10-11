"""
This library is written by Roeland Huys
It helps improving python scripting for making inkscape extensions easier
"""

inkscape_extensions_path = "/Applications/Inkscape.app/Contents/Resources/share/inkscape/extensions"

import sys
sys.path.append(inkscape_extensions_path)

import inkex
from inkex import Group, PathElement, Rectangle
import os
from lxml import etree
from shutil import copy
    
def new_node(parent, node_name, node_text="", attrib={}, **args):
    """wrapper for lxml.etree : improvement of etree.SubElement
    adds a new element to the parent with name, also adds text
    attrib is a dict of attributes
    args also carry attributes. underscores will be replaced by -
    """
    e = etree.Element(node_name)
    for a in attrib:
        e.set(a, str(attrib[a]))
    for key in args:
        if args[key] is not None:
            e.set(key.replace('_', '-'), str(args[key]))
    e.text = str(node_text)
    parent.append(e)
    return e

def draw_rect(parent, x, y, w, h, style='opacity:1;fill:none;stroke:#000000;stroke-width:0.5;stroke-opacity:1'):
    """Draw an SVG Rectangle"""
    return new_node(parent, "rect", x=x, y=y, width=w, height=h, style=style)

def draw_circle(parent, x, y, r, style='opacity:1;fill:none;stroke:#000000;stroke-width:0.5;stroke-opacity:1'):
    """Draw an SVG circle"""
    return new_node(parent, "circle", cx=x, cy=y, r=r, style=style)

def draw_line(parent, x1, y1, x2, y2, style='opacity:1;fill:none;stroke:#000000;stroke-width:0.5;stroke-opacity:1'):
    """Draw an SVG line"""
    # documentation: see https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/d#path_commands
    pathcmd = "M {},{} {},{}".format(x1, y1, x2, y2)
    return new_node(parent, "path", d=pathcmd, style=style)

def draw_path(parent, coords=[], close=True, style='opacity:1;fill:none;stroke:#000000;stroke-width:0.5;stroke-opacity:1'):
    """Draw an SVG line"""
    # documentation: see https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/d#path_commands
    pathcmd = 'M '
    for i in range(0, len(coords), 2):
        pathcmd += str(coords[i])+','+str(coords[i+1])+' '
    if close: pathcmd += 'Z'
    return new_node(parent, "path", d=pathcmd, style=style)


def draw_text(parent, x, y, text, size=4, line=0, align="", style="font-size:5;font-family:sans-serif;fill:#000000"):
    """Draw text on SVG
    size will add the font-size to the style
    line is the line height; default: size*1.2
    line will be the line height
    align will add the text: 'xy' : SME + TMB.
      first char: S (start), M(middle), E(end)
      second char: T (top), M(midde), B(bottom), nothing=baseline. will reposition y because there is a bug in inkscape; always baseline!
    """
    # documentation: https://developer.mozilla.org/en-US/docs/Web/SVG/Element/text
    style += ";font-size:{}".format(size)
    if line==0: line = size*1.2
    capheight = size*0.85   # distance between baseline and top of the text 
    descender = size*0.1  # distance between baseline and bottom of the text

    lines = str(text).splitlines()  # split multiline text in list
    
    # 'start' anchor is default
    a = align[0].lower() if len(align)>=1 else 's'
    text_anchor = 'start' if a=='s' else 'middle' if a=='m' else 'end' if a=='e' else ''

    # 'haning' baseline is default
    a = align[1].lower() if len(align)>=2 else 'h'
    if a=='t':  # hanging: shift down by capheight
        yoffset = capheight
    elif a=='m': # middle: first move down like hanging, then move up by half the size of the text box
         yoffset = capheight-line*(len(lines))/2 
    elif a=='b': # bottom: shift up by N-1 lines and descender
         yoffset = -(len(lines)-1)*line -descender
    else:   # default: baseline
        yoffset = -(len(lines)-1)*line

    
    textnode = new_node(parent, "text", x=x, y=y+yoffset, text_anchor=text_anchor, style=style)
    dy = 0 # first dy is 0
    for l in lines:
        new_node(textnode, 'tspan', l, alignment_baseline='hanging', x=x, dy=dy)
        dy = line # afterwards repeat dy to put text on next line
    return textnode

class InkscapeExtension(inkex.GenerateExtension):
    """extension of the inkex extension, adding more automation and functionality"""
    def __init__(self, long_name, script_menu, install_option=False):
        self.inx_root  = None   # root of xml when building the .inx file , when the "install" option is given
        self.pars = None  # used for option parser in normal execution
        self.long_name = long_name 
        self.script_menu = script_menu
        self.script_filename = sys.argv[0] # caller python scrip name
        self.script_name = os.path.splitext(sys.argv[0])[0] # same, without .py

        if not install_option: super().__init__()

    def define_arguments(self):
        """Override this method to define arguments with the arg_... methods below"""

    def arg_float  (self, name, default=0, min=0, max=10, gui_text="generic float"):
        if self.pars:
            self.pars.add_argument("--"+name, type=float, default=default)
        elif self.inx_root is not None:
            new_node(self.inx_root, 'param', default, name=name, type='float', min=min, max=max, gui_text=gui_text)

    def arg_int (self, name, default=0, min=0, max=10, gui_text="generic integer"):
        if self.pars:
            self.pars.add_argument("--"+name, type=int, default=default)
        elif self.inx_root is not None:
            new_node(self.inx_root, 'param', default, name=name, type='int', min=min, max=max, gui_text=gui_text)
 
    def arg_bool  (self, name, default=False, gui_text="generic boolean"):
        if self.pars:
            self.pars.add_argument("--"+name, type=inkex.Boolean, default=default)
        elif self.inx_root is not None:
            new_node(self.inx_root, 'param', default, name=name, type='bool', gui_text=gui_text)

    def arg_string(self, name, default="type text here", gui_text="generic string"):
        if self.pars:
            self.pars.add_argument("--"+name, type=str, default=default)
        elif self.inx_root is not None:
            new_node(self.inx_root, 'param', default, name=name, type='string', gui_text=gui_text)

    def arg_option(self, name, default=1, options={'a':1,'b':2,'c':3}, gui_text="generic string", appearance="combo"):
        if self.pars:
            self.pars.add_argument("--"+name, default=default)
        elif self.inx_root is not None:
            e = new_node(self.inx_root, 'param', name=name, type='optiongroup', appearance=appearance, gui_text=gui_text)
            for option in options:
                new_node(e, 'option', option, translatable='no', value=options[option])

    def add_arguments(self, pars):
        """overridden from inkex.GenerateExtension to define the arguments"""
        self.pars = pars
        self.define_arguments()
                    
    def build_inx(self):
        """build the inx file"""
        
        # header        
        self.inx_root = etree.Element('inkscape-extension', xmlns="http://www.inkscape.org/namespace/inkscape/extension")
        etree.SubElement(self.inx_root, "name").text = self.script_name
        etree.SubElement(self.inx_root, "id").text = 'org.inkscape.'+self.script_menu+'.'+self.script_name

        # parse parameters
        self.define_arguments()

        # footer
        e = etree.SubElement(self.inx_root, "effect")
        e1 = etree.SubElement(e, "object-type")
        e1.text='all'
        e2 = etree.SubElement(e, "effects-menu")
        submenu_name = self.script_menu.replace('_', ' ')
        
       # print(f"submenu_name={submenu_name}")
        etree.SubElement(e2, "submenu", name=submenu_name)

        e = etree.SubElement(self.inx_root, "script")
        etree.SubElement(e, "command", location='inx', interpreter='python').text=self.script_filename
        
        # save the .inx file
        xml_str = etree.tostring(self.inx_root, pretty_print = True, xml_declaration=True, encoding="UTF-8")
        save_path_file = self.script_name + ".inx"
        with open(save_path_file, "wb") as f:
            f.write(xml_str)

    def copy_files_to_inkscape(self):
        """perform a copy operation of the .py and .inx files to the inkscape folder"""

        print(self.script_filename)
        dest_path = os.path.join(inkscape_extensions_path, self.script_menu)
    
        if not os.path.isdir(dest_path):
            os.makedirs(dest_path)
            print("New directory created:"+dest_path)
        
        print("copying files to:"+dest_path)
    
        copy(self.script_filename, dest_path)
        copy(self.script_name+".inx", dest_path)    
        copy("my_inkscape.py", dest_path)
        
    def iter_layers(self):
        """iterate through the document layers. usage:
        for layer in self.iter_layers(newdoc): print(layer.label)"""
        
        for node in self.svg.iterchildren():
            if isinstance(node, inkex.Layer) and node.label:
                yield node

