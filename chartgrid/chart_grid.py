#!/usr/bin/env python

## USAGE:
# copy this folder to /Applications/Inkscape.app/Contents/Resources/share/inkscape/extensions

from my_inkscape import *
import sys

import inkex
from inkex import Group, PathElement, units

class Extension(InkscapeExtension):
    def __init__(self, install_option=False):
        super().__init__(long_name="Create chart grid", script_menu="charting_extensions", install_option=install_option)

    def define_arguments(self):
        # add arguments here 
        # some exampes:
        self.arg_float  ("margin", default=12, min=0, max=50, gui_text="page margin in mm")
        self.arg_float  ("grid_m", default=25, min=1, max=1000, gui_text="grid length in real (m)")
        self.arg_float  ("ref_m", default=200, min=1, max=1000, gui_text="reference length real (meters)")
        self.arg_float  ("ref_mm", default=150, min=.1, max=1000, gui_text="reference length on map (mm)")

        self.arg_option ("scale_position", default='BL', options={'bottom left':'BL','bottom right':'BR','top left':'TL','top right':'TR'}, gui_text="position of the scale bar and compass", appearance="combo")
        self.arg_int    ("scale_Nbars", default=4, min=1, max=10, gui_text="number of scale bars")
        self.arg_float  ("scale_h", default=2.5, min=1, max=20, gui_text="height of the scale bar (mm)")
    
    def generate(self):
        # magic happens here
      
        #inkex.errormsg("sample text")
        
        group = Group.new("chart_grid")
        
        # DRAW GRID
        group_grid = Group.new("grid")
        
        viewport_width = inkex.units.convert_unit(self.svg.viewport_width, 'mm')
        viewport_height = inkex.units.convert_unit(self.svg.viewport_height, 'mm')
        
        margin = self.options.margin
        width  = viewport_width  -2*margin
        height = viewport_height -2*margin
        scale_h = self.options.scale_h

        #draw passe partout and border
        style_passpartout = 'opacity:1;fill:#ffffff;none' # white border around frame
        style_border = 'opacity:1;fill:none;stroke:#ff00ff;stroke-width:0.4;stroke-linecap:round;stroke-linejoin:round;stroke-miterlimit:4;stroke-dasharray:none;stroke-opacity:1' 
        draw_rect(group_grid, 0, 0, viewport_width, margin, style=style_passpartout)
        draw_rect(group_grid, 0, height+margin, viewport_width, margin, style=style_passpartout)
        draw_rect(group_grid, 0, margin, margin, height, style=style_passpartout)
        draw_rect(group_grid, margin+width, margin, margin, height, style=style_passpartout)
        draw_rect(group_grid, margin, margin, width, height, style=style_border)

        scale = self.options.ref_mm / self.options.ref_m   # scale in mm / m
        gridwidth = self.options.grid_m * scale
        
        Nx = int(width/gridwidth)
        Ny = int(height/gridwidth)
         
        #inkex.errormsg("svg.width={}\n svg.height={}\n margin={}\n width={}\n height={}\n scale={}\n gridwdith={}\n Nx={}\n Ny={}\n"
        #.format(self.svg.width, self.svg.height, margin, width, height, scale, gridwidth, Nx, Ny))
        
        #s="svg.width={}\n svg.height={}\n margin={}\n width={}\n height={}\n scale={}\n gridwdith={}\n Nx={}\n Ny={}\n".format(
        #    self.svg.width, self.svg.height, margin, width, height, scale, gridwidth, Nx, Ny)
        #draw_text(group, 0,0,s)
        
        style_grid  = 'opacity:1;fill:none;stroke:#ff00ff;stroke-width:0.1;stroke-linecap:round;stroke-linejoin:round;stroke-miterlimit:4;stroke-dasharray:1, 1.2;stroke-dashoffset:0;stroke-opacity:1'
        style_text  = 'font-family:sans-serif;fill:#ff00ff'
        text_size = 4
        textspc = 0.4  # small offset between border and text
    
        for ix in range(Nx+1):
            x = margin+(ix+1)*gridwidth
            if ix<Nx: 
                draw_line(group_grid, x, margin, x, margin+height, style=style_grid)
                lastx = x # store last line for scale bar
            
            xt = x-gridwidth/2
            if xt<(viewport_width-margin-3):
                #align will add the text: 'xy' : SME + TMB.
                draw_text(group_grid, xt, margin-textspc, str(ix+1), size=text_size, align='MB', style=style_text)
                draw_text(group_grid, xt, margin+height+textspc, str(ix+1), size=text_size, align='MT', style=style_text)

        for iy in range(Ny+1):
            y = viewport_height - margin - (iy+1)*gridwidth
            if iy<Ny:
                draw_line(group_grid, margin, y, margin+width, y, style=style_grid)
                lasty = y
            
            yt = y+gridwidth/2
            if yt>(margin+text_size):
                ytext = "" if iy<26 else chr(64+int(iy/26)) 
                ytext += chr(65+int(iy%26)) 
                draw_text(group_grid, margin-textspc, yt, ytext, size=text_size, align='EM', style=style_text)
                draw_text(group_grid, margin+width+textspc, yt, ytext, size=text_size, align='SM', style=style_text)
                
        for ix in range(Nx+1):
            xt = margin+ix*gridwidth
            xtext = str(ix+1)
            for iy in range(Ny+1):
                ytext = "" if iy<26 else chr(64+int(iy/26)) 
                ytext += chr(65+int(iy%26)) 
                txt =  ytext + xtext
                yt = viewport_height - margin - (iy+1)*gridwidth     
                if xt<(viewport_width-margin-3) and yt>(margin+text_size):
                    draw_text(group_grid, xt, yt, txt, size=2, align='ST', style=style_text)
                
        group.append(group_grid)
        
        # DRAW SCALE BAR
        Nbars = self.options.scale_Nbars
        scale_h = self.options.scale_h
        scale_w = Nbars * gridwidth  # scale represents 4 grid widths
        text_small = scale_h*0.75
        htotal_sb = scale_h + text_small + 0.1

        style_sb = 'opacity:1;fill:#000000;fill-opacity:1;stroke:#000000;stroke-width:0.25;stroke-linecap:round;stroke-linejoin:round;stroke-miterlimit:4;stroke-dasharray:none;stroke-opacity:1' 
        style_sw = 'opacity:1;fill:#ffffff;fill-opacity:1;stroke:#000000;stroke-width:0.25;stroke-linecap:round;stroke-linejoin:round;stroke-miterlimit:4;stroke-dasharray:none;stroke-opacity:1' 
        style_text  = 'font-family:sans-serif;fill:#000000'
        text_size = scale_h

        #align will add the text: 'xy' : SME + TMB.
        if self.options.scale_position[1]=='L':
            x_sb = margin
            align = 'S'
        else:
            x_sb = self.svg.width - margin - scale_w
            align = 'E'
            
        if self.options.scale_position[0]=='B':
            y_sb = viewport_height - margin - scale_h
            y_sb_text = -textspc
            align += 'B'
        else:
            y_sb = margin
            y_sb_text = scale_h+textspc
            align += 'T'
            
        group_sb = Group.new("scalebar", transform='translate({},{})'.format(x_sb, y_sb))

        for i in range(Nbars+1):
            x = gridwidth * i
            if i<Nbars: draw_rect(group_sb, x, 0, gridwidth, scale_h, style_sb if i%2 else style_sw)
            
            itext = i if self.options.scale_position[1]=='L' else Nbars-i
            sbtext = str(round(itext*gridwidth/scale,1)).rstrip('0').rstrip('.') + 'm'
            draw_text(group_sb, x, y_sb_text, sbtext, size=text_size, align=align, style=style_text)
        group.append(group_sb)

        return group

        
if __name__ == '__main__':
    if len(sys.argv)==2 and sys.argv[1]=="install":
        # install cmdline option will generate the inx file and copy the files to the inkscape folder
        ext = Extension(install_option=True)
        ext.build_inx()
        ext.copy_files_to_inkscape()
    else:  
        Extension().run()

#SVG 'add', 'add_unit', 'addnext', 'addprevious', 'ancestors', 'append', 'attrib', 'backlinks', 'base', 'clear', 'copy', 'cssselect', 'current_layer', 'defs', 'delete', 'desc', 'descendants', 'description', 'duplicate', 'eid', 'extend', 'fallback_style', 'find', 'findall', 'findone', 'findtext', 'get', 'getElement', 'getElementById', 'getElementByName', 'getElementsByClass', 'getElementsByHref', 'getElementsByStyleUrl', 'get_current_layer', 'get_first_selected', 'get_id', 'get_ids', 'get_or_create', 'get_page_bbox', 'get_selected', 'get_selected_bbox', 'get_selected_or_all', 'get_unique_id', 'get_viewbox', 'get_z_selected', 'getchildren', 'getiterator', 'getnext', 'getparent', 'getprevious', 'getroottree', 'height', 'href', 'ids', 'index', 'insert', 'is_sensitive', 'items', 'iter', 'iterancestors', 'iterchildren', 'iterdescendants', 'iterfind', 'itersiblings', 'itertext', 'keys', 'label', 'makeelement', 'metadata', 'name', 'namedview', 'new', 'nsmap', 'pop', 'prefix', 'remove', 'remove_all', 'replace', 'replace_with', 'root', 'scale', 'selected', 'selection', 'set', 'set_id', 'set_random_id', 'set_random_ids', 'set_selected', 'set_sensitive', 'sourceline', 'stylesheet', 'stylesheets', 'tag', 'tag_name', 'tail', 'text', 'title', 'tostring', 'typename', 'unit', 'unittouu', 'update', 'uutounit', 'values', 'view_center', 'width', 'wrapped_attrs', 'wrapped_props', 'xml_path', 'xpath']

#LAYER 'add', 'add_unit', 'addnext', 'addprevious', 'ancestors', 'append', 'attrib', 'backlinks', 'base', 'bounding_box', 'cascaded_style', 'clear', 'clip', 'composed_style', 'composed_transform', 'copy', 'cssselect', 'delete', 'desc', 'descendants', 'description', 'duplicate', 'effective_style', 'eid', 'extend', 'fallback_style', 'find', 'findall', 'findone', 'findtext', 'get', 'get_id', 'get_or_create', 'get_path', 'getchildren', 'getiterator', 'getnext', 'getparent', 'getprevious', 'getroottree', 'groupmode', 'href', 'index', 'insert', 'is_sensitive', 'is_visible', 'items', 'iter', 'iterancestors', 'iterchildren', 'iterdescendants', 'iterfind', 'itersiblings', 'itertext', 'keys', 'label', 'makeelement', 'new', 'nsmap', 'path', 'pop', 'prefix', 'remove', 'remove_all', 'replace', 'replace_with', 'root', 'set', 'set_id', 'set_path', 'set_random_id', 'set_random_ids', 'set_sensitive', 'shape_box', 'sourceline', 'tag', 'tag_name', 'tail', 'text', 'title', 'to_path_element', 'tostring', 'typename', 'unit', 'unittouu', 'update', 'uutounit', 'values', 'wrapped_attrs', 'wrapped_props', 'xml_path', 'xpath']