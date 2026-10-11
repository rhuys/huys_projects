#!/usr/bin/env python


from my_inkscape import *
import sys

import inkex
from inkex import Group, PathElement

class Extension(InkscapeExtension):
    def __init__(self, install_option=False):
        super().__init__(long_name="Template inkscape extension", script_menu="Template submenu", install_option=install_option)

    def define_arguments(self):
        # add arguments here 
        # some exampes:
        self.arg_float  ("param_float", default=3, min=1, max=10, gui_text="enter a float")
        self.arg_int    ("param_int",   default=3, min=1, max=10, gui_text="enter an int")
        self.arg_bool   ("param_bool",  default=True, gui_text="enter a bool")
        self.arg_string ("param_str", default="xxx123", gui_text="type a string")       
        self.arg_option ("param_option", options={'a':1,'b':2,'c':3}, gui_text="select an option")

    def generate(self):
        # magic happens here
        
#         inkex.errormsg(repr(self.svg))
#         inkex.errormsg(self.svg.get('width'))
#         
#         # get docment width and height
#         inkex.errormsg('width:{}'.format(self.svg.width))
#         inkex.errormsg('height:{}'.format(self.svg.height))
#         
#         inkex.errormsg('current layer:'+self.svg.get_current_layer().label)
#         inkex.errormsg('layers:')
#         for layer in self.iter_layers(): 
#             inkex.errormsg('  ' + layer.label)

        group = Group.new("effect")
    
        x1 = 50; x2=100; x3=150
        y1 = 50; y2=100; y3=150
    
        draw_line(group, x1, y1, x3, y1)
        draw_line(group, x1, y2, x3, y2)
        draw_line(group, x1, y3, x3, y3)
        draw_line(group, x1, y1, x1, y3)
        draw_line(group, x2, y1, x2, y3)
        draw_line(group, x3, y1, x3, y3)
        
        size = 10
        draw_text(group, x1, y1, "align=ST 1\nsecond line", size=size, align="ST")
        draw_text(group, x1, y2, "align=MT 1\nsecond line", size=size, align="MT")
        draw_text(group, x1, y3, "align=ET 1\nsecond line", size=size, align="ET")
        draw_text(group, x2, y1, "align=SM 1\nsecond line", size=size, align="SM")
        draw_text(group, x2, y2, "align=MM 1\nsecond line", size=size, align="MM")
        draw_text(group, x2, y3, "align=EM 1\nsecond line", size=size, align="EM")
        draw_text(group, x3, y1, "align=SB 1\nsecond line", size=size, align="SB")
        draw_text(group, x3, y2, "align=MB 1\nsecond line", size=size, align="MB")
        draw_text(group, x3, y3, "align=EB 1\nsecond line", size=size, align="EB")
        
        
        
        #style1="font-variation-settings:normal;opacity:1;fill:none;fill-opacity:1;fill-rule:evenodd;stroke:#000000;stroke-width:0.25000001;stroke-linecap:butt;stroke-linejoin:miter;stroke-miterlimit:4;stroke-dasharray:0.75000002,0.25000001;stroke-dashoffset:0;stroke-opacity:1;stop-color:#000000;stop-opacity:1"

        style1 = 'fill:none;fill-opacity:1;stroke:#ff0000;stroke-opacity:1;stroke-width:0.2;stroke-linecap:butt;stroke-linejoin:miter;stroke-miterlimit:4;stroke-dasharray:none;-inkscape-stroke:none'
        new_node(group, "rect", x=0, y=0, width=self.options.param_float, height=self.options.param_float, style=style1)
        
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