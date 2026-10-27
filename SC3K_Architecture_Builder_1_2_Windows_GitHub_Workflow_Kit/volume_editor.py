#!/usr/bin/env python3
"""SC3K Volume Editor v13.5: coherent ground edges and analytic wall shadows."""
import json, math, tkinter as tk
from pathlib import Path
from dataclasses import dataclass,asdict
from tkinter import ttk, filedialog, messagebox
from PIL import Image,ImageDraw,ImageTk

BG="#f3f3f1"
PREVIEW="#777a7d"
WALL_LIGHT=(226,225,222)
WALL_DARK=(185,186,183)
ROOF_LIGHT=(198,138,115)
ROOF_DARK=(163,101,79)
ROOF_FLAT=(221,173,148)
EDGE=(112,112,110)
CAST_SHADOW=(91,94,98)
ROOF_PALETTE_PATH=Path(__file__).resolve().parent/"library"/"palette_roof.png"

@dataclass
class Block:
    name:str="Block"
    x:int=0
    y:int=0
    w:int=48
    d:int=24
    h:int=36
    rise:int=12
    axis:str="X"
    roof_type:str="Gable"
    ridge:int=20
    overhang:int=1
    thickness:int=1
    eave_drop:int=0
    thickness_enabled:bool=False
    extended_gable:bool=True

    def roof_bounds(self):
        # Isometric horizontal coordinates: 1 world unit projects to 2
        # screen pixels over a symmetric eave extension. Half-units give
        # consistent 1-pixel increments for successive spinbox values.
        e=self.overhang/2
        return (self.x-e,self.y-e,self.x+self.w+e,self.y+self.d+e)

    def roof_contains(self,x,y):
        x0,y0,x1,y1=self.roof_bounds()
        return x0-1e-8<=x<=x1+1e-8 and y0-1e-8<=y<=y1+1e-8

    def planes(self, disabled_hips=()):
        """Roof as the lower envelope of 2 or 4 planes.

        The ridge is anchored to the BODY and always stays at h+rise.
        All slopes terminate at the same eave height, h-eave_drop,
        at the OUTER roof boundary (including lateral overhang).
        Thus adjusting overhang/drop/ridge never sends one facet
        arbitrarily beneath the others at the edge.
        """
        x0,y0,x1,y1=self.roof_bounds()
        high=self.h+self.rise
        low=self.h-self.eave_drop
        span=high-low
        midx=self.x+self.w/2
        midy=self.y+self.d/2
        if self.axis=="X":
            sy0=span/max(0.5,midy-y0)
            sy1=span/max(0.5,y1-midy)
            planes=[(0, sy0, high-sy0*midy),
                    (0,-sy1, high+sy1*midy)]
            if self.roof_type=="Hip":
                ridge=max(0,min(self.ridge,self.w))
                left=midx-ridge/2
                right=midx+ridge/2
                sx0=span/max(0.5,left-x0)
                sx1=span/max(0.5,x1-right)
                if "start" not in disabled_hips:
                    planes.append((sx0,0,high-sx0*left))
                if "end" not in disabled_hips:
                    planes.append((-sx1,0,high+sx1*right))
        else:
            sx0=span/max(0.5,midx-x0)
            sx1=span/max(0.5,x1-midx)
            planes=[( sx0,0,high-sx0*midx),
                    (-sx1,0,high+sx1*midx)]
            if self.roof_type=="Hip":
                ridge=max(0,min(self.ridge,self.d))
                near=midy-ridge/2
                far=midy+ridge/2
                sy0=span/max(0.5,near-y0)
                sy1=span/max(0.5,y1-far)
                if "start" not in disabled_hips:
                    planes.append((0,sy0,high-sy0*near))
                if "end" not in disabled_hips:
                    planes.append((0,-sy1,high+sy1*far))
        return planes

    def height_at(self,x,y,disabled_hips=()):
        if not self.roof_contains(x,y):
            return None
        return min(a*x+b*y+c for a,b,c in self.planes(disabled_hips))

    def contains(self,x,y):
        return self.x<=x<self.x+self.w and self.y<=y<self.y+self.d

def iso(p):
    x,y,z=p
    return x-y,0.5*(x+y)-2*z

def rotate(p,angle,cx,cy):
    x,y,z=p
    x-=cx;y-=cy
    a=math.radians(angle)
    return x*math.cos(a)-y*math.sin(a),x*math.sin(a)+y*math.cos(a),z

def visible_color(normal,roof=False):
    # SimCity-style light/dark relative to the screen, not the building.
    nx,ny,nz=normal
    if not roof and abs(nx-ny)<1e-7 and abs(nz)<1e-7:
        return tuple(round((light+dark)/2) for light,dark in zip(WALL_LIGHT,WALL_DARK))
    return (ROOF_LIGHT if nx-ny<0 else ROOF_DARK) if roof else (
        WALL_LIGHT if nx-ny<0 else WALL_DARK)

def connected_hip_ends(blocks):
    """Remove a hip at an end of a wing embedded in another building.

    A roof branch that joins the middle of a perpendicular main block
    should have two longitudinal slopes and only its OUTER end hip.
    In a through-crossing, neither end is inside the other footprint,
    so both hips remain. No manual switch is required.
    """
    disabled={id(b):set() for b in blocks}
    for wing in blocks:
        if wing.roof_type!="Hip":
            continue
        for main in blocks:
            if main is wing or main.axis==wing.axis:
                continue
            if wing.axis=="Y":
                # Require genuine overlap across the wing's width.
                overlap=min(wing.x+wing.w,main.x+main.w)-max(wing.x,main.x)
                if overlap<min(wing.w,main.w)*0.35:
                    continue
                for end,y in (("start",wing.y),("end",wing.y+wing.d)):
                    # Embedded end must be in the main's INTERIOR,
                    # not just touching its wall.
                    if main.y+0.01<y<main.y+main.d-0.01:
                        disabled[id(wing)].add(end)
            else:
                overlap=min(wing.y+wing.d,main.y+main.d)-max(wing.y,main.y)
                if overlap<min(wing.d,main.d)*0.35:
                    continue
                for end,x in (("start",wing.x),("end",wing.x+wing.w)):
                    if main.x+0.01<x<main.x+main.w-0.01:
                        disabled[id(wing)].add(end)
    return disabled

def scene_mesh(blocks,step=4):
    """Build the exact upper envelope of planar gable/hip roof facets.

    Roof pieces are clipped by analytical plane intersections, not
    interpolated through a coarse height grid. Wall solids use the original
    building footprint; roof eaves can extend beyond it.
    """
    if not blocks:return []

    def plane_value(plane,x,y):
        a,b,c=plane
        return a*x+b*y+c

    def clip(poly,plane,keep_positive=True):
        """Sutherland-Hodgman clip of a 2D polygon by a linear inequality."""
        if not poly:return []
        a,b,c=plane
        def value(p):
            v=a*p[0]+b*p[1]+c
            return v if keep_positive else -v
        result=[]
        prev=poly[-1];pv=value(prev)
        for cur in poly:
            cv=value(cur)
            inside=cv>=-1e-9
            was_inside=pv>=-1e-9
            if inside!=was_inside:
                ratio=pv/(pv-cv)
                result.append((prev[0]+ratio*(cur[0]-prev[0]),
                               prev[1]+ratio*(cur[1]-prev[1])))
            if inside:result.append(cur)
            prev,pv=cur,cv
        return result

    def subtract_planes(p,q):
        return tuple(a-b for a,b in zip(p,q))

    def add_poly(mesh,poly,plane,kind):
        if len(poly)<3:return
        a,b,c=plane
        pts=[(x,y,a*x+b*y+c) for x,y in poly]
        normal=(-a,-b,1) if kind=="roof" else (0,0,1)
        for k in range(1,len(pts)-1):
            mesh.append(((pts[0],pts[k],pts[k+1]),kind,normal))

    # Grid lines at every footprint and eave boundary, ridge centre, and
    # start/end of each hip ridge. Within a cell each roof facet is planar.
    xs=set();ys=set()
    for b in blocks:
        x0,y0,x1,y1=b.roof_bounds()
        xs.update((x0,x1,b.x,b.x+b.w,b.x+b.w/2))
        ys.update((y0,y1,b.y,b.y+b.d,b.y+b.d/2))
        if b.axis=="X":
            xs.update((b.x+(b.w-b.ridge)/2,b.x+(b.w+b.ridge)/2))
        else:
            ys.update((b.y+(b.d-b.ridge)/2,b.y+(b.d+b.ridge)/2))
    xmin=min(xs);xmax=max(xs);ymin=min(ys);ymax=max(ys)
    xs.update(xmin+i*step for i in range(math.ceil((xmax-xmin)/step)+1) if xmin+i*step<xmax)
    ys.update(ymin+i*step for i in range(math.ceil((ymax-ymin)/step)+1) if ymin+i*step<ymax)
    xs=sorted(xs);ys=sorted(ys)
    if (len(xs)-1)*(len(ys)-1)>16000:
        raise ValueError("Scene too large for exact roof joins")

    mesh=[]
    suppressed_hips=connected_hip_ends(blocks)
    cached_planes={id(b):b.planes(suppressed_hips[id(b)]) for b in blocks}
    def footprint_cover(b,x,y):
        return b.x-1e-8<=x<=b.x+b.w+1e-8 and b.y-1e-8<=y<=b.y+b.d+1e-8

    def roof_height(group,x,y):
        return max(b.height_at(x,y) for b in group)

    for i in range(len(xs)-1):
        x0,x1=xs[i:i+2]
        if x1-x0<1e-7:continue
        for j in range(len(ys)-1):
            y0,y1=ys[j:j+2]
            if y1-y0<1e-7:continue
            mx=(x0+x1)/2;my=(y0+y1)/2
            active=[b for b in blocks if b.roof_contains(mx,my)]
            if not active:continue
            square=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
            # Exact facet arrangement: for each candidate facet, first
            # choose the MIN facet of its own roof; then choose the MAX
            # roof of all overlapping blocks. This forms hips and valleys.
            for current in active:
                planes=cached_planes[id(current)]
                for plane in planes:
                    poly=square[:]
                    for own in planes:
                        if own is plane:continue
                        poly=clip(poly,subtract_planes(own,plane))
                        if len(poly)<3:break
                    if len(poly)<3:continue
                    regions=[poly]
                    for other in active:
                        if other is current:continue
                        new_regions=[]
                        others=cached_planes[id(other)]
                        for region in regions:
                            for other_plane in others:
                                part=region
                                for p in others:
                                    if p is other_plane:continue
                                    part=clip(part,subtract_planes(p,other_plane))
                                    if len(part)<3:break
                                if len(part)<3:continue
                                part=clip(part,subtract_planes(plane,other_plane))
                                if len(part)>=3:new_regions.append(part)
                        regions=new_regions
                        if not regions:break
                    for region in regions:
                        add_poly(mesh,region,plane,"roof")

            # External walls stop at wall height (under the eave).
            # Determine which walls are exposed using neighbour probes.
            covered=[b for b in blocks if b.contains(mx,my)]
            if not covered:continue
            for di,dj,p0,p1,normal in (
                (-1,0,(x0,y0),(x0,y1),(-1,0,0)),
                (1,0,(x1,y0),(x1,y1),(1,0,0)),
                (0,-1,(x0,y0),(x1,y0),(0,-1,0)),
                (0,1,(x0,y1),(x1,y1),(0,1,0)),
            ):
                eps=0.0001
                bx=(p0[0]+p1[0])/2+di*eps
                by=(p0[1]+p1[1])/2+dj*eps
                neighbours=[b for b in blocks if b.contains(bx,by)]
                top=max(b.h for b in covered)
                bottom=max((b.h for b in neighbours),default=0)
                if top<=bottom:continue
                q0=(p0[0],p0[1],bottom);q1=(p1[0],p1[1],bottom)
                # Continue external walls up to the UNDERSIDE of the
                # roof at the true building boundary. A widened eave
                # otherwise leaves a spurious background-coloured gap.
                def wall_top(point):
                    heights=[b.height_at(*point,suppressed_hips[id(b)])
                             for b in covered if b.roof_contains(*point)]
                    return max([z for z in heights if z is not None],default=top)
                r0=(p0[0],p0[1],wall_top(p0))
                r1=(p1[0],p1[1],wall_top(p1))
                mesh.append(((q0,q1,r1),"wall",normal))
                mesh.append(((q0,r1,r0),"wall",normal))

    # Triangular gable infill: the vertical triangle between the wall
    # top and the roof ridge at each end of a gable roof. Without these
    # pieces, gable roofs have holes when viewed from their ends.
    for b in blocks:
        if b.roof_type!="Gable":
            continue
        x0,y0,x1,y1=b.roof_bounds()
        # The gable end wall may either extend to the eave edge (legacy)
        # or stop at the actual body end, leaving visible roof overhang.
        for side in (0,1):
            if b.axis=="X":
                fixed=(x0 if side==0 else x1) if b.extended_gable else (b.x if side==0 else b.x+b.w)
                ystart,yend=(y0,y1) if b.extended_gable else (b.y,b.y+b.d)
                p0=(fixed,ystart);p1=(fixed,yend)
                pm=(fixed,(ystart+yend)/2)
                normal=(-1,0,0) if side==0 else (1,0,0)
            else:
                fixed=(y0 if side==0 else y1) if b.extended_gable else (b.y if side==0 else b.y+b.d)
                xstart,xend=(x0,x1) if b.extended_gable else (b.x,b.x+b.w)
                p0=(xstart,fixed);p1=(xend,fixed)
                pm=((xstart+xend)/2,fixed)
                normal=(0,-1,0) if side==0 else (0,1,0)
            midx,midy=pm
            z0=b.height_at(*p0)
            z1=b.height_at(*p1)
            zm=b.height_at(*pm)
            baseline=min(z0,z1)
            # Gable fill can be occluded by a second roof through Z-buffer.
            if zm>baseline+1e-6:
                mesh.append((((p0[0],p0[1],baseline),
                              (p1[0],p1[1],baseline),
                              (pm[0],pm[1],zm)),"wall",normal))

    # Roof thickness (fascia) for a gable roof: build it as real 3D strips
    # under the visible roof edge, not as a later 2D overlay. This makes the
    # trim follow the roof boundary pixel-for-pixel and removes gaps at the
    # ridge and eaves.
    for b in blocks:
        if b.roof_type!="Gable" or not b.thickness_enabled or b.thickness<=0:
            continue
        dz=b.thickness*0.5  # 0.5 world-z -> 1 screen pixel vertically
        eps=0.01
        x0,y0,x1,y1=b.roof_bounds()
        for side in (0,1):
            if b.axis=="X":
                fixed=x0 if side==0 else x1
                a=(fixed,y0)
                m=(fixed,(y0+y1)/2)
                c=(fixed,y1)
                shift=(-eps,0) if side==0 else (eps,0)
                normal=(-1,0,0) if side==0 else (1,0,0)
            else:
                fixed=y0 if side==0 else y1
                a=(x0,fixed)
                m=((x0+x1)/2,fixed)
                c=(x1,fixed)
                shift=(0,-eps) if side==0 else (0,eps)
                normal=(0,-1,0) if side==0 else (0,1,0)
            az=b.height_at(*a)
            mz=b.height_at(*m)
            cz=b.height_at(*c)
            top=[(a[0]+shift[0],a[1]+shift[1],az),
                 (m[0]+shift[0],m[1]+shift[1],mz),
                 (c[0]+shift[0],c[1]+shift[1],cz)]
            bot=[(top[0][0],top[0][1],az-dz),
                 (top[1][0],top[1][1],mz-dz),
                 (top[2][0],top[2][1],cz-dz)]
            # quad a-m and quad m-c
            mesh.append(((top[0],top[1],bot[1]),"fascia",normal))
            mesh.append(((top[0],bot[1],bot[0]),"fascia",normal))
            mesh.append(((top[1],top[2],bot[2]),"fascia",normal))
            mesh.append(((top[1],bot[2],bot[1]),"fascia",normal))
    return mesh

def render_scene(blocks,angle=0,step=2,cast_shadow=False,facade_texture=None,facade_block=0,facade_source=None,facade_filter="Pixels",facade_front=None,roof_color=None,roof_lines=False,roof_spacing=7,roof_opacity=30,roof_softness=0.65):
    """Software z-buffer; shared roof is a solid union envelope."""
    if not blocks:
        return Image.new("RGB",(400,300),PREVIEW)
    mesh=scene_mesh(blocks,step)
    cx=(min(b.x for b in blocks)+max(b.x+b.w for b in blocks))/2
    cy=(min(b.y for b in blocks)+max(b.y+b.d for b in blocks))/2
    # IMPORTANT: shading is calculated AFTER rotation, in camera/screen space.
    # v11 calculated the colour BEFORE rotation, so two dark sides could face
    # the viewer after a 90-degree turn.
    a=math.radians(angle)
    ca,sa=math.cos(a),math.sin(a)
    transformed=[]
    shadow_triangles=[]
    for tri,kind,normal in mesh:
        nx,ny,nz=normal
        rotated_normal=(nx*ca-ny*sa,nx*sa+ny*ca,nz)
        if kind=="fascia":
            color=(175,110,85)
        else:
            color=visible_color(rotated_normal,roof=(kind in ("roof","underside")))
        if kind=="roof" and roof_color is not None:
            # Keep the game's pronounced flat light/shadow distinction.
            factor=1.0 if rotated_normal[0]-rotated_normal[1]<0 else 0.82
            color=tuple(max(0,min(255,round(c*factor))) for c in roof_color)
        rotated=[rotate(p,angle,cx,cy) for p in tri]
        transformed.append((rotated,color,kind,rotated_normal))
        if cast_shadow:
            # Game-art convention: every elevated point shifts strictly right
            # by its on-screen height (2 pixels per world z unit).
            shadow_triangles.append([(iso((x,y,0))[0]+2*z,iso((x,y,0))[1]) for x,y,z in rotated])
    coords=[iso(p) for tri,_,_,_ in transformed for p in tri]
    if cast_shadow:
        coords.extend(pt for tri in shadow_triangles for pt in tri)
    minx=math.floor(min(x for x,y in coords));maxx=math.ceil(max(x for x,y in coords))
    miny=math.floor(min(y for x,y in coords));maxy=math.ceil(max(y for x,y in coords))
    pad=12
    width=int(maxx-minx)+2*pad
    height=int(maxy-miny)+2*pad
    if width*height>6_000_000:
        raise ValueError("Scene image is too large")
    image=Image.new("RGB",(width,height),PREVIEW)
    if cast_shadow:
        # Rasterize a single union mask, rather than painting individual
        # shadow triangles over the building. All shadow edges use the same
        # pixel-centre convention as the solid rasterizer below.
        shadow_mask=Image.new("L",(width,height),0)
        shadow_draw=ImageDraw.Draw(shadow_mask)
        for tri in shadow_triangles:
            points=[(x-minx+pad,y-miny+pad) for x,y in tri]
            shadow_draw.polygon(points,fill=255)
        # The wall rasterizer itself occludes the ground shadow, using its
        # exact pixel-centre silhouette. Do not dilate a separate footprint:
        # that creates a grey no-shadow halo outside the rendered walls.
        image.paste(CAST_SHADOW,(0,0),shadow_mask)
    pix=image.load()
    depth=[-float("inf")]*(width*height)
    # Shadow rays run in rotated world coordinates. Screen-right is
    # (-0.5,+0.5) on the ground; one unit of screen distance also raises
    # the ray by 0.5 world units. Test actual solid intersections rather
    # than sampling rounded columns (which caused v13.2's stripes).
    ray_dx,ray_dy,ray_dz=-0.5,0.5,0.5
    max_ray=2*max(b.h+b.rise for b in blocks)+4
    local_blocks=[]
    for b in blocks:
        # Bounds of each block in rotated coordinates.
        corners=[rotate((x,y,0),angle,cx,cy) for x in (b.x,b.x+b.w)
                 for y in (b.y,b.y+b.d)]
        local_blocks.append((b,corners))

    # The wall-shadow boundary is a true intersection of the light ray
    # with the solid, NOT a decision sampled at five arbitrary positions.
    # A block's roof is the minimum of its roof planes, therefore the ray
    # is under the roof precisely when it satisfies ALL plane inequalities.
    # Clipping one continuous interval removes the broken wall-shadow edge.
    planes_by_block={id(b):b.planes() for b in blocks}

    def wall_in_shadow(pos,normal):
        nx,ny,_=normal
        if nx*ray_dx+ny*ray_dy<=1e-7:
            return False
        rx,ry,rz=pos
        ox=rx*ca+ry*sa+cx
        oy=-rx*sa+ry*ca+cy
        dx=ray_dx*ca+ray_dy*sa
        dy=-ray_dx*sa+ray_dy*ca
        eps=1e-6
        for b,_ in local_blocks:
            # Intersect ray with the BODY footprint, not the overhang.
            # Open interval avoids false self-shadow at the wall surface.
            lo,hi=0.025,float(max_ray)
            for value,direction,start,stop in ((ox,dx,b.x,b.x+b.w),
                                               (oy,dy,b.y,b.y+b.d)):
                if abs(direction)<1e-12:
                    if not (start+eps<value<stop-eps):
                        hi=-1
                        break
                else:
                    t0=(start-value)/direction
                    t1=(stop-value)/direction
                    lo=max(lo,min(t0,t1)+eps)
                    hi=min(hi,max(t0,t1)-eps)
            if hi<=lo:
                continue
            # z > 0, and z < each sloped roof plane a*x+b*y+c.
            if rz+ray_dz*hi<=eps:
                continue
            lo=max(lo,(eps-rz)/ray_dz)
            for a,beta,c in planes_by_block[id(b)]:
                # f(t) = roof_plane(t) - ray_height(t) > 0
                f0=a*ox+beta*oy+c-rz
                slope=a*dx+beta*dy-ray_dz
                if abs(slope)<1e-12:
                    if f0<=eps:
                        hi=-1
                        break
                elif slope>0:
                    lo=max(lo,(eps-f0)/slope)
                else:
                    hi=min(hi,(eps-f0)/slope)
                if hi<=lo:
                    break
            if hi>lo+eps:
                return True
        return False

    # Direct pixel transfer at canonical iso views: no de-shearing,
    # re-projection, interpolation, or color correction of the original
    # facade artwork.  At 270° the visible +Y wall is the mirror image of
    # the default isometric wall, so use a horizontally flipped ISO master
    # instead of re-sampling the facade through the generic affine path.
    rotation=angle%360
    exact_facade = None
    exact_origin_mode = None
    if facade_source is not None:
        if rotation == 0:
            exact_facade = facade_source.convert("RGBA")
            exact_origin_mode = "wall_top"
        elif rotation == 270:
            exact_facade = facade_source.convert("RGBA").transpose(Image.FLIP_LEFT_RIGHT)
            exact_origin_mode = "bbox_top"
    exact_pixels = exact_facade.load() if exact_facade is not None else None
    # ISO strips can have transparent margins at their diagonal bottom edge.
    # The wall geometry and facade use independent pixel rounding, leaving a
    # narrow bare WALL_LIGHT strip. Use the dominant *actual facade wall*
    # color only where there is no source pixel; do not stretch windows.
    exact_wall_fill = None
    if exact_facade is not None:
        from collections import Counter
        sample = Counter()
        for sy in range(0, exact_facade.height, 2):
            for sx in range(0, exact_facade.width, 2):
                rgba = exact_pixels[sx, sy]
                if rgba[3] == 255:
                    sample[rgba[:3]] += 1
        if sample:
            exact_wall_fill = sample.most_common(1)[0][0]
    # The original isometric master is sampled directly at every rotation.
    # Never create or sample a de-sheared intermediate bitmap.
    texture_pixels=facade_source.convert("RGBA").load() if facade_source is not None else None
    texture_block=blocks[facade_block] if (texture_pixels is not None or exact_pixels is not None) and 0 <= facade_block < len(blocks) else None
    # ISO (0°) and FRONT (315°) are two independent hand-drawn masters.
    # Always keep ISO at the canonical angles; use FRONT for intermediate
    # rotations where the +Y facade approaches a head-on (horizontal) view.
    # Both masters are sampled directly, never transformed into each other.
    def angular_distance(a,b):
        return abs((a-b+180)%360-180)
    # All non-canonical rotations use hand-drawn FRONT art; canonical
    # quarter turns retain ISO. No partial selection by angular distance.
    front_active=(facade_front is not None and rotation%90 != 0)
    if front_active:
        facade_source=facade_front
        texture_pixels=facade_front.convert('RGBA').load()
    master=facade_source.convert("RGBA") if facade_source is not None else None
    # The height of the RGBA bounding rectangle is NOT the physical wall
    # height: the isometric image includes an uneven staircase at its bottom.
    # Use exactly the same alpha-envelope measure as Facade Builder's height
    # synchronisation.  The previous (height - width/2) approximation was
    # several pixels too large, making 90/180/270-degree walls sample empty
    # rows and leaving a bare strip at the bottom.
    straight_height=1.0
    if master is not None:
        if front_active:
            straight_height=float(master.height)
        else:
            from statistics import median
            alpha=master.getchannel('A')
            ap=alpha.load()
            bottoms=[]
            for sx in range(master.width):
                for sy in range(master.height-1,-1,-1):
                    if ap[sx,sy]:
                        bottoms.append(sy+1-sx*0.5)
                        break
            straight_height=max(1.0,float(median(bottoms))) if bottoms else 1.0
    if texture_block is not None and exact_pixels is not None:
        b=texture_block
        if exact_origin_mode == "wall_top":
            # Pixel-coordinate origin of the top-left of the +Y wall.
            wall_origin=iso(rotate((b.x,b.y+b.d,b.h),angle,cx,cy))
            facade_sx=round(wall_origin[0]-minx+pad)
            facade_sy=round(wall_origin[1]-miny+pad)
        else:
            # Mirrored canonical view: align the flipped wall master to the
            # bounding box of the visible wall footprint.
            wall_pts=[iso(rotate(p,angle,cx,cy)) for p in
                      ((b.x,b.y+b.d,0),(b.x+b.w,b.y+b.d,0),
                       (b.x+b.w,b.y+b.d,b.h),(b.x,b.y+b.d,b.h))]
            facade_sx=round(min(p[0] for p in wall_pts)-minx+pad)
            facade_sy=round(min(p[1] for p in wall_pts)-miny+pad)


    def triangle(pts,color,kind,world_pts,normal):
        # A plane's height gradient gives the downhill direction in XY.
        # Constant stripes run ALONG this downhill direction. Compute the
        # cross-slope coordinate in original world space, so subdivisions,
        # camera rotation and pitch changes never reset the pattern.
        roof_cross=None
        if kind=="roof" and roof_lines:
            rp=[(x*ca+y*sa+cx,-x*sa+y*ca+cy,z) for x,y,z in world_pts]
            dx1=rp[1][0]-rp[0][0];dy1=rp[1][1]-rp[0][1];dz1=rp[1][2]-rp[0][2]
            dx2=rp[2][0]-rp[0][0];dy2=rp[2][1]-rp[0][1];dz2=rp[2][2]-rp[0][2]
            denom=dx1*dy2-dx2*dy1
            if abs(denom)>1e-8:
                gx=(dz1*dy2-dz2*dy1)/denom
                gy=(dx1*dz2-dx2*dz1)/denom
                gl=math.hypot(gx,gy)
                if gl>1e-8:
                    roof_cross=(-gy/gl,gx/gl)

        (x0,y0,z0),(x1,y1,z1),(x2,y2,z2)=pts
        det=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
        if abs(det)<1e-9:return
        xstart=max(0,math.floor(min(x0,x1,x2)))
        xend=min(width-1,math.ceil(max(x0,x1,x2)))
        ystart=max(0,math.floor(min(y0,y1,y2)))
        yend=min(height-1,math.ceil(max(y0,y1,y2)))
        for yy in range(ystart,yend+1):
            py=yy+0.5
            for xx in range(xstart,xend+1):
                px=xx+0.5
                u=((px-x0)*(y2-y0)-(x2-x0)*(py-y0))/det
                v=((x1-x0)*(py-y0)-(px-x0)*(y1-y0))/det
                if u< -1e-8 or v< -1e-8 or u+v>1+1e-8:continue
                z=z0+u*(z1-z0)+v*(z2-z0)
                idx=yy*width+xx
                if z>depth[idx]+1e-8:
                    depth[idx]=z
                    if cast_shadow and kind=="wall":
                        # Recover the 3D receiver position from the same
                        # barycentric coordinates used by the z-buffer.
                        p0,p1,p2=world_pts
                        pos=(p0[0]+u*(p1[0]-p0[0])+v*(p2[0]-p0[0]),
                             p0[1]+u*(p1[1]-p0[1])+v*(p2[1]-p0[1]),
                             p0[2]+u*(p1[2]-p0[2])+v*(p2[2]-p0[2]))
                        if wall_in_shadow(pos,normal):
                            # Keep wall shadows substantially lighter than
                            # ground shadows and preserve original own shade.
                            pix[xx,yy]=tuple(max(0,c-18) for c in color)
                        else:
                            pix[xx,yy]=color
                    else:
                        pix[xx,yy]=color
                    if roof_cross is not None:
                        # Interpolate the world-space receiver from its actual
                        # roof triangle. All adjoining clipped roof triangles
                        # use a common phase, preventing texture seams.
                        rp0,rp1,rp2=world_pts
                        rxx=rp0[0]+u*(rp1[0]-rp0[0])+v*(rp2[0]-rp0[0])
                        ryy=rp0[1]+u*(rp1[1]-rp0[1])+v*(rp2[1]-rp0[1])
                        wx=rxx*ca+ryy*sa+cx
                        wy=-rxx*sa+ryy*ca+cy
                        phase=wx*roof_cross[0]+wy*roof_cross[1]
                        gap=max(2.0,float(roof_spacing))
                        dist=abs((phase+0.5*gap)%gap-0.5*gap)
                        # Dark one-pixel grooves with a narrow soft shoulder.
                        # The edges remain confined to the roof z-buffer.
                        core=0.42
                        blur=max(0.02,float(roof_softness))
                        weight=max(0.0,min(1.0,(core+blur-dist)/blur))
                        amount=max(0.0,min(0.85,float(roof_opacity)/100))*weight
                        if amount>0:
                            pix[xx,yy]=tuple(max(0,round(c*(1-amount))) for c in pix[xx,yy])
                    # Integrated façade: sample the finished 2D facade on the
                    # +Y wall of the main block, using original world coords.
                    # This occurs inside the depth-tested rasterization, so roofs
                    # and nearer surfaces correctly occlude decorations.
                    if texture_block is not None and kind == "wall":
                        wx=world_pts[0][0]+u*(world_pts[1][0]-world_pts[0][0])+v*(world_pts[2][0]-world_pts[0][0])
                        wy=world_pts[0][1]+u*(world_pts[1][1]-world_pts[0][1])+v*(world_pts[2][1]-world_pts[0][1])
                        wz=world_pts[0][2]+u*(world_pts[1][2]-world_pts[0][2])+v*(world_pts[2][2]-world_pts[0][2])
                        original_x=wx*ca+wy*sa+cx
                        original_y=-wx*sa+wy*ca+cy
                        b=texture_block
                        if (abs(original_y-(b.y+b.d))<0.025 and
                            b.x-0.01<=original_x<=b.x+b.w+0.01 and
                            0<=wz<=b.h):
                            if exact_pixels is not None and facade_filter=="Pixels":
                                # The source canvas is ALREADY a 2:1 isometric
                                # wall. Copy identical integer pixels without
                                # UV interpolation, preserving all window shapes.
                                tx=xx-facade_sx
                                ty=yy-facade_sy
                                if 0<=tx<exact_facade.width and 0<=ty<exact_facade.height:
                                    fr,fg,fb,fa=exact_pixels[tx,ty]
                                    if fa:
                                        if fa==255:
                                            pix[xx,yy]=(fr,fg,fb)
                                        else:
                                            base=pix[xx,yy]
                                            pix[xx,yy]=tuple(round((fa*v+(255-fa)*base[i])/255) for i,v in enumerate((fr,fg,fb)))
                                    elif exact_wall_fill is not None:
                                        pix[xx,yy]=exact_wall_fill
                                elif exact_wall_fill is not None:
                                    pix[xx,yy]=exact_wall_fill
                                continue
                            # Direct inverse affine mapping into the original
                            # isometric art: the source uses a 2:1 sheared rail.
                            # A single mapping avoids column-by-column rounding
                            # in a de-sheared copy, responsible for visible jumps.
                            tx=(original_x-b.x)/b.w*master.width-0.5
                            if front_active:
                                ty=(b.h-wz)/b.h*master.height-0.5
                            else:
                                ty=(b.h-wz)/b.h*straight_height + (tx+0.5)*0.5-0.5
                            if facade_filter=="Pixels":
                                ix=min(master.width-1,max(0,int(round(tx))))
                                iy=min(master.height-1,max(0,int(round(ty))))
                                fr,fg,fb,fa=texture_pixels[ix,iy]
                            else:
                                # Filter only after rotation. Source is never enlarged.
                                # Bicubic uses the original pixel neighborhood, not
                                # a twice-upscaled intermediate texture.
                                def px_at(ix,iy):
                                    ix=max(0,min(master.width-1,ix))
                                    iy=max(0,min(master.height-1,iy))
                                    return texture_pixels[ix,iy]
                                def cubic(t):
                                    t=abs(t)
                                    if t<1:return 1.5*t*t*t-2.5*t*t+1
                                    if t<2:return -0.5*t*t*t+2.5*t*t-4*t+2
                                    return 0.
                                if facade_filter=="Detailed":
                                    ix=math.floor(tx);iy=math.floor(ty)
                                    accum=[0.]*4
                                    for j in range(-1,3):
                                        wy=cubic(ty-(iy+j))
                                        for i in range(-1,3):
                                            ww=wy*cubic(tx-(ix+i))
                                            pixel=px_at(ix+i,iy+j)
                                            for channel in range(4):accum[channel]+=pixel[channel]*ww
                                    fr,fg,fb,fa=(max(0,min(255,round(v))) for v in accum)
                                else:
                                    ix=math.floor(tx);iy=math.floor(ty)
                                    fx=tx-ix;fy=ty-iy
                                    a,bp,c,d=px_at(ix,iy),px_at(ix+1,iy),px_at(ix,iy+1),px_at(ix+1,iy+1)
                                    fr,fg,fb,fa=(round(a[k]*(1-fx)*(1-fy)+bp[k]*fx*(1-fy)+c[k]*(1-fx)*fy+d[k]*fx*fy) for k in range(4))
                            if fa:
                                # Preserve painterly highlights but follow the
                                # wall's own light/shade and cast shadow.
                                base=pix[xx,yy]
                                shade=max(0.3,min(1.15,sum(base)/max(1,sum(WALL_LIGHT))))
                                decorated=(min(255,round(fr*shade)),min(255,round(fg*shade)),min(255,round(fb*shade)))
                                pix[xx,yy]=tuple(round((fa*decorated[i]+(255-fa)*base[i])/255) for i in range(3))
    for pts,color,kind,normal in transformed:
        screen=[]
        for p in pts:
            x,y=iso(p)
            screen.append((x-minx+pad,y-miny+pad,
                           p[0]+p[1]+p[2]*0.5+(0.0004 if color==(113,69,56) else 0)))
        triangle(screen,color,kind,pts,normal)
    return image

class App:
    fields=(("X","x",-400,400),("Y","y",-400,400),
            ("Width","w",12,250),("Depth","d",12,250),
            ("Wall height","h",10,250),("Roof rise","rise",1,120),
            ("Ridge length","ridge",0,250),
            ("Overhang (px)","overhang",0,8),
            ("Roof thickness","thickness",0,2),
            ("Lower eave (vertical)","eave_drop",0,3))
    def __init__(self,root,embedded=False):
        self.root=root
        self.embedded=embedded
        self.facade_texture=None
        self.facade_source=None
        self.facade_front=None
        self.facade_filter="Pixels"
        self.facade_filter_auto=False
        if not embedded:
            root.title("SC3K Volume Editor v13.5 — 15° rotation + shadows")
            root.geometry("1170x760")
            root.minsize(850,600)
            root.configure(bg=BG)
        self.blocks=[]
        self.active=0
        self.angle=0
        self.after_id=None
        self.photo=None
        self.updating=False
        self.snap=tk.BooleanVar(value=False)
        self.cast_shadow=tk.BooleanVar(value=False)
        self.roof_color=(153,169,187)
        self.roof_lines=tk.BooleanVar(value=True)
        self.roof_spacing=tk.IntVar(value=7)
        self.roof_opacity=tk.IntVar(value=30)
        self.roof_softness=tk.DoubleVar(value=0.65)
        self.setup_style()
        self.build_ui()
        self.preset("I")

    def setup_style(self):
        style=ttk.Style()
        if "aqua" in style.theme_names():style.theme_use("aqua")
        else:
            style.theme_use("clam")
            style.configure("TButton",padding=(10,6))
        style.configure("TFrame",background=BG)
        style.configure("Panel.TFrame",background="white")
        style.configure("Panel.TLabel",background="white",foreground="#25272a")
        style.configure("Heading.TLabel",background="white",font=("Helvetica",12,"bold"))

    def build_ui(self):
        head=ttk.Frame(self.root,padding=(16,12))
        head.pack(fill="x")
        ttk.Label(head,text="SC3K Volume Editor — Roofs 1.2",font=("Helvetica",16,"bold")).pack(side="left")
        ttk.Button(head,text="PNG",command=self.export_png).pack(side="right",padx=4)
        ttk.Button(head,text="JSON",command=self.export_json).pack(side="right",padx=4)
        ttk.Button(head,text="Open JSON",command=self.import_json).pack(side="right",padx=4)
        body=ttk.Frame(self.root,padding=(16,0,16,16))
        body.pack(fill="both",expand=True)
        sidebar=tk.Canvas(body,bg="white",highlightthickness=0,width=316)
        sidebar.pack(side="left",fill="y",padx=(0,12))
        scroll=ttk.Scrollbar(body,orient="vertical",command=sidebar.yview)
        scroll.pack(side="left",fill="y",padx=(0,8))
        sidebar.configure(yscrollcommand=scroll.set)
        side=ttk.Frame(sidebar,style="Panel.TFrame",padding=12)
        sidebar.create_window((0,0),window=side,anchor="nw",width=300)
        side.bind("<Configure>",lambda e:sidebar.configure(scrollregion=sidebar.bbox("all")))
        def wheel(e):
            if e.delta:sidebar.yview_scroll(-1 if e.delta>0 else 1,"units")
        sidebar.bind("<MouseWheel>",wheel)
        side.bind("<MouseWheel>",wheel)
        ttk.Label(side,text="Building blocks",style="Heading.TLabel").pack(anchor="w",pady=(0,7))
        self.listbox=tk.Listbox(side,height=6,exportselection=False,activestyle="none",
                                font=("Helvetica",11),highlightthickness=0)
        self.listbox.pack(fill="x")
        self.listbox.bind("<<ListboxSelect>>",self.choose)
        buttons=ttk.Frame(side,style="Panel.TFrame")
        buttons.pack(fill="x",pady=8)
        ttk.Button(buttons,text="+ Block",command=self.add).pack(side="left",expand=True,fill="x")
        ttk.Button(buttons,text="Duplicate",command=self.duplicate).pack(side="left",expand=True,fill="x")
        ttk.Button(buttons,text="Delete",command=self.delete).pack(side="left",expand=True,fill="x")
        ttk.Label(side,text="Position and dimensions",style="Heading.TLabel").pack(anchor="w",pady=(8,5))
        self.vars={}
        for title,key,low,high in self.fields:
            row=ttk.Frame(side,style="Panel.TFrame")
            row.pack(fill="x",pady=3)
            ttk.Label(row,text=title,style="Panel.TLabel").pack(side="left")
            var=tk.IntVar(value=0)
            self.vars[key]=var
            spin=ttk.Spinbox(row,from_=low,to=high,width=9,textvariable=var,command=self.changed)
            spin.pack(side="right")
            spin.bind("<Return>",self.changed)
            spin.bind("<FocusOut>",self.changed)
        row=ttk.Frame(side,style="Panel.TFrame")
        row.pack(fill="x",pady=(8,5))
        ttk.Label(row,text="Ridge direction",style="Panel.TLabel").pack(side="left")
        self.axis=tk.StringVar(value="X")
        axes=ttk.Combobox(row,textvariable=self.axis,values=("X","Y"),width=5,state="readonly")
        axes.pack(side="right")
        axes.bind("<<ComboboxSelected>>",self.changed)
        row=ttk.Frame(side,style="Panel.TFrame")
        row.pack(fill="x",pady=(6,4))
        ttk.Label(row,text="Roof type",style="Panel.TLabel").pack(side="left")
        self.roof_type=tk.StringVar(value="Gable")
        roofs=ttk.Combobox(row,textvariable=self.roof_type,
                           values=("Gable","Hip"),
                           width=16,state="readonly")
        roofs.pack(side="right")
        roofs.bind("<<ComboboxSelected>>",self.changed)
        self.extended_gable=tk.BooleanVar(value=True)
        ttk.Checkbutton(side,text="Extend gable to overhang",
                        variable=self.extended_gable,
                        command=self.changed).pack(anchor="w",pady=4)
        self.thickness_enabled=tk.BooleanVar(value=False)
        ttk.Checkbutton(side,text="Gable roof thickness (on/off)",
                        variable=self.thickness_enabled,
                        command=self.changed).pack(anchor="w",pady=4)
        ttk.Checkbutton(side,text="Auto-snap (up to 2 units)",variable=self.snap).pack(anchor="w",pady=4)
        ttk.Button(side,text="Join roofs (overlap)",command=self.snap_to_neighbor).pack(fill="x",pady=5)
        ttk.Label(side,text="Roof colour and texture",style="Heading.TLabel").pack(anchor="w",pady=(12,5))
        roof_controls=ttk.Frame(side,style="Panel.TFrame")
        roof_controls.pack(fill="x",pady=(0,4))
        self.roof_swatch=tk.Label(roof_controls,text="  ",bg=self.roof_hex(),width=4)
        self.roof_swatch.pack(side="left",padx=(0,6))
        ttk.Button(roof_controls,text="Roof palette…",command=self.pick_roof_palette).pack(side="left",expand=True,fill="x")
        ttk.Checkbutton(side,text="Roof slope stripes",variable=self.roof_lines,command=self.schedule).pack(anchor="w")
        for label,variable,low,high in (("Stripe spacing (units)",self.roof_spacing,2,18),
                                         ("Darkening (%)",self.roof_opacity,5,65),
                                         ("Softness",self.roof_softness,0.1,2.0)):
            row=ttk.Frame(side,style="Panel.TFrame"); row.pack(fill="x",pady=2)
            ttk.Label(row,text=label,style="Panel.TLabel").pack(side="left")
            increment=0.1 if label=="Softness" else 1
            spin=ttk.Spinbox(row,from_=low,to=high,increment=increment,width=7,textvariable=variable,command=self.schedule)
            spin.pack(side="right");spin.bind("<Return>",lambda e:self.schedule());spin.bind("<FocusOut>",lambda e:self.schedule())
        ttk.Label(side,text="Quick examples",style="Heading.TLabel").pack(anchor="w",pady=(12,5))
        presets=ttk.Frame(side,style="Panel.TFrame")
        presets.pack(fill="x")
        for label,code in (("Single","I"),("L","L"),("T","T"),("+","+")):
            ttk.Button(presets,text=label,command=lambda s=code:self.preset(s)).pack(side="left",expand=True,fill="x")
        ttk.Label(side,text="Overhang expands the roof outline,\n"
                           "lower eave changes edge height.\n"
                           "Ridge remains in place.\n"
                           "Thickness applies to gable ends only.",
                  style="Panel.TLabel",justify="left").pack(anchor="w",pady=(12,0))
        right=ttk.Frame(body,style="Panel.TFrame",padding=10)
        right.pack(side="left",fill="both",expand=True)
        toolbar=ttk.Frame(right,style="Panel.TFrame")
        toolbar.pack(fill="x",pady=(0,8))
        ttk.Label(toolbar,text="Preview",style="Heading.TLabel").pack(side="left")
        ttk.Button(toolbar,text="0°",command=self.reset_rotation).pack(side="right",padx=4)
        ttk.Button(toolbar,text="+15° ↷",command=lambda:self.rotate(15)).pack(side="right",padx=4)
        ttk.Button(toolbar,text="↶ −15°",command=lambda:self.rotate(-15)).pack(side="right",padx=4)
        self.angle_label=ttk.Label(toolbar,text="0°",style="Panel.TLabel",width=5)
        self.angle_label.pack(side="right",padx=(0,8))
        ttk.Checkbutton(toolbar,text="Cast shadow",variable=self.cast_shadow,
                        command=self.schedule).pack(side="right",padx=(0,12))
        self.status=ttk.Label(right,text="",style="Panel.TLabel")
        self.status.pack(anchor="w",pady=(0,6))
        self.canvas=tk.Canvas(right,bg=PREVIEW,highlightthickness=0)
        self.canvas.pack(fill="both",expand=True)
        self.canvas.bind("<Configure>",lambda e:self.schedule())

    def roof_hex(self):
        return "#%02x%02x%02x" % self.roof_color

    def pick_roof_palette(self):
        path=ROOF_PALETTE_PATH
        if not path.is_file():
            selected=filedialog.askopenfilename(title="Roof palette",filetypes=[("Images","*.png *.jpg *.jpeg")])
            if not selected:return
            path=Path(selected)
        try:
            picture=Image.open(path).convert("RGB")
        except Exception as exc:
            messagebox.showerror("Roof palette",str(exc));return
        popup=tk.Toplevel(self.root);popup.title("Choose roof colour")
        popup.transient(self.root)
        maxw,maxh=760,490
        factor=min(1.0,maxw/picture.width,maxh/picture.height)
        shown=picture.resize((max(1,round(picture.width*factor)),max(1,round(picture.height*factor))),Image.Resampling.BILINEAR)
        photo=ImageTk.PhotoImage(shown)
        canvas=tk.Canvas(popup,width=shown.width,height=shown.height,highlightthickness=0)
        canvas.pack(padx=10,pady=10)
        canvas.image=photo
        canvas.create_image(0,0,image=photo,anchor="nw")
        ttk.Label(popup,text="Click the desired shade to apply it to all roof slopes.").pack(pady=(0,10))
        def choose(event):
            x=min(picture.width-1,max(0,int(event.x/factor)))
            y=min(picture.height-1,max(0,int(event.y/factor)))
            self.roof_color=picture.getpixel((x,y))
            self.roof_swatch.configure(bg=self.roof_hex())
            popup.destroy();self.schedule()
        canvas.bind("<Button-1>",choose)

    def roof_render_options(self):
        try:
            return dict(roof_color=self.roof_color,roof_lines=bool(self.roof_lines.get()),
                        roof_spacing=max(2,int(self.roof_spacing.get())),
                        roof_opacity=max(0,min(85,int(self.roof_opacity.get()))),
                        roof_softness=max(0.05,float(self.roof_softness.get())))
        except (ValueError,tk.TclError):
            return dict(roof_color=self.roof_color,roof_lines=bool(self.roof_lines.get()))

    def refresh_list(self):
        self.listbox.delete(0,"end")
        for i,b in enumerate(self.blocks):
            self.listbox.insert("end",f"{i+1}. {b.name}  ({b.axis})")
        if self.blocks:
            self.active=max(0,min(self.active,len(self.blocks)-1))
            self.listbox.selection_set(self.active)
            self.listbox.activate(self.active)
            self.load_fields()

    def load_fields(self):
        if not self.blocks:return
        self.updating=True
        b=self.blocks[self.active]
        for key,var in self.vars.items():var.set(getattr(b,key))
        self.axis.set(b.axis)
        self.roof_type.set(b.roof_type)
        self.thickness_enabled.set(b.thickness_enabled)
        self.extended_gable.set(b.extended_gable)
        self.updating=False

    def choose(self,event=None):
        selected=self.listbox.curselection()
        if selected:
            self.active=selected[0]
            self.load_fields()

    def changed(self,event=None):
        if self.updating or not self.blocks:return
        b=self.blocks[self.active]
        try:
            values={key:var.get() for key,var in self.vars.items()}
        except (ValueError,tk.TclError):
            return
        oldx,oldy=b.x,b.y
        for key,value in values.items():
            setattr(b,key,max(12,value) if key in ("w","d") else max(1,value) if key in ("h","rise") else value)
        b.axis=self.axis.get()
        b.roof_type=self.roof_type.get()
        b.thickness_enabled=self.thickness_enabled.get()
        b.extended_gable=self.extended_gable.get()
        b.overhang=min(8,max(0,b.overhang))
        b.thickness=min(2,max(0,b.thickness))
        b.eave_drop=min(3,max(0,b.eave_drop))
        max_ridge=b.w if b.axis=="X" else b.d
        b.ridge=min(max(0,b.ridge),max_ridge)
        if self.snap.get() and (oldx!=b.x or oldy!=b.y):
            self.apply_snap(b,2)
        self.schedule()

    def apply_snap(self,b,tolerance=6):
        others=[o for o in self.blocks if o is not b]
        if not others:return
        for coord,size in (("x","w"),("y","d")):
            current=getattr(b,coord)
            length=getattr(b,size)
            possibilities=[]
            for o in others:
                ostart=getattr(o,coord);oend=ostart+getattr(o,size)
                for target in (ostart,oend,ostart-length,oend-length):
                    possibilities.append((abs(target-current),target))
            if possibilities:
                dist,target=min(possibilities)
                if dist<=tolerance:setattr(b,coord,int(target))
        self.load_fields()

    def snap_to_neighbor(self):
        """Join roof footprints with an intentional overlap, not edge contact.

        Merely touching walls does not create a valley between roof solids.
        The button creates an overlap while preserving the other coordinate.
        """
        if len(self.blocks)<2:return
        b=self.blocks[self.active]
        others=[o for o in self.blocks if o is not b]
        def overlap(a0,a1,b0,b1):
            return min(a1,b1)-max(a0,b0)
        if any(overlap(b.x,b.x+b.w,o.x,o.x+o.w)>0 and
               overlap(b.y,b.y+b.d,o.y,o.y+o.d)>0 for o in others):
            self.schedule()
            return
        choices=[]
        for o in others:
            for coord,size,other_coord,other_size in (("x","w","y","d"),("y","d","x","w")):
                # A joint is useful only if the footprints overlap on the
                # perpendicular axis, or can be centered on that axis.
                current=getattr(b,coord)
                length=getattr(b,size)
                left=getattr(o,coord)
                right=left+getattr(o,size)
                inset=max(2,min(length,getattr(o,size))//3)
                for target in (left-length+inset,right-inset):
                    choices.append((abs(current-target),coord,target,o,other_coord,other_size))
        if choices:
            _,coord,target,o,other_coord,other_size=min(choices,key=lambda t:t[0])
            setattr(b,coord,int(target))
            perpendicular_start=getattr(b,other_coord)
            perpendicular_end=perpendicular_start+getattr(b,other_size)
            neighbor_start=getattr(o,other_coord)
            neighbor_end=neighbor_start+getattr(o,other_size)
            if overlap(perpendicular_start,perpendicular_end,neighbor_start,neighbor_end)<=0:
                setattr(b,other_coord,int(neighbor_start+(getattr(o,other_size)-getattr(b,other_size))/2))
            self.load_fields()
            self.schedule()

    def add(self):
        n=len(self.blocks)
        self.blocks.append(Block(name=f"Block {n+1}",x=8+n*4,y=8+n*4,
                                 w=28,d=20,h=36,rise=10,axis="Y",
                                 roof_type="Hip",ridge=12))
        self.active=n
        self.refresh_list()
        self.schedule()

    def duplicate(self):
        if not self.blocks:return
        original=asdict(self.blocks[self.active])
        original["name"]=original["name"]+" copy"
        original["x"]+=8;original["y"]+=8
        self.blocks.append(Block(**original))
        self.active=len(self.blocks)-1
        self.refresh_list();self.schedule()

    def delete(self):
        if len(self.blocks)<=1:
            messagebox.showinfo("Blocks","At least one block must remain.")
            return
        self.blocks.pop(self.active)
        self.active=max(0,self.active-1)
        self.refresh_list();self.schedule()

    def preset(self,shape):
        main=Block("Main block",0,0,48,24,36,12,"X",
                   "Hip",ridge=24,overhang=1,thickness=1)
        if shape=="I":
            self.blocks=[main]
        elif shape=="L":
            side=Block("Side wing",0,12,24,44,36,12,"Y",
                       "Hip",ridge=20,overhang=1,thickness=1)
            self.blocks=[main,side]
        elif shape=="T":
            side=Block("Cross wing",14,12,20,44,36,12,"Y",
                       "Hip",ridge=20,overhang=1,thickness=1)
            self.blocks=[main,side]
        else:
            side=Block("Cross wing",14,-10,20,44,36,12,"Y",
                       "Hip",ridge=20,overhang=1,thickness=1)
            self.blocks=[main,side]
        self.active=len(self.blocks)-1
        self.refresh_list();self.schedule()

    def rotate(self,delta):
        # Rotate the entire scene, never mutate any Block coordinates.
        self.angle=(self.angle+delta)%360
        self.angle_label.configure(text=f"{self.angle}°")
        if callable(getattr(self,"rotation_callback",None)):self.rotation_callback()
        self.schedule()

    def reset_rotation(self):
        self.angle=0
        self.angle_label.configure(text="0°")
        if callable(getattr(self,"rotation_callback",None)):self.rotation_callback()
        self.schedule()

    def schedule(self):
        if self.after_id is not None:self.root.after_cancel(self.after_id)
        self.after_id=self.root.after(160,self.refresh)

    def refresh(self):
        self.after_id=None
        try:
            image=render_scene(self.blocks,self.angle,cast_shadow=self.cast_shadow.get(),facade_texture=self.facade_texture,facade_source=self.facade_source,facade_filter=self.facade_filter,facade_front=self.facade_front,**self.roof_render_options())
        except (ValueError,tk.TclError) as exc:
            self.status.configure(text=f"Error: {exc}")
            return
        cw=max(100,self.canvas.winfo_width());ch=max(100,self.canvas.winfo_height())
        factor=min((cw-24)/image.width,(ch-24)/image.height)
        # Preserve visible pixel-art steps without giant initial objects.
        if factor>=1:
            zoom=min(4,max(1,int(factor)))
            image=image.resize((image.width*zoom,image.height*zoom),Image.Resampling.NEAREST)
        self.photo=ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(cw//2,ch//2,image=self.photo,anchor="center")
        self.status.configure(text=f"{len(self.blocks)} blocks · {self.angle}° · automatic roof joining")

    def export_png(self):
        path=filedialog.asksaveasfilename(defaultextension=".png",filetypes=[("PNG","*.png")])
        if path:
            try:render_scene(self.blocks,self.angle,cast_shadow=self.cast_shadow.get(),facade_texture=self.facade_texture,facade_source=self.facade_source,facade_filter=self.facade_filter,facade_front=self.facade_front,**self.roof_render_options()).save(path)
            except Exception as exc:messagebox.showerror("Error",str(exc))

    def export_json(self):
        path=filedialog.asksaveasfilename(defaultextension=".json",filetypes=[("JSON","*.json")])
        if path:
            with open(path,"w",encoding="utf-8") as f:
                json.dump({"format":"SC3K-volume","version":13.5,"angle":self.angle,"cast_shadow":self.cast_shadow.get(),
                           "roof_color":self.roof_hex(),"roof_lines":self.roof_lines.get(),
                           "roof_spacing":self.roof_spacing.get(),"roof_opacity":self.roof_opacity.get(),
                           "roof_softness":self.roof_softness.get(),
                           "blocks":[asdict(b) for b in self.blocks]},f,ensure_ascii=False,indent=2)

    def import_json(self):
        path=filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if not path:return
        try:
            with open(path,encoding="utf-8") as f:data=json.load(f)
            # Accept projects made in the Russian macOS edition too.
            legacy_roofs={"Двускатная":"Gable", "Четырёхскатная":"Hip"}
            loaded=[Block(**{**b, "roof_type":legacy_roofs.get(b.get("roof_type"), b.get("roof_type","Gable"))})
                    for b in data["blocks"]]
            if not loaded:raise ValueError("No building blocks")
            self.blocks=loaded
            self.cast_shadow.set(bool(data.get("cast_shadow",False)))
            rc=data.get("roof_color")
            if isinstance(rc,str) and len(rc)==7 and rc.startswith("#"):
                try:self.roof_color=tuple(bytes.fromhex(rc[1:]))
                except ValueError:pass
            self.roof_lines.set(bool(data.get("roof_lines",True)))
            self.roof_spacing.set(int(data.get("roof_spacing",7)))
            self.roof_opacity.set(int(data.get("roof_opacity",30)))
            self.roof_softness.set(float(data.get("roof_softness",0.65)))
            self.roof_swatch.configure(bg=self.roof_hex())
            # Older saves with 90-degree rotation remain compatible.
            self.angle=(round(float(data.get("angle",0))/15)*15)%360
            self.angle_label.configure(text=f"{self.angle}°")
            self.active=0;self.refresh_list();self.schedule()
        except Exception as exc:messagebox.showerror("Could not open file",str(exc))

if __name__=="__main__":
    root=tk.Tk()
    App(root)
    root.mainloop()
