#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mosaic-cipher print generator for a friend's birthday hoodie.
Everything is built from the SAME triangular shard language so nothing
"floats" on top — emblems are woven into the mosaic as medallions.

Hero: his apartment tower whose lit windows form the number 15
(home + jersey number + lucky number).
Around it (mosaic medallions): dogs Maria & Stepan, BMW / Audi / Mini
roundels, Obolon FC shield, football with 15, Kyiv cake.
Hidden cipher: wife's name "Дарина" as a constellation.
"""
import random, math

random.seed(1508)  # 15 / month-ish seed, deterministic output

W, H = 900, 1200
OUT = "/Users/macbookair/Desktop/VideoEditor/print_dog.svg"

# ---- palette (fixed print colors, NOT theme-adaptive) ----
BG        = "#0d1117"
FABRIC    = ["#111826", "#141d2e", "#182338", "#0f1622", "#131b2b"]
SLATE     = ["#1c2740", "#22314f", "#2a3c60", "#324670"]
TEAL      = ["#173f42", "#1d5155", "#236166"]
GOLD      = "#e9b44c"
GOLD_HI   = "#f6d78a"
GOLD_LO   = "#b9832f"
COPPER    = "#c77b3b"
BONE      = "#e7e2d6"
GREEN     = "#2fa64f"   # Obolon
GREENY    = "#c9d64a"
INK       = "#0a0e15"

parts = []
def add(s): parts.append(s)

# ============================================================
# 1. MOSAIC SHARD FIELD (covers the whole canvas)
# ============================================================
# jittered triangular grid -> the unifying "tile" language
GRID = 52
pts = {}
def key(i, j): return (i, j)
cols = W // GRID + 3
rows = H // GRID + 3
for j in range(rows):
    for i in range(cols):
        x = (i - 1) * GRID + random.uniform(-14, 14)
        y = (j - 1) * GRID + random.uniform(-14, 14)
        pts[key(i, j)] = (x, y)

def lerp(a, b, t): return a + (b - a) * t
def hex2rgb(h): h=h.lstrip('#'); return tuple(int(h[k:k+2],16) for k in (0,2,4))
def rgb2hex(r): return '#%02x%02x%02x' % tuple(max(0,min(255,int(c))) for c in r)
def mix(c1, c2, t):
    a, b = hex2rgb(c1), hex2rgb(c2)
    return rgb2hex(tuple(lerp(a[k], b[k], t) for k in range(3)))
def shade(c, f):  # f<1 darker, >1 lighter
    r = hex2rgb(c); return rgb2hex(tuple(v*f for v in r))

def centroid(tri):
    return (sum(p[0] for p in tri)/3, sum(p[1] for p in tri)/3)

# ----- imagery "fields": functions returning a color for a shard
#       centroid, or None if that shard is plain fabric. This is what
#       makes the picture EMERGE from the tiles instead of sitting on top.

CX = W/2
TOWER_TOP, TOWER_BOT = 250, 880
TOWER_W = 300

def tower_field(cx, cy):
    """His apartment tower. Returns color for shard inside the tower,
    with lit windows spelling 15."""
    half = TOWER_W/2 * (0.62 + 0.38*(cy-TOWER_TOP)/(TOWER_BOT-TOWER_TOP))
    if cy < TOWER_TOP or cy > TOWER_BOT: return None
    if abs(cx-CX) > half: return None
    # window grid coordinates
    gx = (cx - (CX-half)) / (2*half)          # 0..1 across
    gy = (cy - TOWER_TOP) / (TOWER_BOT-TOWER_TOP)  # 0..1 down
    col = int(gx*9); row = int(gy*16)
    lit = digit_lit(col, row)
    base = mix(SLATE[1], INK, 0.35)
    if lit:
        # light -> number transition: brighter toward center rows
        t = 0.5 + 0.5*math.sin(gy*math.pi)
        return mix(GOLD, GOLD_HI, t*random.uniform(0.3,1.0))
    # dark windows / structure
    return mix(base, random.choice(SLATE), random.uniform(0.0,0.5))

# 9-col x 16-row bitmap of the digits "1" and "5" (lit windows)
_ONE = ["..X..", "..X..", "..X..", "..X..", "..X..", "..X..", "..X.."]
_FIVE= ["XXXX.", "X....", "XXXX.", "....X", "....X", "X...X", ".XXX."]
def digit_lit(col, row):
    # place "1" in cols 0..3, "5" in cols 5..8, rows 3..12 (7 tall)
    if row < 4 or row > 12: return False
    r = int((row-4)/9*7)  # map to 7-row glyph
    r = max(0, min(6, r))
    if 0 <= col <= 3:
        c = int(col/4*5); c=max(0,min(4,c))
        return _ONE[r][c] == 'X'
    if 5 <= col <= 8:
        c = int((col-5)/4*5); c=max(0,min(4,c))
        return _FIVE[r][c] == 'X'
    return False

def field_color(cx, cy):
    c = tower_field(cx, cy)
    if c: return c, True
    # ambient glow halo behind tower
    d = math.hypot(cx-CX, cy-(TOWER_TOP+TOWER_BOT)/2)
    if d < 360:
        t = (1 - d/360)*0.30
        return mix(random.choice(FABRIC), GOLD_LO, t*random.uniform(0.3,1)), False
    return random.choice(FABRIC), False

# ----- emit triangles
for j in range(rows-1):
    for i in range(cols-1):
        a = pts[key(i,j)]; b = pts[key(i+1,j)]
        c = pts[key(i,j+1)]; d = pts[key(i+1,j+1)]
        for tri in ((a,b,c),(b,d,c)):
            cx, cy = centroid(tri)
            col, lit = field_color(cx, cy)
            op = 1.0
            stroke = shade(col, 0.7)
            sw = 0.6 if lit else 0.4
            pth = "M%.1f %.1f L%.1f %.1f L%.1f %.1f Z" % (
                tri[0][0],tri[0][1],tri[1][0],tri[1][1],tri[2][0],tri[2][1])
            add('<path d="%s" fill="%s" stroke="%s" stroke-width="%.1f"/>'%(
                pth, col, stroke, sw))

# ============================================================
# 2. MOSAIC MEDALLIONS  (same shard style, clipped to circle)
# ============================================================
def shard_disc(cx, cy, r, colors, seed, n=22):
    """A little Voronoi-ish shard disc so emblems read as mosaic."""
    rnd = random.Random(seed)
    out = ['<g clip-path="url(#clip%d)">'%seed]
    out.append('<clipPath id="clip%d"><circle cx="%.1f" cy="%.1f" r="%.1f"/></clipPath>'%(seed,cx,cy,r))
    # radial shard petals
    ang = 0
    while ang < 2*math.pi:
        da = rnd.uniform(0.25, 0.5)
        r1 = r*rnd.uniform(0.85,1.15); r2 = r*rnd.uniform(0.85,1.15)
        x1=cx+r1*math.cos(ang); y1=cy+r1*math.sin(ang)
        x2=cx+r2*math.cos(ang+da); y2=cy+r2*math.sin(ang+da)
        col = rnd.choice(colors)
        out.append('<path d="M%.1f %.1f L%.1f %.1f L%.1f %.1f Z" fill="%s" stroke="%s" stroke-width="0.5"/>'%(
            cx,cy,x1,y1,x2,y2,col,shade(col,0.7)))
        ang += da
    out.append('</g>')
    return "".join(out)

def ring(cx, cy, r, col, sw=3):
    return '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="%d"/>'%(cx,cy,r,col,sw)

emb = []

# --- BMW roundel woven as mosaic (quartered) ---
def bmw(cx, cy, r):
    g=['<g>']
    g.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"/>'%(cx,cy,r,INK))
    for k,(a0,col) in enumerate([(180,BONE),(270,mix(SLATE[3],"#4a78c8",0.6)),(0,BONE),(90,mix(SLATE[3],"#4a78c8",0.6))]):
        a=math.radians(a0)
        g.append('<path d="M%.1f %.1f L%.1f %.1f A%.1f %.1f 0 0 1 %.1f %.1f Z" fill="%s" stroke="%s" stroke-width="0.6"/>'%(
            cx,cy, cx+r*.72*math.cos(a),cy+r*.72*math.sin(a), r*.72,r*.72,
            cx+r*.72*math.cos(a+math.pi/2), cy+r*.72*math.sin(a+math.pi/2), col, shade(col,0.7)))
    g.append(ring(cx,cy,r,GOLD_LO,3))
    g.append(ring(cx,cy,r*.72,GOLD,2))
    g.append('</g>'); return "".join(g)

# --- Audi four rings, mosaic-tinted ---
def audi(cx, cy, r):
    g=['<g>']
    for k in range(4):
        x=cx+(k-1.5)*r*0.9
        g.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="4"/>'%(x,cy,r,mix(BONE,SLATE[3],0.35)))
        g.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="1"/>'%(x,cy,r,GOLD_LO))
    g.append('</g>'); return "".join(g)

# --- Mini winged roundel (simplified, mosaic) ---
def mini(cx, cy, r):
    g=['<g>']
    g.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="%s" stroke-width="3"/>'%(cx,cy,r,INK,GOLD))
    # wings
    for s in (-1,1):
        g.append('<path d="M%.1f %.1f q %.1f -%.1f %.1f 0 q -%.1f %.1f -%.1f %.1f Z" fill="%s" stroke="%s" stroke-width="0.6"/>'%(
            cx+s*r, cy, s*r*0.9, r*0.5, s*r*1.7, r*0.5, s*r*0.5, s*r*1.7, r*0.35, mix(BONE,GOLD,0.2), GOLD_LO))
    g.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-family="Georgia,serif" font-size="%.0f" fill="%s" font-style="italic">MINI</text>'%(cx,cy+r*0.35,r*0.7,BONE))
    g.append('</g>'); return "".join(g)

# --- Obolon shield ---
def obolon(cx, cy, r):
    g=['<g>']
    g.append('<path d="M%.1f %.1f L%.1f %.1f L%.1f %.1f L%.1f %.1f L%.1f %.1f Z" fill="%s" stroke="%s" stroke-width="2.5"/>'%(
        cx-r,cy-r, cx+r,cy-r, cx+r,cy+r*0.3, cx,cy+r*1.3, cx-r,cy+r*0.3, GREEN, GREENY))
    g.append('<path d="M%.1f %.1f L%.1f %.1f L%.1f %.1f Z" fill="%s"/>'%(cx,cy-r*0.4, cx-r*0.5,cy+r*0.6, cx+r*0.5,cy+r*0.6, GREENY))
    g.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-family="Georgia,serif" font-size="%.0f" fill="%s">15</text>'%(cx,cy+r*0.35,r*0.7,GREEN))
    g.append('</g>'); return "".join(g)

# --- Kyiv cake (round, hazelnut ring) ---
def cake(cx, cy, r):
    g=['<g>']
    g.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="%s" stroke-width="2"/>'%(cx,cy,r,mix(COPPER,INK,0.3),GOLD_LO))
    g.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="3" stroke-dasharray="3 4"/>'%(cx,cy,r*0.7,GOLD))
    for k in range(12):
        a=k/12*2*math.pi
        g.append('<circle cx="%.1f" cy="%.1f" r="3.5" fill="%s"/>'%(cx+r*0.85*math.cos(a),cy+r*0.85*math.sin(a),GOLD_HI))
    g.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-family="Georgia,serif" font-size="%.0f" fill="%s">Київ</text>'%(cx,cy+r*0.25,r*0.55,BONE))
    g.append('</g>'); return "".join(g)

# --- geometric dog head (low-poly) ---
def dog(cx, cy, r, name, flip=1):
    rnd=random.Random(hash(name)%9999)
    g=['<g>']
    P=lambda dx,dy:(cx+flip*dx*r, cy+dy*r)
    # ears + head triangles
    tris=[
        [P(-0.9,-0.9),P(-0.4,-0.2),P(-0.95,0.1)],   # left ear
        [P(0.9,-0.9),P(0.4,-0.2),P(0.95,0.1)],       # right ear
        [P(-0.4,-0.2),P(0.4,-0.2),P(0,0.4)],         # forehead
        [P(-0.4,-0.2),P(0,0.4),P(-0.55,0.5)],
        [P(0.4,-0.2),P(0,0.4),P(0.55,0.5)],
        [P(-0.55,0.5),P(0,0.4),P(0,1.0)],            # muzzle L
        [P(0.55,0.5),P(0,0.4),P(0,1.0)],             # muzzle R
    ]
    cols=[BONE, mix(BONE,COPPER,0.4), mix(BONE,SLATE[2],0.3), COPPER]
    for t in tris:
        col=rnd.choice(cols)
        g.append('<path d="M%.1f %.1f L%.1f %.1f L%.1f %.1f Z" fill="%s" stroke="%s" stroke-width="0.6"/>'%(
            t[0][0],t[0][1],t[1][0],t[1][1],t[2][0],t[2][1],col,shade(col,0.65)))
    # eyes + nose
    g.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s"/>'%(cx-flip*0.22*r,cy+0.05*r,INK))
    g.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s"/>'%(cx+flip*0.22*r,cy+0.05*r,INK))
    g.append('<circle cx="%.1f" cy="%.1f" r="6" fill="%s"/>'%(cx,cy+0.9*r,INK))
    g.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-family="Georgia,serif" font-size="20" fill="%s" letter-spacing="1">%s</text>'%(
        cx,cy+1.5*r,GOLD,name))
    g.append('</g>'); return "".join(g)

# --- place medallions (woven around the tower base & upper field) ---
emb.append(dog(210, 720, 90, "Мар'я", flip=1))
emb.append(dog(690, 720, 90, "Степан", flip=-1))
emb.append(bmw(180, 360, 62))
emb.append(audi(700, 360, 40))
emb.append(mini(160, 520, 58))
emb.append(obolon(735, 520, 60))
emb.append(cake(450, 1000, 70))

# football with 15
fb_cx, fb_cy, fb_r = 300, 980, 46
emb.append('<circle cx="%d" cy="%d" r="%d" fill="%s" stroke="%s" stroke-width="2"/>'%(fb_cx,fb_cy,fb_r,BONE,SLATE[1]))
for k in range(5):
    a=k/5*2*math.pi - math.pi/2
    x=fb_cx+fb_r*0.5*math.cos(a); y=fb_cy+fb_r*0.5*math.sin(a)
    pts5=[]
    for m in range(5):
        aa=a+m/5*2*math.pi
        pts5.append("%.1f,%.1f"%(x+13*math.cos(aa),y+13*math.sin(aa)))
    emb.append('<polygon points="%s" fill="%s"/>'%(" ".join(pts5[::2]),INK))
emb.append('<text x="%d" y="%d" text-anchor="middle" font-family="Georgia,serif" font-size="30" fill="%s">15</text>'%(fb_cx,fb_cy+10,INK))

# ============================================================
# 3. HIDDEN CIPHER — "Дарина" as a constellation
# ============================================================
name = "Дарина"
star_y = 170
cipher=['<g opacity="0.95">']
sx0 = CX - (len(name)-1)*46/2
prev=None
for idx,ch in enumerate(name):
    x = sx0 + idx*46 + random.uniform(-6,6)
    y = star_y + random.uniform(-10,10)
    if prev:
        cipher.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="0.8" opacity="0.5"/>'%(prev[0],prev[1],x,y,GOLD))
    cipher.append('<circle cx="%.1f" cy="%.1f" r="3.5" fill="%s"/>'%(x,y,GOLD_HI))
    cipher.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-family="Georgia,serif" font-size="15" fill="%s" opacity="0.85">%s</text>'%(x,y-10,BONE,ch))
    prev=(x,y)
cipher.append('</g>')

# ============================================================
# 4. FRAME + CIPHER KEY border
# ============================================================
frame = ('<rect x="18" y="18" width="%d" height="%d" fill="none" stroke="%s" stroke-width="2" rx="6"/>'
         '<rect x="26" y="26" width="%d" height="%d" fill="none" stroke="%s" stroke-width="0.8" rx="4"/>'
        )%(W-36,H-36,GOLD_LO,W-52,H-52,shade(GOLD_LO,0.7))

# ============================================================
# assemble
# ============================================================
svg = []
svg.append('<svg width="100%%" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" role="img">'%(W,H))
svg.append('<title>Мозаичный принт-шифр другу</title><desc>Мозаика из шардов: башня-ЖК с числом 15 из окон, собаки Мария и Степан, эмблемы BMW Audi Mini, щит Оболони, киевский торт, скрытое имя Дарина.</desc>')
svg.append('<rect x="0" y="0" width="%d" height="%d" fill="%s"/>'%(W,H,BG))
svg.extend(parts)            # mosaic field
svg.append("".join(cipher))  # hidden name
svg.extend(emb)              # medallions
svg.append(frame)
svg.append('</svg>')
svg = "".join(svg)

with open(OUT,"w") as f: f.write(svg)
print("wrote", OUT, len(svg), "bytes,", len(parts), "shards")
