#!/usr/bin/env python3
"""SC3K Facade Generator v4 — separate module and anchored facade stages."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox
from PIL import Image, ImageTk, ImageColor
import json, random, colorsys, re, copy

ROOT=Path(__file__).resolve().parent
LIBRARY=ROOT/'library'; OUT=Path.home()/'Documents'/'SC3K Architecture Builder'/'Exports'; OUT.mkdir(parents=True,exist_ok=True)
SHEETS={
 'default wall 12x25.png':('wall',(12,25)),
 'rustication_2x5.png':('rustication',(2,5)),
 'cornice_2x5.png':('cornice',(2,5)),
 'foundation_2x5.png':('foundation',(2,5)),
}
LABELS={'glass':'Glass','frame':'Window frame','casing':'Window casing','sill':'Window sill','bracket':'Bracket','sandrik':'Pediment','cornice':'Cornice'}
ARCH_PALETTE=[('Ivory','#D8D0C2'),('Warm limestone','#C9BBA5'),('Sandstone','#C7B18D'),('Light ochre','#BDA477'),('Dusty rose','#B98F87'),('Terracotta','#A96850'),('Muted sage','#9CA58C'),('Grey green','#7F938A'),('Dusty blue','#8FA6B4'),('Slate blue','#667F91'),('Warm greige','#AAA39A'),('Warm grey','#8F8981'),('Cream','#E4DCCB'),('Grey lilac','#A59AA7')]

ORDER=('glass','frame','casing','sill','bracket','sandrik','cornice')
WINDOW_SIZES=('L','M','S','XS','XXS')
WINDOW_ASSETS={'frame':'frames','casing':'casing','sandrik':'padiment','sill':'sills'}

def split_sheet(path,cell):
 im=Image.open(path).convert('RGBA'); cw,ch=cell; result=[]
 for y in range(im.height//ch):
  for x in range(im.width//cw):
   crop=im.crop((x*cw,y*ch,(x+1)*cw,(y+1)*ch))
   if crop.getbbox(): result.append(crop)
 return result

def paired_sheet(path, cell, size=None):
 """A pair is (ISO, FRONT); preserve blank cells to avoid shifting pair IDs."""
 sheet=Image.open(path).convert('RGBA')
 cw,ch=cell
 if cw<=0 or ch<=0 or sheet.width%cw or sheet.height%ch:
  raise ValueError(f'{path.name}: sheet {sheet.size} is not divisible by cell {cell}')
 cells=[sheet.crop((x,y,x+cw,y+ch)) for y in range(0,sheet.height,ch) for x in range(0,sheet.width,cw)]
 if len(cells)%2:
  raise ValueError(f'{path.name}: expected ISO/FRONT pairs, got {len(cells)} cells')
 return [{'name':f'{path.stem} #{i//2+1}', 'image':cells[i],
          'front_image':cells[i+1], 'size':size, 'pair_index':i//2}
         for i in range(0,len(cells),2)]

def place_clipped(target, sprite, x, y):
 # Alpha-composite a sprite even when its pixel offset is negative or outside the module.
 left=max(0,x); top=max(0,y); right=min(target.width,x+sprite.width); bottom=min(target.height,y+sprite.height)
 if right<=left or bottom<=top: return
 crop=sprite.crop((left-x,top-y,right-x,bottom-y))
 target.alpha_composite(crop,(left,top))

def recolor_wall(source,color):
 im=source.convert('RGBA'); target=ImageColor.getrgb(color); px=im.load()
 for y in range(im.height):
  for x in range(im.width):
   r,g,b,a=px[x,y]
   if not a: continue
   lum=(.299*r+.587*g+.114*b)/255; f=.72+lum*.38
   px[x,y]=(max(0,min(255,int(target[0]*f))),max(0,min(255,int(target[1]*f))),max(0,min(255,int(target[2]*f))),a)
 return im

def tint_sprite(source, color, mode='shade', strength=100):
 # Non-destructive recolor: alpha is untouched, pixel edges remain crisp.
 im=source.convert('RGBA'); target=ImageColor.getrgb(color); px=im.load(); amount=max(0,min(100,int(strength)))/100
 tr,tg,tb=[v/255 for v in target]
 th,ts,tv=colorsys.rgb_to_hsv(tr,tg,tb)
 for y in range(im.height):
  for x in range(im.width):
   r,g,b,a=px[x,y]
   if a==0: continue
   rr,gg,bb=r/255,g/255,b/255
   if mode=='hue':
    h,ss,v=colorsys.rgb_to_hsv(rr,gg,bb)
    # Preserve the source's tonal structure while shifting its hue toward chosen color.
    nh=(h+th)%1 if ss>0.08 else th
    ns=max(ss,ts*0.72)
    nr,ng,nb=colorsys.hsv_to_rgb(nh,ns,v)
   else:
    lum=(0.299*r+0.587*g+0.114*b)/255
    # A gently curved luminance map retains hand-painted highlights and shadows.
    factor=0.40+lum*0.78
    nr,ng,nb=min(1,tr*factor),min(1,tg*factor),min(1,tb*factor)
   px[x,y]=(round(r*(1-amount)+nr*255*amount),round(g*(1-amount)+ng*255*amount),round(b*(1-amount)+nb*255*amount),a)
 return im

class App:
 def __init__(self,root):
  self.root=root; root.title('SC3K Architecture Builder 1.2'); root.geometry('1220x820'); root.minsize(960,650)
  self.assets={k:[] for k in ('wall',)+ORDER+('rustication','foundation')}; self.wall_color='#D8D0C2'; self.window_size=tk.StringVar(value='M')
  self.component_colors={c:None for c in ORDER}; self.component_modes={c:'shade' for c in ORDER}; self.component_strength={c:100 for c in ORDER}
  self.enabled={c:False for c in ORDER}; self.choice={c:None for c in ORDER}; self.offset={c:[0,0] for c in ORDER}
  self.front_offset={c:[0,0] for c in ORDER}; self.module_view=tk.StringVar(value='ISO')
  self.cols=tk.IntVar(value=5); self.floors=tk.IntVar(value=5)
  self.facade_width=tk.IntVar(value=48)
  self.floor_counts=[tk.IntVar(value=v) for v in (4,6,8,6)]
  self.distribution=tk.StringVar(value='Evenly spaced')
  self.side_margin=tk.IntVar(value=4); self.group_size=tk.IntVar(value=2); self.group_gap=tk.IntVar(value=6)
  # Anchors are pixel offsets between corresponding module origins.
  self.step_x=tk.IntVar(value=12); self.step_y=tk.IntVar(value=0)
  self.row_x=tk.IntVar(value=0); self.row_y=tk.IntVar(value=25)
  self.module=None; self.facade=None; self.facade_front=None; self.layers={}; self.photo=None; self.drag=None
  self.extra_wall_height=tk.IntVar(value=0)
  self.type_names=['Ground floor','Second floor','Middle floor','Top floor']
  self.active_type=0; self.independent_edit=tk.BooleanVar(value=False); self.type_states={}; self.type_modules={}
  self.rust_first=tk.BooleanVar(value=False); self.rust_second=tk.BooleanVar(value=False); self.rust_count=tk.IntVar(value=5)
  self.first_foundation=tk.BooleanVar(value=False); self.foundation_choice=None; self.foundation_color='#C9BBA5'
  self.foundation_color_enabled=tk.BooleanVar(value=True)
  self.foundation_x=tk.IntVar(value=0); self.foundation_y=tk.IntVar(value=0)
  self._build(); self.load_assets(); self._capture_type_state(); self.compose_module()
  from volume_editor import App as VolumeApp
  self.volume_app=VolumeApp(self.tab_volume,embedded=True)
  self.volume_sync_enabled=tk.BooleanVar(value=True)
  self.volume_apply_enabled=tk.BooleanVar(value=True)
  self.volume_filter=tk.StringVar(value='Pixels')
  self.volume_auto_filter=tk.BooleanVar(value=True)
  self.volume_app.rotation_callback=self._refresh_auto_filter
  self._build_volume_bridge()
  self.tabs.bind('<<NotebookTabChanged>>',self._on_tab_changed)
  self.facade_width.trace_add('write', self._facade_width_changed)
 def _build(self):
  top=ttk.Frame(self.root,padding=(10,8,10,0)); top.pack(fill='x')
  ttk.Label(top,text='SC3K ARCHITECTURE BUILDER 1.2',font=('TkDefaultFont',14,'bold')).pack(side='left')
  ttk.Label(top,text='  ISO + FRONT · lighting in Volume Editor').pack(side='left')
  self.tabs=ttk.Notebook(self.root); self.tabs.pack(fill='both',expand=True,padx=8,pady=8)
  self.tab_module=ttk.Frame(self.tabs); self.tab_facade=ttk.Frame(self.tabs); self.tab_volume=ttk.Frame(self.tabs)
  self.tabs.add(self.tab_module,text='1 · Facade module'); self.tabs.add(self.tab_facade,text='2 · Facade assembly'); self.tabs.add(self.tab_volume,text='3 · Building volume')
  self.build_module_tab(); self.build_facade_tab()
 def build_module_tab(self):
  # Scrollable left control panel: keeps lower buttons reachable on short screens.
  panel=ttk.Frame(self.tab_module,width=310); panel.pack(side='left',fill='y'); panel.pack_propagate(False)
  left_canvas=tk.Canvas(panel,highlightthickness=0,width=300)
  left_scroll=ttk.Scrollbar(panel,orient='vertical',command=left_canvas.yview)
  left_canvas.configure(yscrollcommand=left_scroll.set)
  left_scroll.pack(side='right',fill='y')
  left_canvas.pack(side='left',fill='both',expand=True)
  left=ttk.Frame(left_canvas,padding=8)
  left_window=left_canvas.create_window((0,0),window=left,anchor='nw')
  def _module_panel_configure(_event=None):
   left_canvas.configure(scrollregion=left_canvas.bbox('all'))
  def _module_canvas_configure(event):
   left_canvas.itemconfigure(left_window,width=event.width)
  left.bind('<Configure>',_module_panel_configure)
  left_canvas.bind('<Configure>',_module_canvas_configure)
  def _module_wheel(event):
   if getattr(event,'delta',0): left_canvas.yview_scroll(int(-event.delta/120) or (-1 if event.delta>0 else 1),'units')
   elif getattr(event,'num',None)==4: left_canvas.yview_scroll(-1,'units')
   elif getattr(event,'num',None)==5: left_canvas.yview_scroll(1,'units')
  left_canvas.bind_all('<MouseWheel>',_module_wheel,add='+')
  left_canvas.bind_all('<Button-4>',_module_wheel,add='+')
  left_canvas.bind_all('<Button-5>',_module_wheel,add='+')
  right=ttk.Frame(self.tab_module,padding=8); right.pack(side='right',fill='both',expand=True)
  ttk.Label(left,text='BUILD A WINDOW MODULE',font=('TkDefaultFont',11,'bold')).pack(anchor='w')
  ttk.Label(left,text='FLOOR TYPE').pack(anchor='w',pady=(7,2))
  self.type_selector=ttk.Combobox(left,state='readonly',values=self.type_names,width=25); self.type_selector.current(0); self.type_selector.pack(fill='x')
  self.type_selector.bind('<<ComboboxSelected>>',self.select_type)
  ttk.Checkbutton(left,text='Edit floor types separately',variable=self.independent_edit,command=self.toggle_independent).pack(anchor='w',pady=(3,5))
  ttk.Label(left,text='Unchecked: edit all four floor types. Checked: edit only the selected type.',wraplength=265).pack(anchor='w')
  ttk.Label(left,text='Wall colour palette').pack(anchor='w',pady=(8,3))
  self.wall_palette=tk.StringVar(value=ARCH_PALETTE[0][0])
  self.wall_palette_box=ttk.Combobox(left,state='readonly',textvariable=self.wall_palette,values=[name for name,col in ARCH_PALETTE])
  self.wall_palette_box.pack(fill='x'); self.wall_palette_box.bind('<<ComboboxSelected>>',self.pick_wall_preset)
  row=ttk.Frame(left); row.pack(fill='x',pady=3)
  ttk.Button(row,text='Open palette…',command=lambda:self.open_palette('wall')).pack(side='left',fill='x',expand=True)
  self.swatch=tk.Label(row,text=self.wall_color,bg=self.wall_color,relief='groove',width=10); self.swatch.pack(side='left',padx=(5,0),ipady=3)
  ttk.Label(left,text='Additional wall height (px)').pack(anchor='w',pady=(8,2))
  hr=ttk.Frame(left); hr.pack(fill='x')
  height_spin=ttk.Spinbox(hr,from_=-20,to=80,textvariable=self.extra_wall_height,width=7,command=self.compose_module)
  height_spin.pack(side='left')
  height_spin.bind('<Return>',lambda e:self.compose_module())
  height_spin.bind('<FocusOut>',lambda e:self.compose_module())
  ttk.Button(hr,text='Apply height',command=self.compose_module).pack(side='left',padx=5)
  ttk.Label(left,text='Positive values extend the wall; negative values shorten it. Decorations are not stretched.',wraplength=260).pack(anchor='w',pady=(2,4))
  ttk.Label(left,text='WINDOW SIZE').pack(anchor='w',pady=(8,2))
  self.window_size_box=ttk.Combobox(left,state='readonly',textvariable=self.window_size,values=['L','M','S','XS','XXS'],width=10)
  self.window_size_box.pack(fill='x'); self.window_size_box.bind('<<ComboboxSelected>>',self.change_window_size)
  ttk.Label(left,text='Glass size determines compatible decorations. XS/XXS may use S pediments and sills if unavailable.',wraplength=265).pack(anchor='w',pady=(2,4))
  ttk.Label(left,text='Enable components in order:').pack(anchor='w',pady=(8,4))
  self.check_vars={}
  for cat in ORDER:
   row=ttk.Frame(left); row.pack(fill='x',pady=2)
   var=tk.BooleanVar(value=False); self.check_vars[cat]=var
   ttk.Checkbutton(row,text=LABELS[cat],variable=var,command=lambda c=cat:self.toggle(c)).pack(side='left')
   ttk.Button(row,text='↻ Change',command=lambda c=cat:self.reroll(c)).pack(side='right')
  ttk.Separator(left).pack(fill='x',pady=8)
  ttk.Label(left,text='RUSTICATION',font=('TkDefaultFont',10,'bold')).pack(anchor='w',pady=(2,4))
  ttk.Checkbutton(left,text='On ground floor',variable=self.rust_first,command=self.compose_module).pack(anchor='w',pady=1)
  ttk.Checkbutton(left,text='On second floor',variable=self.rust_second,command=self.compose_module).pack(anchor='w',pady=1)
  rr=ttk.Frame(left); rr.pack(fill='x',pady=2)
  ttk.Label(rr,text='Number of courses').pack(side='left')
  ttk.Spinbox(rr,from_=1,to=20,textvariable=self.rust_count,width=5,command=self.compose_module).pack(side='right')
  ttk.Separator(left).pack(fill='x',pady=8)
  ttk.Label(left,text='Module editing view').pack(anchor='w',pady=(8,2))
  mode_row=ttk.Frame(left);mode_row.pack(fill='x',pady=(0,5))
  ttk.Radiobutton(mode_row,text='ISO 2:1',variable=self.module_view,value='ISO',command=self.change_module_view).pack(side='left',padx=(0,14))
  ttk.Radiobutton(mode_row,text='FRONT 45°',variable=self.module_view,value='FRONT',command=self.change_module_view).pack(side='left')
  ttk.Label(left,text='FRONT elements align to visible glass; FRONT offsets are independent of ISO.',wraplength=270).pack(anchor='w',pady=(0,5))
  ttk.Label(left,text='Move selected component (px)').pack(anchor='w')
  self.selected=tk.StringVar(value=LABELS['glass'])
  self.selected_label=ttk.Label(left,text='Selected component: Glass',font=('TkDefaultFont',10,'bold')); self.selected_label.pack(anchor='w',pady=(3,0))
  self.selector=ttk.Combobox(left,state='readonly',textvariable=self.selected,values=[LABELS[c] for c in ORDER]); self.selector.pack(fill='x',pady=4)
  self.selector.bind('<<ComboboxSelected>>',self.sync_offset)
  row=ttk.Frame(left); row.pack(fill='x')
  ttk.Label(row,text='X').pack(side='left'); self.xvar=tk.IntVar(value=0); ttk.Spinbox(row,from_=-100,to=100,width=6,textvariable=self.xvar).pack(side='left',padx=(3,10))
  ttk.Label(row,text='Y').pack(side='left'); self.yvar=tk.IntVar(value=0); ttk.Spinbox(row,from_=-100,to=100,width=6,textvariable=self.yvar).pack(side='left',padx=3)
  ttk.Button(left,text='Apply X/Y',command=self.apply_offset).pack(fill='x',pady=(4,8))
  ttk.Separator(left).pack(fill='x',pady=5)
  ttk.Label(left,text='Recolour selected component',font=('TkDefaultFont',10,'bold'),wraplength=260).pack(anchor='w')
  ttk.Label(left,text='Colour applies to all instances of this component.',wraplength=260).pack(anchor='w',pady=(2,4))
  row=ttk.Frame(left); row.pack(fill='x')
  ttk.Button(row,text='Component colour from palette…',command=lambda:self.open_palette('component')).pack(side='left',fill='x',expand=True)
  self.component_swatch=tk.Label(row,text='Original',bg='#d8d0c2',relief='groove',width=10); self.component_swatch.pack(side='left',padx=(5,0),ipady=3)
  self.mode_var=tk.StringVar(value='Preserve shading')
  self.mode_box=ttk.Combobox(left,state='readonly',textvariable=self.mode_var,values=['Preserve shading','Hue shift'],width=24); self.mode_box.pack(fill='x',pady=(5,3)); self.mode_box.bind('<<ComboboxSelected>>',self.change_component_mode)
  ttk.Button(left,text='Reset component colour',command=self.reset_component_color).pack(fill='x',pady=(0,7))
  ttk.Button(left,text='Save module…',command=self.save_module).pack(fill='x',pady=2)
  ttk.Button(left,text='APPLY MODULE →',command=self.apply_module).pack(fill='x',pady=(8,3))
  ttk.Label(left,text='The sprite library is included.',wraplength=260).pack(anchor='w',pady=(8,0))
  self.asset_info=tk.StringVar(value='')
  ttk.Label(left,textvariable=self.asset_info,wraplength=260).pack(anchor='w',pady=3)
  ttk.Label(right,text='Preview of four floor types · ISO/FRONT · select a type or drag a component',font=('TkDefaultFont',11,'bold')).pack(anchor='w')
  preview_grid=ttk.Frame(right); preview_grid.pack(fill='both',expand=True,pady=(8,4))
  self.type_canvases=[]; self.type_photos=[None]*4
  for idx,name in enumerate(self.type_names):
   card=ttk.Frame(preview_grid,relief='solid',borderwidth=2); card.grid(row=idx//2,column=idx%2,sticky='nsew',padx=3,pady=3)
   title=ttk.Label(card,text=name,font=('TkDefaultFont',10,'bold')); title.pack(anchor='w',padx=4,pady=2)
   cv=tk.Canvas(card,bg='#303238',highlightthickness=0); cv.pack(fill='both',expand=True)
   cv.bind('<Configure>',lambda e,i=idx:self.show_type_preview(i))
   cv.bind('<Button-1>',lambda e,i=idx:self.preview_click(i,e))
   cv.bind('<B1-Motion>',self.move_drag); cv.bind('<ButtonRelease-1>',lambda e:setattr(self,'drag',None))
   self.type_canvases.append(cv)
  self.module_canvas=self.type_canvases[0]
  self.module_status=tk.StringVar(value=''); ttk.Label(right,textvariable=self.module_status).pack(anchor='w')
 def build_facade_tab(self):
  # Scrollable assembly controls as well, so export/save buttons stay accessible.
  panel=ttk.Frame(self.tab_facade,width=320); panel.pack(side='left',fill='y'); panel.pack_propagate(False)
  left_canvas=tk.Canvas(panel,highlightthickness=0,width=310)
  left_scroll=ttk.Scrollbar(panel,orient='vertical',command=left_canvas.yview)
  left_canvas.configure(yscrollcommand=left_scroll.set)
  left_scroll.pack(side='right',fill='y')
  left_canvas.pack(side='left',fill='both',expand=True)
  left=ttk.Frame(left_canvas,padding=8)
  left_window=left_canvas.create_window((0,0),window=left,anchor='nw')
  def _facade_panel_configure(_event=None):
   left_canvas.configure(scrollregion=left_canvas.bbox('all'))
  def _facade_canvas_configure(event):
   left_canvas.itemconfigure(left_window,width=event.width)
  left.bind('<Configure>',_facade_panel_configure)
  left_canvas.bind('<Configure>',_facade_canvas_configure)
  def _facade_wheel(event):
   if getattr(event,'delta',0): left_canvas.yview_scroll(int(-event.delta/120) or (-1 if event.delta>0 else 1),'units')
   elif getattr(event,'num',None)==4: left_canvas.yview_scroll(-1,'units')
   elif getattr(event,'num',None)==5: left_canvas.yview_scroll(1,'units')
  left_canvas.bind_all('<MouseWheel>',_facade_wheel,add='+')
  left_canvas.bind_all('<Button-4>',_facade_wheel,add='+')
  left_canvas.bind_all('<Button-5>',_facade_wheel,add='+')
  right=ttk.Frame(self.tab_facade,padding=8); right.pack(side='right',fill='both',expand=True)
  ttk.Label(left,text='ISOMETRIC FLOOR STRIPS' ,font=('TkDefaultFont',11,'bold'),wraplength=275).pack(anchor='w')
  ttk.Label(left,text='First create a module. Each floor uses continuous isometric wall strips with window modules inserted.',wraplength=275).pack(anchor='w',pady=(5,8))
  ttk.Label(left,text='Width of one side (px)').pack(anchor='w')
  self.facade_width_spin=ttk.Spinbox(left,from_=12,to=1000,increment=2,textvariable=self.facade_width,width=8,command=self.render_facade)
  self.facade_width_spin.pack(anchor='w',pady=(2,7))
  self.facade_width_spin.bind('<KeyRelease>',lambda e:self.root.after_idle(self.render_facade))
  ttk.Label(left,text='Number of floors').pack(anchor='w')
  ttk.Spinbox(left,from_=1,to=40,textvariable=self.floors,width=8,command=self.render_facade).pack(anchor='w',pady=(2,7))
  ttk.Label(left,text='Windows per side, per floor').pack(anchor='w',pady=(2,3))
  for i,name in enumerate(self.type_names):
   row=ttk.Frame(left); row.pack(fill='x',pady=1)
   ttk.Label(row,text=name,width=19).pack(side='left')
   ttk.Spinbox(row,from_=0,to=40,textvariable=self.floor_counts[i],width=6,command=self.render_facade).pack(side='right')
  ttk.Separator(left).pack(fill='x',pady=5)
  ttk.Label(left,text='WINDOW SPACING',font=('TkDefaultFont',10,'bold'),wraplength=275).pack(anchor='w',pady=(2,5))
  ttk.Label(left,text='Windows on each floor remain centred; only spacing between them changes.',wraplength=275).pack(anchor='w',pady=(0,5))
  self.floor_gap_vars=[]
  for i,name in enumerate(self.type_names):
   box=ttk.LabelFrame(left,text=name,padding=5); box.pack(fill='x',pady=3)
   gap=tk.IntVar(value=0)
   row=ttk.Frame(box); row.pack(fill='x')
   ttk.Label(row,text='Window spacing (px)').pack(side='left')
   sp=ttk.Spinbox(row,from_=0,to=120,increment=2,textvariable=gap,width=6,command=self.render_facade)
   sp.pack(side='right')
   sp.bind('<KeyRelease>',lambda e:self.root.after_idle(self.render_facade))
   self.floor_gap_vars.append(gap)
  ttk.Label(left,text='Each floor is a continuous V-shaped isometric wall strip. Windows replace selected segments on each side.',wraplength=275).pack(anchor='w',pady=(3,7))
  ttk.Separator(left).pack(fill='x',pady=5)
  ttk.Separator(left).pack(fill='x',pady=7)
  ttk.Label(left,text='FOUNDATION',font=('TkDefaultFont',10,'bold')).pack(anchor='w',pady=(2,5))
  ttk.Checkbutton(left,text='Add foundation',variable=self.first_foundation,command=self.render_facade).pack(anchor='w',pady=2)
  rr=ttk.Frame(left); rr.pack(fill='x',pady=2)
  ttk.Button(rr,text='Change foundation',command=self.reroll_foundation).pack(side='left',fill='x',expand=True)
  ttk.Checkbutton(left,text='Match wall colour',variable=self.foundation_color_enabled,command=self.render_facade).pack(anchor='w',pady=2)
  ttk.Button(left,text='Foundation colour…',command=self.choose_foundation_color).pack(fill='x',pady=2)
  ttk.Label(left,text='Foundation offset (px)').pack(anchor='w',pady=(5,1))
  fr=ttk.Frame(left); fr.pack(fill='x')
  ttk.Label(fr,text='X').pack(side='left'); ttk.Spinbox(fr,from_=-100,to=100,textvariable=self.foundation_x,width=6,command=self.render_facade).pack(side='left',padx=(3,10))
  ttk.Label(fr,text='Y').pack(side='left'); ttk.Spinbox(fr,from_=-100,to=100,textvariable=self.foundation_y,width=6,command=self.render_facade).pack(side='left',padx=3)
  ttk.Label(left,text='Move the foundation up, down or sideways.',wraplength=270).pack(anchor='w',pady=(2,5))
  ttk.Button(left,text='Refresh preview',command=self.render_facade).pack(fill='x',pady=(6,3))
  ttk.Button(left,text='Save project JSON…',command=self.save_project).pack(fill='x',pady=3)
  ttk.Button(left,text='Open project JSON…',command=self.load_project).pack(fill='x',pady=3)
  ttk.Button(left,text='Export facade PNG…',command=self.export_facade).pack(fill='x',pady=3)
  self.facade_status=tk.StringVar(value='Module has not been applied yet.')
  ttk.Label(right,text='Final assembly preview',font=('TkDefaultFont',11,'bold')).pack(anchor='w')
  ttk.Label(right,text='Original ISO 2:1 facade; FRONT is generated automatically for rotations.',wraplength=480).pack(anchor='w')
  self.facade_canvas=tk.Canvas(right,bg='#303238',highlightthickness=0); self.facade_canvas.pack(fill='both',expand=True,pady=(8,4))
  self.facade_canvas.bind('<Configure>',lambda e:self.show_facade())
  ttk.Label(right,textvariable=self.facade_status).pack(anchor='w')
 def _capture_type_state(self):
  return {'wall_color':self.wall_color,'enabled':dict(self.enabled),'choice':dict(self.choice),'offset':{k:list(v) for k,v in self.offset.items()},'front_offset':{k:list(v) for k,v in self.front_offset.items()},'component_colors':dict(self.component_colors),'component_modes':dict(self.component_modes),'component_strength':dict(self.component_strength),'extra_height':int(self.extra_wall_height.get()),'window_size':self.window_size.get()}
 def _restore_type_state(self,state):
  self.wall_color=state['wall_color']; self.enabled=dict(state['enabled']); self.choice=dict(state['choice']); self.offset={k:list(v) for k,v in state['offset'].items()}; self.front_offset={k:list(v) for k,v in state.get('front_offset',{c:[0,0] for c in ORDER}).items()}; self.component_colors=dict(state['component_colors']); self.component_modes=dict(state['component_modes']); self.component_strength=dict(state['component_strength']); self.extra_wall_height.set(state['extra_height']); self.window_size.set(state.get('window_size','M'))
  for c in ORDER: self.check_vars[c].set(self.enabled[c])
  self.swatch.configure(bg=self.wall_color,text=self.wall_color)
  self.wall_palette.set(next((n for n,col in ARCH_PALETTE if col.lower()==self.wall_color.lower()),'Custom colour'))
  self.sync_offset()
 def select_type(self,event=None):
  if self.type_states: self.type_states[self.active_type]=self._capture_type_state()
  new=self.type_selector.current()
  if new<0: return
  self.active_type=new
  if self.independent_edit.get() and new in self.type_states: self._restore_type_state(self.type_states[new])
  else:
   # Shared mode uses the current module definition for all types.
   if self.type_states: self._restore_type_state(self.type_states.get(0,self._capture_type_state()))
  self.compose_module()
 def toggle_independent(self):
  self.type_states[self.active_type]=self._capture_type_state()
  if self.independent_edit.get():
   for i in range(4): self.type_states.setdefault(i,self._capture_type_state())
  else:
   shared=self._capture_type_state()
   for i in range(4): self.type_states[i]=copy.deepcopy(shared)
  self.compose_module()
 def preview_click(self,index,event):
  if index!=self.active_type:
   self.type_states[self.active_type]=self._capture_type_state()
   self.active_type=index; self.type_selector.current(index)
   if self.independent_edit.get(): self._restore_type_state(self.type_states[index])
   else:
    state=self._capture_type_state()
    for i in range(4): self.type_states[i]=state
   self.compose_module(); return
  cv=self.type_canvases[index]
  if self.module is None:return
  if self.module_view.get()=='FRONT':
   current_image,self.front_layers=self._front_module(index,with_layers=True)
   current_layers=self.front_layers
  else:
   current_image=self.module
   current_layers=self.layers
  scale=min((max(1,cv.winfo_width()-20))/current_image.width,(max(1,cv.winfo_height()-38))/current_image.height,18); scale=max(.25,scale)
  shown_w=max(1,int(current_image.width*scale)); shown_h=max(1,int(current_image.height*scale)); ox=(cv.winfo_width()-shown_w)//2; oy=(cv.winfo_height()-shown_h)//2+8
  self.module_scale=scale; self.module_origin=(ox,oy); self.scale=scale; self.preview_origin=(ox,oy)
  x=int((event.x-ox)/scale); y=int((event.y-oy)/scale)
  for c in reversed(ORDER):
   layer=current_layers.get(c)
   if layer and 0<=x<layer.width and 0<=y<layer.height and layer.getpixel((x,y))[3]>0:
    offsets=self.front_offset if self.module_view.get()=='FRONT' else self.offset
    self.drag=(c,event.x,event.y,offsets[c][0],offsets[c][1]); self.selected.set(LABELS[c]); self.sync_offset(); return
 def open_palette(self, target='wall'):
  # The palette image is shipped inside the embedded library folder.
  palette_path=LIBRARY/'palette.png'
  if not palette_path.exists(): palette_path=ROOT/'palette.png'
  if not palette_path.exists():
   matches=list(ROOT.rglob('palette.png'))
   if matches:palette_path=matches[0]
  if not palette_path.exists():
   chosen=filedialog.askopenfilename(title='Choose palette image',filetypes=[('PNG palette','*.png'),('Images','*.png *.jpg *.jpeg')])
   if not chosen:return
   palette_path=Path(chosen)
  component=self.selected_cat() if target=='component' else None
  initial=(self.component_colors.get(component) if component else None) or self.wall_color
  try: im=Image.open(palette_path).convert('RGB')
  except Exception as e:
   messagebox.showerror('Palette error',f'Could not open the palette image:\n{e}')
   return
  win=tk.Toplevel(self.root); win.title('Architectural palette' if target=='wall' else 'Decoration colour from architectural palette'); win.transient(self.root); win.grab_set()
  maxw,maxh=900,650; scale=min(maxw/im.width,maxh/im.height,1)
  shown=im.resize((max(1,int(im.width*scale)),max(1,int(im.height*scale))),Image.Resampling.NEAREST)
  body=ttk.Frame(win,padding=8); body.pack(fill='both',expand=True)
  side=ttk.Frame(body); side.pack(side='right',fill='y',padx=(10,0))
  canvas=tk.Canvas(body,width=shown.width,height=shown.height,highlightthickness=0,cursor='crosshair')
  canvas.pack(side='left',fill='both',expand=False)
  photo=ImageTk.PhotoImage(shown); canvas.create_image(0,0,image=photo,anchor='nw'); canvas.image=photo
  ttk.Label(side,text='Selected colour',font=('TkDefaultFont',10,'bold')).pack(anchor='w')
  preview=tk.Label(side,bg=initial,relief='sunken',width=18,height=5); preview.pack(pady=6)
  hexvar=tk.StringVar(value=initial); ttk.Label(side,textvariable=hexvar,font=('TkFixedFont',11)).pack(pady=(0,10))
  target_text='wall' if target=='wall' else f'component {LABELS.get(component, "not selected")}'
  ttk.Label(side,text=f'Click a colour for {target_text}.\nThen click Apply.',justify='left',wraplength=180).pack(anchor='w',pady=(0,12))
  result={'color':initial}; cross=canvas.create_line(0,0,0,0,fill='white',width=1); cross2=canvas.create_line(0,0,0,0,fill='black',width=1)
  def update_at(e):
   x=max(0,min(im.width-1,int(e.x/scale))); y=max(0,min(im.height-1,int(e.y/scale)))
   col=im.getpixel((x,y)); hx='#%02X%02X%02X'%col; result['color']=hx
   px=x*scale; py=y*scale
   canvas.coords(cross,px-8,py,px+8,py); canvas.coords(cross2,px,py-8,px,py+8)
   preview.configure(bg=hx); hexvar.set(hx)
  canvas.bind('<Button-1>',update_at)
  buttons=ttk.Frame(side); buttons.pack(side='bottom',fill='x',pady=(12,0))
  def apply():
   if target=='component':
    c=self.selected_cat()
    if not c:
     messagebox.showinfo('No component selected','First choose a component from the list.',parent=win); return
    self.component_colors[c]=result['color']
    if hasattr(self,'component_swatch'): self.component_swatch.configure(bg=result['color'],text=result['color'])
   else:
    self.wall_color=result['color']; self.swatch.configure(bg=self.wall_color,text=self.wall_color); self.wall_palette.set('Custom colour')
   self.compose_module(); win.destroy()
  ttk.Button(buttons,text='Apply',command=apply).pack(fill='x',pady=2)
  ttk.Button(buttons,text='Cancel',command=win.destroy).pack(fill='x',pady=2)
  win.update_idletasks(); win.geometry(f'{min(win.winfo_reqwidth(),1150)}x{min(win.winfo_reqheight(),800)}')
 def change_module_view(self):
  # The same module is previewed in two projections; neither view changes the other.
  self.drag=None
  self.sync_offset()
  self.compose_module()

 def show_type_preview(self,index):
  if not hasattr(self,'type_canvases') or self.module is None:return
  current=self._capture_type_state()
  try:
   if self.independent_edit.get() and index!=self.active_type and index in self.type_states:
    self._restore_type_state(self.type_states[index])
   if self.module_view.get()=='FRONT':
    im,_=self._front_module(index,with_layers=True)
   else:
    self._compose_only(rustication_enabled=self._rust_for_type(index))
    im=self.module.copy()
  finally:
   self._restore_type_state(current)
   self._compose_only(rustication_enabled=self._rust_for_type(self.active_type))
  cv=self.type_canvases[index]
  cw,ch=max(1,cv.winfo_width()),max(1,cv.winfo_height())
  scale=min((cw-20)/im.width,(ch-38)/im.height,18);scale=max(.25,scale)
  shown=im.resize((max(1,int(im.width*scale)),max(1,int(im.height*scale))),Image.Resampling.NEAREST)
  photo=ImageTk.PhotoImage(shown);self.type_photos[index]=photo
  cv.delete('all');cv.create_image(cw//2,ch//2+8,image=photo,anchor='center')
  cv.master.configure(relief='solid',borderwidth=4 if index==self.active_type else 1)

 def _rust_for_type(self,index):
  return bool(self.rust_first.get()) if index==0 else bool(self.rust_second.get()) if index==1 else False
 def _compose_only(self, rustication_enabled=None):
  w,h=self.module_size(); self.layers={}
  wall=self.extended_wall().copy()
  if rustication_enabled is None: rustication_enabled=self._rust_for_type(self.active_type)
  # Rustication belongs to the wall layer: window/decor sprites are added above it and can never erase it.
  wall=self.apply_rustication(wall,rustication_enabled)
  self.module=wall
  for c in ORDER:
   if not self.enabled[c] or not self.choice[c]: continue
   item=self.choice[c]
   sprite=item['image']  # Light ISO artwork; wall shading is procedural.
   tint=self.component_colors.get(c)
   if tint: sprite=tint_sprite(sprite,tint,self.component_modes[c],self.component_strength[c])
   layer=Image.new('RGBA',(w,h),(0,0,0,0)); bx,by=self.default_position(c,sprite); ox,oy=self.offset[c]
   if c=='cornice' and sprite.height<=5:
    # Cornice is also a repeating 2px isometric segment, not one full-width sprite.
    piece=sprite.crop((0,0,min(2,sprite.width),sprite.height))
    x=bx+ox; y=by+oy
    while x<w:
     place_clipped(layer,piece,x,y); x+=2; y+=1
   else:
    place_clipped(layer,sprite,bx+ox,by+oy)
   self.layers[c]=layer; self.module.alpha_composite(layer)
 def load_assets(self):
  errors=[]
  for fn,(cat,cell) in SHEETS.items():
   path=LIBRARY/fn
   if not path.exists(): errors.append(fn);continue
   try:
    if cat=='wall':
     self.assets[cat]=[{'name':path.stem,'image':Image.open(path).convert('RGBA')}]
    else:
     self.assets[cat]=paired_sheet(path,cell)
   except Exception as e: errors.append(f'{fn}: {e}')
  self.window_sheets={'frame':{},'casing':{},'sandrik':{},'sill':{}}
  self.window_glass=[]
  glass=LIBRARY/'windows'/'glass_16_17.png'
  try:
   if not glass.exists(): raise FileNotFoundError('glass_16_17.png')
   glass_pairs=paired_sheet(glass,(16,17))
   # The pair order in the artist's sheet runs from XXS to L.
   for size, pair in zip(reversed(WINDOW_SIZES),glass_pairs):
    pair['size']=size;pair['name']=f'glass {size}'
    self.window_glass.append(pair)
  except Exception as e:errors.append(f'glass: {e}')
  root=LIBRARY/'windows'
  for cat,folder in WINDOW_ASSETS.items():
   for path in sorted((root/folder).glob('*.png')) if (root/folder).exists() else []:
    m=re.search(r'(XXS|XS|L|M|S)_([0-9]+)x([0-9]+)',path.stem,re.I)
    if not m: errors.append(f'{path.name}: unknown filename');continue
    size=m.group(1).upper()
    cell=(int(m.group(2)),int(m.group(3)))
    sheet_size=Image.open(path).size
    if sheet_size[0]%cell[0] or sheet_size[1]%cell[1]:
     errors.append(f'{path.name}: {sheet_size} does not match cell {cell}')
     continue
    try:self.window_sheets[cat][size]=paired_sheet(path,cell,size)
    except Exception as e:errors.append(f'{path.name}: {e}')
  self.assets['glass']=list(self.window_glass)
  for cat in WINDOW_ASSETS:
   self.assets[cat]=[a for group in self.window_sheets[cat].values() for a in group]
  self.wall_source=self.assets['wall'][0]['image'] if self.assets['wall'] else None
  if self.assets['foundation']:self.foundation_choice=random.choice(self.assets['foundation'])
  counts=[f'{LABELS[c]}: {len(self.assets[c])} ISO/FRONT pairs' for c in ORDER]
  counts += [f"Glass: {len(self.window_glass)} sizes",f"Rustication: {len(self.assets['rustication'])} pairs",f"Foundation: {len(self.assets['foundation'])} pairs"]
  self.asset_info.set('\n'.join(counts)+(('\nMissing: '+', '.join(errors)) if errors else ''))
  if errors:messagebox.showwarning('Sprite library','Loading problems:\n'+'\n'.join(errors))
 def _size_assets(self,cat):
  size=self.window_size.get().upper()
  if cat=='glass': return [a for a in self.assets['glass'] if a.get('size')==size]
  if cat in self.window_sheets:
   variants=self.window_sheets[cat].get(size)
   if not variants and size in ('XS','XXS') and cat in ('sandrik','sill'):
    variants=self.window_sheets[cat].get('S')
   return variants or []
  return self.assets.get(cat,[])
 def change_window_size(self,event=None):
  size=self.window_size.get().upper()
  if self.enabled.get('glass'):
   opts=self._size_assets('glass'); self.choice['glass']=opts[0] if opts else None
  for cat in ('frame','casing','sill','sandrik'):
   if self.enabled.get(cat):
    opts=self._size_assets(cat); self.choice[cat]=random.choice(opts) if opts else None
  self.compose_module()
 def pick_wall_preset(self,event=None):
  name=self.wall_palette.get()
  for n,col in ARCH_PALETTE:
   if n==name:
    self.wall_color=col; self.swatch.configure(bg=col,text=col); self.compose_module(); return
 def choose_component_color(self):
  self.open_palette('component')
 def change_component_mode(self,event=None):
  c=self.selected_cat()
  if c:
   self.component_modes[c]='hue' if self.mode_var.get()=='Hue shift' else 'shade'; self.compose_module()
 def reset_component_color(self):
  c=self.selected_cat()
  if c:
   self.component_colors[c]=None; self.component_modes[c]='shade'; self.mode_var.set('Preserve shading'); self.component_swatch.configure(bg='#d8d0c2',text='Original'); self.compose_module()
 def selected_cat(self):
  for c in ORDER:
   if LABELS[c]==self.selected.get(): return c
  return None
 def choose_color(self):
  self.open_palette()
 def toggle(self,c):
  self.enabled[c]=self.check_vars[c].get()
  if c=='glass' and self.enabled[c]:
   opts=self._size_assets('glass'); self.choice[c]=opts[0] if opts else None
   if self.choice[c]: self.window_size.set(self.choice[c].get('size','M'))
  else:
   opts=self._size_assets(c); self.choice[c]=random.choice(opts) if self.enabled[c] and opts else None
  self.offset[c]=[0,0];self.front_offset[c]=[0,0];self.compose_module()
 def reroll(self,c):
  if not self.enabled[c]: self.check_vars[c].set(True); self.enabled[c]=True
  arr=self._size_assets(c)
  if arr:
   choices=[a for a in arr if a is not self.choice[c]]; self.choice[c]=random.choice(choices or arr)
   if c=='glass' and self.choice[c]: self.window_size.set(self.choice[c].get('size','M'))
  self.compose_module()
 def module_size(self):
  w,h=self.wall_source.size if self.wall_source else (12,25)
  return (w,max(5,h+int(self.extra_wall_height.get())))
 def extended_wall(self):
  if not self.wall_source: return Image.new('RGBA',self.module_size(),self.wall_color)
  source=recolor_wall(self.wall_source,self.wall_color)
  extra=self.module_size()[1]-source.height
  if extra==0: return source
  # Keep pixel-art edges crisp: insert/remove rows in the middle of the wall, never resample.
  if extra>0:
   top=max(1,source.height//3); bottom=max(top+1,source.height*2//3)
   band=source.crop((0,top,source.width,bottom))
   rows=[]
   for y in range(extra): rows.append(band.crop((0,(y%band.height),band.width,(y%band.height)+1)))
   out=Image.new('RGBA',(source.width,source.height+extra),(0,0,0,0))
   out.alpha_composite(source.crop((0,0,source.width,top)),(0,0))
   for i,row in enumerate(rows): out.alpha_composite(row,(0,top+i))
   out.alpha_composite(source.crop((0,top,source.width,source.height)),(0,top+extra))
   return out
  cut=-extra; top=max(1,source.height//3); bottom=min(source.height-1,top+cut)
  out=Image.new('RGBA',(source.width,source.height-cut),(0,0,0,0))
  out.alpha_composite(source.crop((0,0,source.width,top)),(0,0))
  out.alpha_composite(source.crop((0,bottom,source.width,source.height)),(0,top))
  return out
 def default_position(self,c,sprite):
  # Initial positions follow the 12x25 wall module; user can refine them pixel-by-pixel.
  w,h=self.module_size(); cx=max(0,(w-sprite.width)//2)
  return {'glass':(max(0,(w-sprite.width)//2),max(1,(h-sprite.height)//3)),'frame':(max(0,(w-sprite.width)//2),max(0,(h-sprite.height)//3-1)),'casing':(max(0,(w-sprite.width)//2),max(0,(h-sprite.height)//3-2)),'sill':(max(0,(w-sprite.width)//2),min(h-sprite.height,h//2+5)),'bracket':(2,19),'sandrik':(max(0,(w-sprite.width)//2),max(0,(h-sprite.height)//3-2)),'cornice':(0,0)}[c]
 def compose_module(self):
  self._compose_only()
  if hasattr(self,'type_states'):
   state=self._capture_type_state()
   if self.independent_edit.get(): self.type_states[self.active_type]=state
   else:
    for i in range(4): self.type_states[i]=state
  if hasattr(self,'type_canvases'):
   for i in range(4): self.show_type_preview(i)
  self.show_module()
  w,h=self.module.size
  self.module_status.set(f'Active type: {self.type_names[self.active_type]} · {self.module_view.get()} · {w} × {h} px. ISO/FRONT offsets are independent.')
  if getattr(self,'module_applied',False): self.render_facade()
 def sync_offset(self,event=None):
  for c in ORDER:
   if LABELS[c]==self.selected.get():
    self.selected_label.configure(text='Selected component: '+LABELS[c])
    offsets=self.front_offset if self.module_view.get()=='FRONT' else self.offset
    self.xvar.set(offsets[c][0]); self.yvar.set(offsets[c][1])
    col=self.component_colors[c]; self.component_swatch.configure(bg=col or '#d8d0c2',text=col or 'Original')
    self.mode_var.set('Hue shift' if self.component_modes[c]=='hue' else 'Preserve shading')
    return
 def apply_offset(self):
  for c in ORDER:
   if LABELS[c]==self.selected.get() and self.enabled[c]:
    offsets=self.front_offset if self.module_view.get()=='FRONT' else self.offset
    offsets[c]=[int(self.xvar.get()),int(self.yvar.get())];self.compose_module();return
 def draw_image(self,canvas,im):
  cw,ch=max(1,canvas.winfo_width()),max(1,canvas.winfo_height())
  scale=min((cw-30)/im.width,(ch-30)/im.height,18); scale=max(.25,scale)
  shown=im.resize((max(1,int(im.width*scale)),max(1,int(im.height*scale))),Image.Resampling.NEAREST)
  photo=ImageTk.PhotoImage(shown); canvas.delete('all'); canvas.create_image(cw//2,ch//2,image=photo,anchor='center');
  return photo,scale,(cw//2-shown.width//2,ch//2-shown.height//2)
 def show_module(self):
  if self.module is None:return
  if hasattr(self,'type_canvases'):
   for i in range(4): self.show_type_preview(i)
  else:
   self.module_photo,self.module_scale,self.module_origin=self.draw_image(self.module_canvas,self.module)
   self.scale=self.module_scale; self.preview_origin=self.module_origin
 def start_drag(self,e):
  if self.module is None:return
  x=int((e.x-self.module_origin[0])/self.module_scale); y=int((e.y-self.module_origin[1])/self.module_scale)
  for c in reversed(ORDER):
   layer=self.layers.get(c)
   if layer and 0<=x<layer.width and 0<=y<layer.height and layer.getpixel((x,y))[3]>0:
    self.drag=(c,e.x,e.y,self.offset[c][0],self.offset[c][1]); self.selected.set(LABELS[c]); self.sync_offset(); return
 def move_drag(self,e):
  if not self.drag:return
  c,sx,sy,ox,oy=self.drag
  offsets=self.front_offset if self.module_view.get()=='FRONT' else self.offset
  offsets[c]=[ox+round((e.x-sx)/self.module_scale),oy+round((e.y-sy)/self.module_scale)]
  self.xvar.set(offsets[c][0]);self.yvar.set(offsets[c][1]);self.compose_module()
 def apply_module(self):
  # Freeze a current composed module snapshot for assembly; editing the first tab won't silently alter it.
  self.type_states[self.active_type]=self._capture_type_state()
  if not self.independent_edit.get():
   for i in range(4): self.type_states[i]=self._capture_type_state()
  self.type_modules={}
  current=self._capture_type_state()
  original_active=self.active_type
  for i in range(4):
   self.active_type=i
   if self.independent_edit.get(): self._restore_type_state(self.type_states[i])
   else: self._restore_type_state(current)
   self._compose_only(rustication_enabled=self._rust_for_type(i)); self.type_modules[i]=self.module.copy()
  self.active_type=original_active
  self._restore_type_state(current); self._compose_only(rustication_enabled=self._rust_for_type(self.active_type)); self.applied_module=self.type_modules.get(2,self.module.copy()); self.module_applied=True
  self.tabs.select(self.tab_facade); self.render_facade()
 def reroll_foundation(self):
  arr=self.assets.get('foundation',[])
  if arr:
   choices=[a for a in arr if a is not self.foundation_choice]
   self.foundation_choice=random.choice(choices or arr)
   self.render_facade()
 def choose_foundation_color(self):
  res=colorchooser.askcolor(color=self.foundation_color,title='Foundation colour')
  if res and res[1]:
   self.foundation_color=res[1]; self.foundation_color_enabled.set(False); self.render_facade()
 def _repeat_iso_trim(self, target, tile, y_start=0):
  """Repeat a 2px-wide trim fragment across the wall, shifting 1px per 2px horizontally."""
  if tile.width > 2:
   tile=tile.crop((0,0,2,tile.height))
  x=0; step=max(1,tile.width); y=int(y_start)
  while x < target.width:
   place_clipped(target,tile,x,y)
   x += step; y += 1
 def apply_rustication(self, base, enabled, state_layers=None):
  if not enabled or not self.assets.get('rustication'): return base
  base=base.copy(); source=self.assets['rustication'][0]['image']
  tile=source.crop((0,0,min(2,source.width),source.height))
  # Recompute the vertical distribution from the CURRENT wall height, not 12x25 defaults.
  # Each horizontal repeat advances (tile.width, 1), so reserve that diagonal drop.
  diagonal_drop=max(0,((base.width-1)//max(1,tile.width)))
  top=0
  lowest_start=max(0,base.height-tile.height-diagonal_drop)
  top=min(top,lowest_start)
  count=max(1,min(40,int(self.rust_count.get())))
  if count==1: starts=[max(0,(top+lowest_start)//2)]
  else: starts=[round(top+i*(lowest_start-top)/(count-1)) for i in range(count)]
  for y_start in starts: self._repeat_iso_trim(base,tile,y_start)
  return base
 def make_first_floor_module(self, base=None, rust=False, add_foundation=True):
  base=(base or self.applied_module).copy()
  if add_foundation and self.first_foundation.get() and self.foundation_choice:
   f=self.foundation_choice['image'].copy()
   color=self.wall_color if self.foundation_color_enabled.get() else self.foundation_color
   f=tint_sprite(f,color,'shade',100)
   ox=int(self.foundation_x.get()); oy=base.height-1+int(self.foundation_y.get())
   left=min(0,ox); top=min(0,oy); right=max(base.width,ox+f.width); bottom=max(base.height,oy+f.height)
   extended=Image.new('RGBA',(right-left,bottom-top),(0,0,0,0))
   extended.alpha_composite(base,(-left,-top)); place_clipped(extended,f,ox-left,oy-top)
   return extended, left, top
  return base,0,0
 def _wall_only_snapshot(self, index):
  current=self._capture_type_state(); enabled=dict(self.enabled); active=self.active_type
  try:
   if self.independent_edit.get() and index in self.type_states: self._restore_type_state(self.type_states[index])
   self.active_type=index
   self.enabled={c:False for c in ORDER}
   self._compose_only(rustication_enabled=self._rust_for_type(index))
   return self.module.copy()
  finally:
   self.enabled=enabled; self.active_type=active; self._restore_type_state(current)
   self._compose_only(rustication_enabled=self._rust_for_type(active))
 def _band_wall_snapshot(self, index):
  """Build the rail tile: wall + that floor's rustication + cornice, no window beads."""
  current=self._capture_type_state(); active=self.active_type
  try:
   if self.independent_edit.get() and index in self.type_states:
    self._restore_type_state(self.type_states[index])
   self.active_type=index
   keep_cornice=bool(self.enabled.get('cornice',False) and self.choice.get('cornice'))
   self.enabled={c:False for c in ORDER}
   self.enabled['cornice']=keep_cornice
   self._compose_only(rustication_enabled=self._rust_for_type(index))
   return self.module.copy()
  finally:
   self.active_type=active
   self._restore_type_state(current)
   self._compose_only(rustication_enabled=self._rust_for_type(active))
 def _facade_width_changed(self, *_args):
  # Do not snap the user's value back to a tile multiple; every 2px change is valid.
  if getattr(self, '_width_render_pending', False): return
  self._width_render_pending=True
  def _run():
   self._width_render_pending=False
   if getattr(self, 'module_applied', False): self.render_facade()
  self.root.after_idle(_run)
 def _front_module(self,idx,with_layers=False,window_only=False):
  """FRONT sprites: use visible-pixel anchors around the window glass.

  Each component's manual FRONT offset is separate from the ISO offset.
  The transparent padding in sprite sheets must not shift the details.
  """
  iw,ih=self.module_size()
  fw=max(1,round(iw*2**0.5))
  # Preserve the original per-floor vertical rhythm: avoid rescaling rows.
  fh=max(5,ih-round(iw/2))
  base=Image.new('RGBA',(fw,fh),(0,0,0,0) if window_only else ImageColor.getrgb(self.wall_color)+(255,))
  layers={}
  if not window_only and self._rust_for_type(idx) and self.assets.get('rustication'):
   rust=self.assets['rustication'][0]['front_image']
   self._fill_front_rust(base,rust)
  sprites={}
  for cat in ORDER:
   item=self.choice.get(cat)
   if not self.enabled.get(cat) or not item:continue
   sprite=item.get('front_image',item['image'])
   tint=self.component_colors.get(cat)
   if tint:sprite=tint_sprite(sprite,tint,self.component_modes[cat],self.component_strength[cat])
   sprites[cat]=sprite

  # Anchor the visible GLASS, not the dimensions of the transparent PNG cell.
  glass=sprites.get('glass')
  gb=glass.getbbox() if glass is not None else None
  if gb is None:
   # Fallback when glass is disabled: use the frame as a central reference.
   glass=sprites.get('frame') or sprites.get('casing')
   gb=glass.getbbox() if glass is not None else None
  if gb is None:gb=(0,0,fw//2, max(3,fh//2))
  visible_w=gb[2]-gb[0];visible_h=gb[3]-gb[1]
  center_x=fw//2
  # Position the painted glass in the lower half to leave room for pediments.
  glass_top=max(2,round(fh*0.52)-visible_h//2)
  glass_bottom=glass_top+visible_h

  for cat in ORDER:
   if window_only and cat=='cornice':continue
   sprite=sprites.get(cat)
   if sprite is None:continue
   bbox=sprite.getbbox()
   if bbox is None:continue
   l,t,r,b=bbox
   visible_center2=l+r
   # Vertical offsets below are relative to the VISIBLE glass edges.
   # Multiple window decorations share exactly the same horizontal axis.
   x=round(center_x-visible_center2/2)
   if cat=='glass':
    y=glass_top-t
   elif cat in ('frame','casing'):
    y=glass_top-t
   elif cat=='sill':
    y=glass_bottom-t
   elif cat=='sandrik':
    y=glass_top-b
   elif cat=='bracket':
    y=glass_bottom-t
   else:
    y=-t
   dx,dy=self.front_offset.get(cat,(0,0))
   if cat!='glass' and glass is sprites.get('glass'):
    gx,gy=self.front_offset.get('glass',(0,0))
    dx+=gx;dy+=gy
   x+=dx;y+=dy
   layer=Image.new('RGBA',(fw,fh),(0,0,0,0))
   if cat=='cornice':
    # Repeating FRONT horizontal trim shares one stable baseline.
    piece=sprite
    first_x=x
    for xx in range(first_x,fw,max(1,piece.width)):
     place_clipped(layer,piece,xx,y)
    for xx in range(first_x-piece.width,-piece.width,-piece.width):
     place_clipped(layer,piece,xx,y)
   else:
    place_clipped(layer,sprite,x,y)
   layers[cat]=layer
   base.alpha_composite(layer)
  return (base,layers) if with_layers else base

 def _fill_front_rust(self, target, tile):
  """Full-height, continuous front rustication, without gaps between windows.

  The hand-drawn front tile is repeated in its original pixel dimensions,
  never scaled. Transparent pixels reveal the wall base color.
  """
  if tile is None or not tile.getbbox():return
  tw,th=tile.size
  for y in range(0,target.height,max(1,th)):
   for x in range(0,target.width,max(1,tw)):
    place_clipped(target,tile,x,y)

 def _build_front_facade(self):
  """One continuous FRONT facade background; windows are transparent overlays.

  Cornices and rustication are drawn across the whole elevation *before*
  placing windows. Window sprite backgrounds cannot erase the decoration.
  """
  rows=max(1,min(40,int(self.floors.get())))
  front_w=max(1,round(int(self.facade_width.get())*2**0.5))
  modules={}; states={}
  snapshot=self._capture_type_state(); active=self.active_type
  try:
   for i in range(4):
    if self.independent_edit.get() and i in self.type_states:
     self._restore_type_state(self.type_states[i])
    states[i]=self._capture_type_state()
    modules[i]=self._front_module(i,window_only=True)
  finally:
   self._restore_type_state(snapshot);self.active_type=active
  bands=[]
  for row in range(rows):
   idx=0 if row==0 else 1 if row==1 else 3 if row==rows-1 else 2
   tile=modules[idx]
   state=states[idx]
   count=max(0,min(40,int(self.floor_counts[idx].get())))
   iw=self.type_modules.get(idx,self.applied_module).width
   gap=max(0,int(self.floor_gap_vars[idx].get()))
   pitch=round((iw+gap)*2**0.5)
   full_w=max(front_w,tile.width+(count-1)*pitch if count else front_w)
   wall_color=ImageColor.getrgb(state['wall_color'])+(255,)
   band=Image.new('RGBA',(full_w,tile.height),wall_color)
   # Full-width/floor-height base decoration, independent of module count.
   if self._rust_for_type(idx) and self.assets.get('rustication'):
    self._fill_front_rust(band,self.assets['rustication'][0]['front_image'])
   if state['enabled'].get('cornice') and state['choice'].get('cornice'):
    item=state['choice']['cornice']
    trim=item.get('front_image',item['image'])
    tint=state['component_colors'].get('cornice')
    if tint:trim=tint_sprite(trim,tint,state['component_modes']['cornice'],state['component_strength']['cornice'])
    _,dy=state.get('front_offset',{}).get('cornice',(0,0))
    for xx in range(0,full_w,max(1,trim.width)):
     place_clipped(band,trim,xx,int(dy))
   start=round((full_w-(tile.width+(count-1)*pitch))/2) if count else 0
   for j in range(count):place_clipped(band,tile,start+j*pitch,0)
   if row==0 and self.first_foundation.get() and self.foundation_choice:
    f=self.foundation_choice['front_image']
    color=self.wall_color if self.foundation_color_enabled.get() else self.foundation_color
    f=tint_sprite(f,color,'shade',100)
    # The foundation belongs INSIDE the ground floor, immediately above its
    # bottom edge. Extending the image here used to add a fake extra floor
    # height, which subsequently desynchronised the Volume Editor wall.
    fy=band.height-f.height+int(self.foundation_y.get())
    for xx in range(round(self.foundation_x.get()*2**0.5),full_w,max(1,f.width)):
     place_clipped(band,f,xx,fy)
   bands.append(band)
  total=sum(im.height for im in bands)
  out=Image.new('RGBA',(max(i.width for i in bands),total),(0,0,0,0))
  y=0
  for im in reversed(bands):
   out.alpha_composite(im,((out.width-im.width)//2,y));y+=im.height
  return out

 def render_facade(self):
  if not getattr(self,'module_applied',False):
   self.facade_status.set('Create a module, then click APPLY MODULE.'); self.facade_canvas.delete('all'); return
  rows=max(1,min(40,int(self.floors.get())))
  floor_types=[]
  for row in range(rows):
   if row==0: idx=0
   elif row==1: idx=1
   elif row==rows-1: idx=3
   else: idx=2
   floor_types.append(idx)
  bands=[]
  for idx in floor_types:
   module=self.type_modules.get(idx,self.applied_module).copy()
   mw,mh=module.size
   iso_dy=max(1,round(mw/2))
   rail=self._band_wall_snapshot(idx).copy()
   # The rail for each floor uses that floor type's own editable wall height.
   # Never reuse the default module height: that caused gaps when a floor was taller/shorter.
   tile=Image.new('RGBA',(mw,mh),(0,0,0,0))
   place_clipped(tile,rail,0,mh-rail.height)
   count=max(0,min(40,int(self.floor_counts[idx].get())))
   gap=max(0,min(120,int(self.floor_gap_vars[idx].get())))
   pitch=mw+gap
   group_w=0 if count<=0 else mw+(count-1)*pitch
   band_w=max(1,int(self.facade_width.get()),group_w)
   if band_w%2: band_w+=1
   # Continuous wall rail, made from repeated full wall segments. Each segment advances
   # diagonally by half its width. The wall and window modules share the same floor height.
   segments=max(1,(band_w+mw-1)//mw)
   band_h=mh+(segments-1)*iso_dy
   band=Image.new('RGBA',(band_w,band_h),(0,0,0,0))
   for j in range(segments):
    x=j*mw; y=j*iso_dy
    place_clipped(band,tile,x,y)
   # Center the window group as a single mass on the facade midpoint, regardless of count.
   if count>0:
    start_x=(band_w-group_w)//2
    for j in range(count):
     x=start_x+j*pitch
     y=round(x*iso_dy/mw)
     place_clipped(band,module,x,y)
   # Foundation is a continuous rail attached only to the ground-floor band.
   # Repeat the 12px foundation segment across the width with the same isometric drift.
   if idx==0 and self.first_foundation.get() and self.foundation_choice:
    foundation=self.foundation_choice['image'].copy()
    fcolor=self.wall_color if self.foundation_color_enabled.get() else self.foundation_color
    foundation=tint_sprite(foundation,fcolor,'shade',100)
    # The ISO ground line rises by 1 pixel per 2 horizontal pixels.
    # Place the foundation along that SAME ground line and inside the
    # existing band instead of appending hundreds of transparent pixels.
    # The old band.height-1 anchor was at the very lowest *right* corner
    # of the sheared wall, far below its left corner.
    fx=int(self.foundation_x.get())
    fy=mh-foundation.height+int(self.foundation_y.get())
    x=fx
    while x < band.width:
     y=fy+round(x/2)
     place_clipped(band,foundation,x,y)
     x+=foundation.width
   bands.append((band,idx,mh,iso_dy))
  # Stack from the top down using each band's actual height. Adjacent floors overlap
  # by their own module height minus the isometric diagonal step, so custom heights
  # cannot create holes or detach the top floor.
  placements=[]
  y_positions=[0]*len(bands)
  for i in range(len(bands)-2,-1,-1):
   upper_height=bands[i+1][2]
   upper_dy=bands[i+1][3]
   y_positions[i]=y_positions[i+1]+max(1,upper_height-upper_dy)
  for i,(band,idx,mh,dy) in enumerate(bands):
   placements.append((0,y_positions[i],band))
  minx=min(x for x,y,im in placements); miny=min(y for x,y,im in placements)
  maxx=max(x+im.width for x,y,im in placements); maxy=max(y+im.height for x,y,im in placements)
  out=Image.new('RGBA',(max(1,maxx-minx),max(1,maxy-miny)),(0,0,0,0))
  for x,y,im in placements: place_clipped(out,im,x-minx,y-miny)
  # Physical wall height at the near-left corner of the ISO facade.
  # This is NOT the bounding-box height of a diagonally sheared picture:
  # the latter contains an additional width/2 pixels of horizontal run.
  # Derive it from the actual stacked floor modules, independently of
  # foundation decorations and transparent image margins.
  # An ISO floor image can end 2-6 px ABOVE its nominal module box.
  # Measure the actually painted bottom envelope instead of sizing a wall
  # from its transparent padding. Every x adds x/2 to the 2:1 baseline.
  # Use the median over the facade: individual decorations and pixel steps
  # cannot move the overall ground plane.
  import statistics
  alpha=out.getchannel('A')
  baselines=[]
  for xx in range(out.width):
   for yy in range(out.height-1,-1,-1):
    if alpha.getpixel((xx,yy)):
     baselines.append(yy+1-xx/2)
     break
  self.facade_wall_height_px=max(1,statistics.median(baselines)) if baselines else 1
  self.facade=out
  # A second master is constructed from the FRONT assets, not transformed
  # from the isometric façade. This is intentionally independent of blur.
  self.facade_front=self._build_front_facade()
  self.show_facade()
  if hasattr(self,"volume_app") and self.tabs.index(self.tabs.select())==2: self.update_volume_facade()
  counts=', '.join(f'{self.type_names[i]}: {self.floor_counts[i].get()}' for i in range(4))
  heights=', '.join(f'{self.type_names[idx]} {self.type_modules.get(idx,self.applied_module).height}px' for idx in sorted(set(floor_types)))
  self.facade_status.set(f'Floor strips with individual heights · rustication within walls · width {int(self.facade_width.get())}px · {rows} floors · {heights} · {counts} · size {out.width} × {out.height} px')
 def _build_volume_bridge(self):
  # Separate controls are attached to the existing Volume Editor's right
  # panel, keeping its geometry, rotation, save and cast-shadow UI intact.
  bar=ttk.Frame(self.volume_app.canvas.master)
  bar.pack(before=self.volume_app.canvas,fill='x',pady=(0,5))
  ttk.Checkbutton(bar,text='Facade on wall',variable=self.volume_apply_enabled,command=self.update_volume_facade).pack(side='left',padx=4)
  ttk.Checkbutton(bar,text='Match facade dimensions',variable=self.volume_sync_enabled,command=self.update_volume_facade).pack(side='left',padx=4)
  ttk.Label(bar,text='Filtering (rotations):').pack(side='left',padx=(8,2))
  combo=ttk.Combobox(bar,textvariable=self.volume_filter,values=('Pixels','Soft','Detailed'),state='readonly',width=11)
  combo.pack(side='left')
  combo.bind('<<ComboboxSelected>>',self._manual_filter_selected)
  ttk.Checkbutton(bar,text='Auto',variable=self.volume_auto_filter,
                  command=self._refresh_auto_filter).pack(side='left',padx=4)
  ttk.Button(bar,text='Refresh facade',command=self.update_volume_facade).pack(side='right',padx=4)
  self._refresh_auto_filter()

 def _manual_filter_selected(self,event=None):
  # Any manual selection takes precedence until Auto is turned on again.
  self.volume_auto_filter.set(False)
  self.update_volume_facade()

 def _refresh_auto_filter(self):
  if self.volume_auto_filter.get():
   angle=self.volume_app.angle % 360
   # Standard iso and exact screen-horizontal walls need no blur.
   # All other 15-degree steps use gentle filtering by default.
   mode='Pixels' if angle%45==0 else 'Soft'
   self.volume_filter.set(mode)
  self.update_volume_facade()

 def _on_tab_changed(self,event=None):
  if self.tabs.index(self.tabs.select())==2: self.update_volume_facade()

 def update_volume_facade(self):
  if not hasattr(self,'volume_app'):return
  vol=self.volume_app
  if not self.volume_apply_enabled.get() or self.facade is None:
   vol.facade_texture=None;vol.facade_source=None;vol.facade_front=None;vol.schedule();return
  # Preserve the isometric master; no resampled intermediate.
  # Pass both hand-drawn master facades directly without any pre-resampling.
  vol.facade_source=self.facade.copy()
  vol.facade_front=self.facade_front.copy() if self.facade_front is not None else None
  vol.facade_texture=vol.facade_source
  vol.facade_filter=self.volume_filter.get()
  if self.volume_sync_enabled.get() and vol.blocks:
   b=vol.blocks[0]
   b.w=max(12,self.facade.width)
   # No bounding-box guesses: use the architectural stack height.
   # Round to the nearest whole world unit (two screen pixels), based
   # on painted geometry rather than the transparent image bounding box.
   master_h=max(1,getattr(self,'facade_wall_height_px',0) or
                (self.facade.height-(self.facade.width-1)/2))
   b.h=max(10,round(master_h/2))
   vol.refresh_list()
  vol.schedule()

 def show_facade(self):
  if self.facade is None:return
  preview=self.facade
  self.facade_photo,self.facade_scale,self.facade_origin=self.draw_image(self.facade_canvas,preview)
 def save_module(self):
  p=filedialog.asksaveasfilename(initialdir=str(OUT),initialfile='facade_module.png',defaultextension='.png',filetypes=[('PNG','*.png')],title='Save module')
  if not p:return
  self.module.save(p); Path(p).with_suffix('.json').write_text(json.dumps(self.module_data(),ensure_ascii=False,indent=2),encoding='utf-8')
  self.module_status.set('Module and editable settings saved.')
 def module_data(self):
  return {'version':19.0,'window_size':self.window_size.get(),'active_type':self.type_names[self.active_type],'independent_edit':self.independent_edit.get(),'module_size':list(self.module.size),'wall_color':self.wall_color,'components':{c:{'enabled':self.enabled[c],'asset':self.choice[c]['name'] if self.choice[c] else None,'offset':self.offset[c],'front_offset':self.front_offset[c],'color':self.component_colors[c],'color_mode':self.component_modes[c],'color_strength':self.component_strength[c]} for c in ORDER}}
 def _encode_state(self,state):
  data=copy.deepcopy({k:v for k,v in state.items() if k!='choice'})
  data['choice']={cat:(item.get('name') if item else None) for cat,item in state['choice'].items()}
  return data

 def _decode_state(self,data):
  base=self._capture_type_state()
  for key in ('wall_color','enabled','offset','front_offset','component_colors','component_modes','component_strength','extra_height','window_size'):
   if key in data:base[key]=copy.deepcopy(data[key])
  for cat,name in data.get('choice',{}).items():
   if cat not in ORDER:continue
   candidates=self.assets.get(cat,[])
   base['choice'][cat]=next((a for a in candidates if a['name']==name),None)
  return base

 def save_project(self):
  if not getattr(self,'module_applied',False):
   messagebox.showinfo('No module','Click Apply Module first.');return
  p=filedialog.asksaveasfilename(initialdir=str(OUT),initialfile='facade_project.json',defaultextension='.json',filetypes=[('JSON project','*.json')],title='Save facade project')
  if not p:return
  self.type_states[self.active_type]=self._capture_type_state()
  assembly={'facade_width':self.facade_width.get(),'floors':self.floors.get(),
            'floor_counts':[v.get() for v in self.floor_counts],
            'floor_gaps':[v.get() for v in self.floor_gap_vars],
            'rust_first':self.rust_first.get(),'rust_second':self.rust_second.get(),
            'rust_count':self.rust_count.get(),'first_foundation':self.first_foundation.get(),
            'foundation_name':self.foundation_choice.get('name') if self.foundation_choice else None,
            'foundation_color':self.foundation_color,'foundation_color_enabled':self.foundation_color_enabled.get(),
            'foundation_x':self.foundation_x.get(),'foundation_y':self.foundation_y.get()}
  data={'format':'sc3k-architecture-facade','version':0.8,'assembly':assembly,
        'active_type':self.active_type,'independent_edit':self.independent_edit.get(),
        'types':{str(i):self._encode_state(self.type_states.get(i,self._capture_type_state())) for i in range(4)}}
  try:
   Path(p).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
   self.facade_status.set('Project saved: '+p)
  except Exception as exc:messagebox.showerror('Save error',str(exc))

 def load_project(self):
  p=filedialog.askopenfilename(initialdir=str(OUT),filetypes=[('JSON project','*.json')],title='Open facade project')
  if not p:return
  try:
   data=json.loads(Path(p).read_text(encoding='utf-8'))
   if data.get('format')!='sc3k-architecture-facade':
    raise ValueError('This is not an Architecture Builder project. The old incomplete JSON cannot be restored reliably.')
   a=data['assembly']
   states={int(i):self._decode_state(st) for i,st in data['types'].items()}
   self.facade_width.set(int(a['facade_width']));self.floors.set(int(a['floors']))
   for i,v in enumerate(a['floor_counts'][:4]):self.floor_counts[i].set(int(v))
   for i,v in enumerate(a['floor_gaps'][:4]):self.floor_gap_vars[i].set(int(v))
   self.rust_first.set(bool(a['rust_first']));self.rust_second.set(bool(a['rust_second']))
   self.rust_count.set(int(a['rust_count']))
   self.first_foundation.set(bool(a['first_foundation']))
   self.foundation_color=a['foundation_color']
   self.foundation_color_enabled.set(bool(a['foundation_color_enabled']))
   self.foundation_x.set(int(a['foundation_x']));self.foundation_y.set(int(a['foundation_y']))
   foundation_name=a.get('foundation_name')
   self.foundation_choice=next((item for item in self.assets['foundation'] if item['name']==foundation_name),None)
   self.independent_edit.set(bool(data.get('independent_edit',False)))
   self.type_states=states
   self.active_type=max(0,min(3,int(data.get('active_type',0))))
   self.type_selector.current(self.active_type)
   self._restore_type_state(states[self.active_type])
   self.compose_module()
   self.apply_module()
   self.render_facade()
   self.facade_status.set('Project loaded: '+p)
  except Exception as exc:messagebox.showerror('Could not open project',str(exc))
 def export_facade(self):
  if self.facade is None: self.render_facade()
  if self.facade is None:return
  p=filedialog.asksaveasfilename(initialdir=str(OUT),initialfile='facade.png',defaultextension='.png',filetypes=[('PNG','*.png')],title='Export facade')
  if p:self.facade.save(p); self.facade_status.set('PNG exported: '+p)
if __name__ == '__main__':
 root=tk.Tk(); app=App(root); root.mainloop()
