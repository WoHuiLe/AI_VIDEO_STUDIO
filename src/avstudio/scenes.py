"""Deterministic vector scene: one command stream for browser and FFmpeg."""
import math
from PIL import Image, ImageDraw
from .storage import StudioError


def validate_scene(scene):
    if not isinstance(scene, dict) or set(scene) - {"palette", "rain", "walk", "lamp"}:
        raise StudioError("程序场景格式无效")
    if scene.get("palette") not in {"night", "warm", "dawn"} or type(scene.get("walk")) is not bool:
        raise StudioError("场景配色或人物动作无效")
    for field in ["rain", "lamp"]:
        if type(scene.get(field)) not in {int, float} or not math.isfinite(scene[field]) or not 0 <= scene[field] <= 1:
            raise StudioError("雨量与灯光须为 0–1")
    return scene


def commands(scene, progress, motion="static"):
    validate_scene(scene)
    t = max(0, min(1, progress)); palette=scene["palette"]
    sky, wall, floor, accent = {"night": ("#101d32", "#253846", "#13262c", "#e9ba78"),
        "warm": ("#c48972", "#66574e", "#353d3d", "#f6d7a1"),
        "dawn": ("#8da5ae", "#56696a", "#253f43", "#f8dec0")}[palette]
    out=[]
    def add(kind, points, fill, width=1):out.append({"kind":kind,"points":points,"fill":fill,"width":width})
    add("rect",[0,0,1280,720],wall)
    add("poly",[0,550,1280,490,1280,720,0,720],floor)
    add("rect",[110,65,880,500],"#101c27")
    add("rect",[124,79,866,483],sky)
    add("ellipse",[665,110,743,188],accent)
    for i in range(16):
        x=145+(i*117)%690;y=92+(i*51)%200
        add("ellipse",[x,y,x+2,y+2],"#c2d3d4")
    for i in range(19):
        x=125+i*41;h=85+(i*71)%120
        add("rect",[x,483-h,x+34,483],"#1d303e")
        for j in range(3):
            add("rect",[x+8,483-h+18+j*24,x+12,483-h+24+j*24],"#9c8c70")
    for i in range(round(scene["rain"]*75)):
        x=133+(i*89+t*36)%720;y=90+(i*67+t*580)%375
        add("line",[x,y,x-5,y+17],"#718d9e",1)
    add("rect",[480,78,494,484],"#172630");add("rect",[125,270,865,282],"#172630")
    add("poly",[98,55,193,55,176,495,94,526],"#425964")
    add("poly",[791,55,890,55,902,520,826,492],"#354e59")
    add("rect",[100,483,889,505],"#ae9272")
    # Paper-cut figure; walking is a real articulated pose, not translation alone.
    x=470+250*t if scene["walk"] else 580
    swing=math.sin(t*math.pi*8)*19 if scene["walk"] else math.sin(t*math.pi*2)*2
    breath=math.sin(t*math.pi*4)*2
    add("ellipse",[x-76,604,x+76,622],"#102329")
    add("line",[x-13,534,x-23-swing,604],"#14232c",16)
    add("line",[x+13,534,x+24+swing,604],"#14232c",16)
    add("poly",[x-33,391+breath,x+24,391+breath,x+49,546,x-47,546],"#b98b71" if palette=="warm" else "#809091")
    add("line",[x-27,411+breath,x-39+swing/2,484],"#657b80",13)
    add("line",[x+21,410+breath,x+40-swing/2,481],"#657b80",13)
    add("ellipse",[x-26,336+breath,x+23,397+breath],"#c9aa90")
    add("poly",[x-29,364+breath,x-24,333+breath,x+6,325+breath,x+27,348+breath,x+13,369+breath],"#20313a")
    # Foreground desk, pages and lamp give depth without decorative particles.
    add("poly",[0,635,403,595,652,720,0,720],"#4d5956")
    add("poly",[60,643,277,620,386,666,155,696],"#d8cdb5")
    for i in range(5):add("line",[110+i*6,652+i*6,260+i*6,637+i*6],"#a09e8d",1)
    add("rect",[1022,386,1032,605],"#17272b")
    add("ellipse",[981,590,1073,611],"#17272b")
    glow=scene["lamp"]*(.93+.07*math.sin(t*math.pi*2))
    add("poly",[1001,363,1057,363,1190,642,863,642],f"rgba(245,202,131,{glow*.11:.3f})")
    add("poly",[968,320,1086,320,1117,391,940,391],accent)
    add("rect",[0,707,1280,720],"#10232a")
    if motion != "static":
        ease=t*t*(3-2*t)
        zoom=1.06+.06*ease if motion=="push_in" else 1.12-.06*ease if motion=="pull_out" else 1.08
        shift=(.02-.04*ease) if motion=="pan_left" else (-.02+.04*ease) if motion=="pan_right" else 0
        for item in out:
            item["points"]=[(v-640)*zoom+640+shift*1280 if i%2==0 else (v-360)*zoom+360 for i,v in enumerate(item["points"])]
            item["width"]*=zoom
    return out


def raster(scene, progress, size, motion="static"):
    # Supersampling keeps paper-cut edges clean in preview and final export.
    scale=min(2,2560/max(size));w=max(1,round(size[0]*scale));h=max(1,round(size[1]*scale))
    image=Image.new("RGBA",(w,h));sx=w/1280;sy=h/720
    for item in commands(scene,progress,motion):
        coords=[v*(sx if i%2==0 else sy) for i,v in enumerate(item["points"])]
        color=item["fill"]
        if color.startswith("rgba"):
            values=color[5:-1].split(',');color=tuple([int(v) for v in values[:3]]+[round(float(values[3])*255)])
            overlay=Image.new("RGBA",image.size);draw=ImageDraw.Draw(overlay)
        else:overlay=None;draw=ImageDraw.Draw(image)
        if item["kind"]=="rect":draw.rectangle(coords,fill=color)
        elif item["kind"]=="ellipse":draw.ellipse(coords,fill=color)
        elif item["kind"]=="poly":draw.polygon(coords,fill=color)
        else:draw.line(coords,fill=color,width=max(1,round(item["width"]*sx)))
        if overlay:image=Image.alpha_composite(image,overlay)
    return image.convert("RGB").resize(size,Image.Resampling.LANCZOS)
