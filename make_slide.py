#!/usr/bin/env python3
"""Build Baseline1_Handover_Flow.pptx using only Python stdlib."""
import zipfile, io, os

SW, SH = 12192000, 6858000  # 16:9 EMU

# ── Palette ──────────────────────────────────────────────────────────────────
BG      = "0D1117"
PANEL   = "0D1B2A"
HDR1    = "0C2340"   # source gNB  (blue)
HDR2    = "0C2E18"   # target gNB  (green)
HDR3    = "1E0C30"   # after HO    (purple)
HDRTIM  = "2E1800"   # timeline    (orange)
ORANGE  = "FFA500"
GREEN   = "4ADE80"
BLUE    = "60A5FA"
WHITE   = "E2E8F0"
GRAY    = "8B949E"
RED     = "FC8181"
YELLOW  = "FBBF24"
PURPLE  = "C084FC"
TEAL    = "2DD4BF"
BDRB    = "1E4A8A"
BDRG    = "1A5C30"
BDRP    = "4A1A70"
BDRT    = "8A4A00"

# ── Helpers ───────────────────────────────────────────────────────────────────
def esc(s):
    return (s.replace('&','&amp;').replace('<','&lt;')
             .replace('>','&gt;').replace('"','&quot;'))

def r(txt, sz=11, bold=False, color=WHITE, mono=False, ital=False):
    b  = '1' if bold else '0'
    i  = '1' if ital else '0'
    fn = '<a:latin typeface="Consolas"/>' if mono else '<a:latin typeface="Calibri"/>'
    return (f'<a:r><a:rPr lang="en-US" sz="{sz*100}" b="{b}" i="{i}" dirty="0">'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            f'{fn}</a:rPr><a:t>{esc(txt)}</a:t></a:r>')

def p(*runs, al='l', sb=0, sa=0):
    s = ''
    if sb: s += f'<a:spcBef><a:spcPts val="{sb*100}"/></a:spcBef>'
    if sa: s += f'<a:spcAft><a:spcPts val="{sa*100}"/></a:spcAft>'
    return f'<a:p><a:pPr algn="{al}">{s}</a:pPr>{"".join(runs)}</a:p>'

def ep():
    return '<a:p><a:endParaRPr lang="en-US" sz="800" dirty="0"/></a:p>'

def tb(paras, ml=91440, mr=91440, mt=60000, mb=60000, anch='t'):
    return (f'<p:txBody>'
            f'<a:bodyPr wrap="sq" lIns="{ml}" rIns="{mr}" tIns="{mt}" bIns="{mb}" anchor="{anch}"/>'
            f'<a:lstStyle/>{"".join(paras)}</p:txBody>')

_id = 1
def sp(x, y, w, h, txbody, fill=None, bdr=None, bw=12700, name=''):
    global _id; _id += 1
    f  = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else '<a:noFill/>'
    bd = (f'<a:ln w="{bw}"><a:solidFill><a:srgbClr val="{bdr}"/></a:solidFill></a:ln>'
          if bdr else '<a:ln><a:noFill/></a:ln>')
    return (f'<p:sp>'
            f'<p:nvSpPr><p:cNvPr id="{_id}" name="{name or f"s{_id}"}"/>'
            f'<p:cNvSpPr txBox="1"><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{f}{bd}</p:spPr>'
            f'{txbody}</p:sp>')

# ── Layout constants ───────────────────────────────────────────────────────────
M   = 80000    # edge margin
GAP = 50000    # column gap
CW  = 3960000  # column width
TH  = 600000   # title bar height
PY  = 650000   # panel y start
HH  = 360000   # panel header height
PH  = SH - PY - 80000   # panel total height  = 6128000
CTY = PY + HH            # content area y      = 1010000
CTH = PH - HH            # content area height = 5768000

CX = [M, M+CW+GAP, M+2*CW+2*GAP]  # [80000, 4090000, 8100000]

# timeline bar
TBY = SH - 268000   # 6590000
TBH = 200000

# ── Slide shapes ──────────────────────────────────────────────────────────────
def slide_xml():
    shapes = []

    # 1 ── Background
    shapes.append(sp(0, 0, SW, SH,
        tb([ep()]), fill=BG, name='bg'))

    # 2 ── Title bar
    shapes.append(sp(0, 0, SW, TH,
        tb([p(r('Baseline 1  —  Xn-Based NTN Handover  |  Implementation Flow',
               sz=22, bold=True, color=ORANGE)),
            p(r('Source gNB triggers CLI command  →  Xn prep (JSON/TCP)  →  '
                'UE context release (NGAP)  →  UE re-attaches on target',
               sz=13, color=GRAY))],
           mt=70000, mb=30000),
        fill='111827', bdr='1E3A5F', bw=19050, name='title'))

    # 3 ── Panel backgrounds + headers + content  (3 columns)
    configs = [
        # (header_fill, border, header_label, header_color, content_paras)
        (HDR1, BDRB, '①  Source gNB  —  handover.cpp', BLUE,  src_content()),
        (HDR2, BDRG, '②  Target gNB  —  xn/task.cpp',  GREEN, tgt_content()),
        (HDR3, BDRP, '③  After Handover  —  UE + AMF',  PURPLE,aft_content()),
    ]
    for i, (hf, bd, lbl, lc, content) in enumerate(configs):
        x = CX[i]
        # panel bg
        shapes.append(sp(x, PY, CW, PH,
            tb([ep()]), fill=PANEL, bdr=bd, bw=19050, name=f'panel{i+1}'))
        # header
        shapes.append(sp(x, PY, CW, HH,
            tb([p(r(lbl, sz=13, bold=True, color=lc))],
               mt=110000, ml=120000),
            fill=hf, bdr=bd, bw=19050, name=f'hdr{i+1}'))
        # content
        shapes.append(sp(x, CTY, CW, CTH,
            tb(content, mt=80000, ml=120000, mr=80000),
            fill=PANEL, name=f'content{i+1}'))

    # 4 ── Timeline bar background
    shapes.append(sp(M, TBY, SW-2*M, TBH,
        tb([ep()]), fill=HDRTIM, bdr=BDRT, bw=12700, name='timebg'))

    # 5 ── Timeline text
    shapes.append(sp(M, TBY, SW-2*M, TBH,
        tb([p(
            r('T1', sz=10, bold=True, color=YELLOW),
            r(' ──── xn-prep (Xn round-trip + target processing) ────', sz=10, color=GRAY),
            r(' T2', sz=10, bold=True, color=YELLOW),
            r(' ── psw=0ms (skipped) ── ', sz=10, color=GRAY),
            r('T3', sz=10, bold=True, color=YELLOW),
            r(' ──── release (NGAP UEContextRelease) ────', sz=10, color=GRAY),
            r(' T4', sz=10, bold=True, color=YELLOW),
            r('     │     total = T4−T1  ≈  2 ms  (Baseline 1)',
              sz=10, bold=True, color=ORANGE),
        )], mt=55000, ml=120000),
        fill=HDRTIM, name='timeline'))

    return ('<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
            ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            + ''.join(shapes) +
            '</p:spTree></p:cSld>'
            '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>'
            '</p:sld>')

# ── Content builders ───────────────────────────────────────────────────────────
def src_content():
    def c(txt, sz=10, bold=False, color=WHITE, mono=False, ital=False):
        return r(txt, sz=sz, bold=bold, color=color, mono=mono, ital=ital)
    def cp(txt, sz=10, bold=False, color=WHITE, mono=False, sb=0, ital=False):
        return p(c(txt, sz=sz, bold=bold, color=color, mono=mono, ital=ital), sb=sb)
    return [
        cp('triggerXnHandover(ueId, addr, port, sst)', sz=11, bold=True, color=BLUE, mono=True),
        cp('─'*44, sz=8, color=BDRB),

        cp('T1 ← CurrentTimeMillis()', sz=10, color=YELLOW, mono=True, sb=4),

        cp('Build XnHandoverRequest JSON:', sz=10, bold=True, color=WHITE, sb=6),
        cp('  { ueId, amfUeNgapId, ranUeNgapId,', sz=10, color=GRAY, mono=True),
        cp('    sliceSst, sourceGnb }', sz=10, color=GRAY, mono=True),

        cp('TcpSendRecv(targetAddr, 38422, payload)', sz=10, color=GREEN, mono=True, sb=6),
        cp('  ← blocks until XnHandoverAck', sz=10, color=GRAY, ital=True),

        cp('T2 ← CurrentTimeMillis()', sz=10, color=YELLOW, mono=True, sb=6),

        cp('if dispatcherAddress.empty():', sz=10, color=WHITE, mono=True, sb=6),
        cp('  // Baseline 1 — no dispatcher', sz=10, color=GRAY, mono=True),
        cp('  log warning; SKIP', sz=10, color=RED, mono=True),
        cp('T3 ≈ T2   (no-op)', sz=10, color=GRAY, mono=True),

        cp('sendContextRelease(ueId,', sz=10, color=TEAL, mono=True, sb=6),
        cp('  RadioNetwork_successful_handover)', sz=10, color=TEAL, mono=True),

        cp('T4 ← CurrentTimeMillis()', sz=10, color=YELLOW, mono=True, sb=4),

        cp('─'*44, sz=8, color=BDRB, sb=6),
        p(c('Logged: ', sz=10, bold=True, color=WHITE),
          c('xn-prep=T2−T1', sz=10, color=YELLOW, mono=True),
          c('  psw=0ms', sz=10, color=RED, mono=True),
          c('  rel=T4−T3', sz=10, color=TEAL, mono=True)),
        p(c('         total=T4−T1', sz=10, color=ORANGE, bold=True, mono=True)),
    ]

def tgt_content():
    def c(txt, sz=10, bold=False, color=WHITE, mono=False, ital=False):
        return r(txt, sz=sz, bold=bold, color=color, mono=mono, ital=ital)
    def cp(txt, sz=10, bold=False, color=WHITE, mono=False, sb=0, ital=False):
        return p(c(txt, sz=sz, bold=bold, color=color, mono=mono, ital=ital), sb=sb)
    return [
        cp('XnTask::handleConnection(fd)', sz=11, bold=True, color=GREEN, mono=True),
        cp('─'*44, sz=8, color=BDRG),

        cp('← RecvMsg(fd)', sz=10, color=GRAY, mono=True, sb=4),
        cp('  receives XnHandoverRequest JSON', sz=10, color=WHITE),

        cp('Parse: ueId, amfUeNgapId,', sz=10, color=GRAY, mono=True, sb=6),
        cp('       ranUeNgapId, sliceSst,', sz=10, color=GRAY, mono=True),
        cp('       sourceGnb', sz=10, color=GRAY, mono=True),

        cp('if dispatcherAddress.empty():', sz=10, color=WHITE, mono=True, sb=6),
        cp('  // Baseline 1 path', sz=10, color=GRAY, mono=True),
        cp('  selectedAmf = "127.0.0.5"', sz=10, color=GREEN, mono=True),
        cp('  pswMs = 0.0', sz=10, color=GREEN, mono=True),
        cp('else:', sz=10, color=WHITE, mono=True, sb=2),
        cp('  ContactDispatcher(addr,port)', sz=10, color=PURPLE, mono=True),
        cp('  pswMs ← measured', sz=10, color=PURPLE, mono=True),

        cp('Build XnHandoverAck JSON:', sz=10, bold=True, color=WHITE, sb=6),
        cp('  { type:"XnHandoverAck",', sz=10, color=GRAY, mono=True),
        cp('    ueId, sliceSst,', sz=10, color=GRAY, mono=True),
        cp('    status:"OK",', sz=10, color=GREEN, mono=True),
        cp('    targetCell: config->name,', sz=10, color=GRAY, mono=True),
        cp('    selectedAmf, pswLatencyMs }', sz=10, color=YELLOW, mono=True),

        cp('→ SendMsg(fd, ack)', sz=10, color=GREEN, mono=True, sb=6),
        cp('→ log: HandoverAck | psw=0.1ms', sz=10, color=GRAY, ital=True),
    ]

def aft_content():
    def c(txt, sz=10, bold=False, color=WHITE, mono=False, ital=False):
        return r(txt, sz=sz, bold=bold, color=color, mono=mono, ital=ital)
    def cp(txt, sz=10, bold=False, color=WHITE, mono=False, sb=0, ital=False):
        return p(c(txt, sz=sz, bold=bold, color=color, mono=mono, ital=ital), sb=sb)
    return [
        cp('After RRC Release  →  UE: CM-IDLE', sz=11, bold=True, color=PURPLE),
        cp('─'*44, sz=8, color=BDRP),

        cp('UE detects uplink data pending', sz=10, color=WHITE, sb=6),
        cp('→ sends Service Request to gnb2', sz=10, color=BLUE),

        cp('gnb2: handleInitialNasTransport()', sz=10, color=PURPLE, mono=True, sb=6),
        cp('  extractSliceInfoAndModifyPdu()', sz=10, color=GRAY, mono=True),
        cp('  → requestedSliceType = -1', sz=10, color=RED, mono=True),
        cp('    (Service Req has no NSSAI)', sz=10, color=GRAY, ital=True),

        cp('selectAmf(ueId, -1):', sz=10, color=WHITE, mono=True, sb=6),
        cp('  no slice match found', sz=10, color=GRAY, mono=True),
        cp('  → fallback: anyConnected AMF', sz=10, color=GREEN, mono=True),
        cp('  ✓ fixed in nnsf.cpp', sz=10, color=GREEN, bold=True),

        cp('AMF → InitialContextSetupReq', sz=10, color=TEAL, mono=True, sb=6),
        cp('gnb2 processes, sends response', sz=10, color=WHITE),

        cp('AMF → Service Accept → UE', sz=10, color=GREEN, bold=True, sb=6),
        cp('─'*44, sz=8, color=BDRP, sb=4),
        cp('UE: MM-REGISTERED/NORMAL-SVC ✓', sz=10, bold=True, color=GREEN),
        cp('PDU session PSI[1] resumed   ✓', sz=10, bold=True, color=GREEN),
    ]

# ── OOXML boilerplate ──────────────────────────────────────────────────────────
CONTENT_TYPES = '''\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml"
    ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml"
    ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml"
    ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml"
    ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/theme/theme1.xml"
    ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
</Types>'''

ROOT_RELS = '''\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="ppt/presentation.xml"/>
</Relationships>'''

PRESENTATION = f'''\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  saveSubsetFonts="1">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
  <p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>
  <p:sldSz cx="{SW}" cy="{SH}"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>'''

PRES_RELS = '''\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
    Target="slideMasters/slideMaster1.xml"/>
  <Relationship Id="rId2"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
    Target="slides/slide1.xml"/>
  <Relationship Id="rId3"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
    Target="theme/theme1.xml"/>
</Relationships>'''

SLIDE_RELS = '''\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
    Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>'''

SLIDE_LAYOUT = '''\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  type="blank" preserve="1">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>
    <a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
  </p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>'''

LAYOUT_RELS = '''\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
    Target="../slideMasters/slideMaster1.xml"/>
</Relationships>'''

SLIDE_MASTER = '''\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>
    <a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
  </p:spTree></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1"
    accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5"
    accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst>
    <p:sldLayoutId id="2147483649" r:id="rId1"/>
  </p:sldLayoutIdLst>
  <p:txStyles>
    <p:titleStyle><a:lstStyle/></p:titleStyle>
    <p:bodyStyle><a:lstStyle/></p:bodyStyle>
    <p:otherStyle><a:lstStyle/></p:otherStyle>
  </p:txStyles>
</p:sldMaster>'''

MASTER_RELS = '''\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
    Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
    Target="../theme/theme1.xml"/>
</Relationships>'''

THEME = '''\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office Theme">
  <a:themeElements>
    <a:clrScheme name="Office">
      <a:dk1><a:sysClr lastClr="000000" val="windowText"/></a:dk1>
      <a:lt1><a:sysClr lastClr="ffffff" val="window"/></a:lt1>
      <a:dk2><a:srgbClr val="1F497D"/></a:dk2>
      <a:lt2><a:srgbClr val="EEECE1"/></a:lt2>
      <a:accent1><a:srgbClr val="4F81BD"/></a:accent1>
      <a:accent2><a:srgbClr val="C0504D"/></a:accent2>
      <a:accent3><a:srgbClr val="9BBB59"/></a:accent3>
      <a:accent4><a:srgbClr val="8064A2"/></a:accent4>
      <a:accent5><a:srgbClr val="4BACC6"/></a:accent5>
      <a:accent6><a:srgbClr val="F79646"/></a:accent6>
      <a:hlink><a:srgbClr val="0000FF"/></a:hlink>
      <a:folHlink><a:srgbClr val="800080"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="Office">
      <a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>
      <a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="Office"><a:fillStyleLst>
      <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
      <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
      <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
    </a:fillStyleLst>
    <a:lnStyleLst>
      <a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
      <a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
      <a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
    </a:lnStyleLst>
    <a:effectStyleLst>
      <a:effectStyle><a:effectLst/></a:effectStyle>
      <a:effectStyle><a:effectLst/></a:effectStyle>
      <a:effectStyle><a:effectLst/></a:effectStyle>
    </a:effectStyleLst>
    <a:bgFillStyleLst>
      <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
      <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
      <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
    </a:bgFillStyleLst>
    </a:fmtScheme>
  </a:themeElements>
</a:theme>'''

# ── Build PPTX ────────────────────────────────────────────────────────────────
def build(path):
    slide = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + slide_xml()
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',                    CONTENT_TYPES)
        z.writestr('_rels/.rels',                            ROOT_RELS)
        z.writestr('ppt/presentation.xml',                   PRESENTATION)
        z.writestr('ppt/_rels/presentation.xml.rels',        PRES_RELS)
        z.writestr('ppt/theme/theme1.xml',                   THEME)
        z.writestr('ppt/slideMasters/slideMaster1.xml',      SLIDE_MASTER)
        z.writestr('ppt/slideMasters/_rels/slideMaster1.xml.rels', MASTER_RELS)
        z.writestr('ppt/slideLayouts/slideLayout1.xml',      SLIDE_LAYOUT)
        z.writestr('ppt/slideLayouts/_rels/slideLayout1.xml.rels', LAYOUT_RELS)
        z.writestr('ppt/slides/slide1.xml',                  slide)
        z.writestr('ppt/slides/_rels/slide1.xml.rels',       SLIDE_RELS)
    print(f'Saved: {path}')

if __name__ == '__main__':
    out = os.path.join(os.path.dirname(__file__), 'Baseline1_Handover_Flow.pptx')
    build(out)
