#!/usr/bin/env python3
"""
WoBo40 KiCad 回路図ジェネレータ

単4電池1本(1.5V / NiMH 1.2V)で動作する 47キー + トラックボール の
ZMK キーボード用回路図を生成する。

  - MCU      : Seeed XIAO nRF52840 Plus
  - 電源      : TPS61021A で 3.3V へ昇圧 → XIAO の VBAT へ
  - マトリクス : 電気 8行 x 6列 (物理 4行 x 12列の行2段重ね)
  - トラボ    : PAW3222 を 6ピンコネクタで外付け

シンボル定義は cormoran/dya-dash-keyboard と Seeed OPL から取り込む。

使い方:
    python3 tools/gen_schematic.py --dya <dya-dash-keyboardのパス> \
                                   --opl <OPL_Kicad_Libraryのパス> \
                                   --out hardware/wobo40
"""
from __future__ import annotations

import argparse
import copy
import math
import uuid
from pathlib import Path

from kiutils.schematic import Schematic
from kiutils.symbol import SymbolLib
from kiutils.items.schitems import (
    SchematicSymbol,
    Connection,
    GlobalLabel,
    LocalLabel,
    NoConnect,
)
from kiutils.items.common import Position, Property, Effects, Font, Justify, Stroke
from kiutils.items.schitems import SymbolProjectInstance, SymbolProjectPath

# --------------------------------------------------------------------------
# 設計パラメータ
# --------------------------------------------------------------------------

PROJECT = "wobo40"

# XIAO Plus のピン割当 (PCB配線しやすいよう機能別・連番に整理済み)
#   上辺(左→右): 行8本 → ADC → トラボ3本
#   下辺(左→右): 電源 → 列6本 → MOTION
XIAO_NETS = {
    "1": "Row0",              # D0
    "2": "Row2",              # D1
    "3": "Row4",              # D2
    "4": "Row6",              # D3
    "5": "INPUT_VOLTAGE_L",   # D4  (AIN2)
    "6": "SDIO_L",            # D5
    "7": "SCLK_L",            # D6
    "8": "MOTION_L",          # D7
    "9": "Col4",              # D8
    "10": "Col2",             # D9
    "11": "Col0",             # D10
    "12": "3.3V_L",           # 3V3_OUT
    "13": "GNDL",             # GND
    "14": "VBUS_L",           # VBUS
    "15": "Row1",             # D11
    "16": "Row3",             # D12
    "17": "Row5",             # D13
    "18": "Row7",             # D14 (NFC1)
    "19": "CS",               # D15 (NFC2)
    "20": None,               # D16 (P0.31) 電池電圧測定用 → 使用禁止
    "21": "Col5",             # D17
    "22": "Col3",             # D18
    "23": "Col1",             # D19
    "24": None,               # SWDIO
    "25": None,               # SWDCLK
    "26": None,               # EN
    "27": "GNDL",             # GND
    "28": "BAT_L",            # VBAT ← 昇圧出力
    "29": "GNDL",             # GND
}

# トラックボール接続 (6ピン)
JL1_NETS = ["3.3V_L", "CS", "MOTION_L", "SDIO_L", "SCLK_L", "GNDL"]

# マトリクス: 物理4行x12列, 電気8行x6列
#   物理(r,c): c<=5 → (row=r,   col=c)
#              c>=6 → (row=r+4, col=c-6)
#   トラックボール位置 = 物理(3,8) → 電気 Row7 x Col2 はキーなし
N_PHYS_ROWS, N_PHYS_COLS = 4, 12
TRACKBALL_PHYS = (3, 8)

COL_PITCH = 25.4
ROW_PITCH = 25.4
BLOCK_GAP = 50.8          # 左ブロックと右ブロックの間隔
MATRIX_X0 = 45.0
MATRIX_Y0 = 190.0

# 電源部の定数。TPS61021A は VFB=0.5V なので
#   Vout = 0.5 * (1 + RL5/RL6) = 0.5 * (1 + 560/100) = 3.3V
FB_TOP = "560k"
FB_BOTTOM = "100k"


def _uuid() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# シンボル配置ヘルパ
# --------------------------------------------------------------------------


def pin_xy(sym_x: float, sym_y: float, angle: float, px: float, py: float):
    """ライブラリ座標のピンを回路図座標へ変換 (回転CCW → Y反転)。"""
    a = math.radians(angle or 0)
    ca, sa = round(math.cos(a), 6), round(math.sin(a), 6)
    return (sym_x + (px * ca - py * sa), sym_y - (px * sa + py * ca))


def pin_dir(rot: float):
    """ライブラリのピン回転から、配線を伸ばす向き(回路図座標)を返す。"""
    return {0: (-1.0, 0.0), 180: (1.0, 0.0), 270: (0.0, -1.0), 90: (0.0, 1.0)}[
        int(rot or 0) % 360
    ]


def _effects(size=1.27, justify=None, hide=False):
    e = Effects(font=Font(width=size, height=size), hide=hide)
    if justify:
        e.justify = Justify(horizontally=justify)
    return e


class Builder:
    """回路図を組み立てるユーティリティ。"""

    def __init__(self, lib_symbols):
        self.sch = Schematic.create_new()
        # kiutils は KiCad 6 系の書式で出力するため、あえて古いバージョンを名乗り
        # KiCad 側の自動アップグレードに任せる (初回オープン時に変換される)
        self.sch.version = "20211014"
        self.sch.generator = "gen_schematic.py"
        self.sch.uuid = _uuid()
        self.sch.paper.paperSize = "A2"
        self.sch.libSymbols = list(lib_symbols.values())
        self.lib = lib_symbols
        self._pins = {}
        for lid, ls in lib_symbols.items():
            self._pins[lid] = {
                p.number: (p.position.X, p.position.Y, p.position.angle or 0)
                for u in ls.units
                for p in u.pins
            }

    # ---- 部品 ----------------------------------------------------------
    def place(self, lib_id, ref, value, x, y, angle=0, footprint="", mirror=None,
              hide_value=False, hide_ref=False):
        nick, entry = lib_id.split(":", 1)
        s = SchematicSymbol(
            libraryNickname=nick,
            entryName=entry,
            position=Position(X=x, Y=y, angle=angle),
            unit=1,
            inBom=True,
            onBoard=True,
            uuid=_uuid(),
        )
        if mirror:
            s.mirror = mirror
        s.properties = [
            Property(key="Reference", value=ref,
                     position=Position(X=x, Y=y - 8.89, angle=0),
                     effects=_effects(hide=hide_ref)),
            Property(key="Value", value=value,
                     position=Position(X=x, Y=y + 8.89, angle=0),
                     effects=_effects(hide=hide_value)),
            Property(key="Footprint", value=footprint,
                     position=Position(X=x, Y=y, angle=0),
                     effects=_effects(hide=True)),
            Property(key="Datasheet", value="",
                     position=Position(X=x, Y=y, angle=0),
                     effects=_effects(hide=True)),
        ]
        s.instances = [
            SymbolProjectInstance(
                name=PROJECT,
                paths=[SymbolProjectPath(sheetInstancePath=f"/{self.sch.uuid}",
                                         reference=ref, unit=1)],
            )
        ]
        self.sch.schematicSymbols.append(s)
        return s

    def pin_of(self, sym, number):
        px, py, _ = self._pins[sym.libId][number]
        return pin_xy(sym.position.X, sym.position.Y, sym.position.angle or 0, px, py)

    def pin_rot(self, sym, number):
        return self._pins[sym.libId][number][2]

    # ---- 配線 ----------------------------------------------------------
    def wire(self, p1, p2):
        if round(p1[0], 3) == round(p2[0], 3) and round(p1[1], 3) == round(p2[1], 3):
            return                       # 長さ0の配線は作らない
        c = Connection(type="wire", uuid=_uuid(), stroke=Stroke(width=0, type="default"))
        c.points = [Position(X=round(p1[0], 3), Y=round(p1[1], 3)),
                    Position(X=round(p2[0], 3), Y=round(p2[1], 3))]
        self.sch.graphicalItems.append(c)

    def glabel(self, name, x, y, angle=0, justify=None):
        g = GlobalLabel(text=name, position=Position(X=x, Y=y, angle=angle),
                        uuid=_uuid(), effects=_effects(justify=justify))
        self.sch.globalLabels.append(g)

    def label_pin(self, sym, number, net, stub=5.08):
        """部品ピンから短い配線を出して、その先にグローバルラベルを置く。"""
        x, y = self.pin_of(sym, number)
        dx, dy = pin_dir(self.pin_rot(sym, number))
        ex, ey = x + dx * stub, y + dy * stub
        self.wire((x, y), (ex, ey))
        if dx < 0:
            self.glabel(net, ex, ey, 180, "right")
        elif dx > 0:
            self.glabel(net, ex, ey, 0, "left")
        elif dy < 0:
            self.glabel(net, ex, ey, 90, "left")
        else:
            self.glabel(net, ex, ey, 270, "left")

    def no_connect(self, sym, number):
        """意図的に未接続のピンへ「未接続フラグ」を置く (ERC対策)。"""
        x, y = self.pin_of(sym, number)
        self.sch.noConnects.append(
            NoConnect(position=Position(X=round(x, 3), Y=round(y, 3)), uuid=_uuid())
        )

    def gnd(self, x, y):
        """GNDシンボルを置いて座標(接続点)を返す。"""
        s = self.place("power:GND", "#PWR", "GND", x, y, hide_ref=True, hide_value=True)
        return self.pin_of(s, "1")


# --------------------------------------------------------------------------
# ライブラリ取り込み
# --------------------------------------------------------------------------

NEEDED_FROM_DYA = [
    "Device:C", "Device:D", "Device:L", "Device:R", "Device:Q_PMOS_GSD",
    "Connector:Conn_01x02_Pin", "Connector:Conn_01x06_Socket",
    "Switch:SW_Push_45deg", "Switch:SW_SPDT", "power:GND",
    "0_dya-kbd:TPS61021A", "0_dya-kbd:BU42",
]

XIAO_LIB_ID = "0_Seeed_Studio_XIAO_Series:XIAO-nRF52840_Plus_SMD"


def load_lib_symbols(dya_root: Path, opl_root: Path):
    src = dya_root / "hardware/dya-dash-v3/left/dya-left.kicad_sch"
    if not src.exists():
        raise SystemExit(f"DYAの回路図が見つかりません: {src}")
    donor = Schematic().from_file(str(src))
    have = {ls.libId: ls for ls in donor.libSymbols}

    out = {}
    for lid in NEEDED_FROM_DYA:
        if lid not in have:
            raise SystemExit(f"シンボルが見つかりません: {lid}")
        out[lid] = copy.deepcopy(have[lid])

    # XIAO Plus は Seeed OPL から
    symfile = opl_root / "Seeed Studio XIAO Series Library/Seeed_Studio_XIAO_Series.kicad_sym"
    if not symfile.exists():
        raise SystemExit(f"OPLライブラリが見つかりません: {symfile}")
    lib = SymbolLib().from_file(str(symfile))
    xiao = None
    for s in lib.symbols:
        if s.entryName == "XIAO-nRF52840_Plus_SMD":
            xiao = copy.deepcopy(s)
            break
    if xiao is None:
        raise SystemExit("XIAO-nRF52840_Plus_SMD が OPL に見つかりません")
    xiao.entryName = "XIAO-nRF52840_Plus_SMD"
    xiao.libraryNickname = "0_Seeed_Studio_XIAO_Series"
    out[XIAO_LIB_ID] = xiao

    # PWR_FLAG は標準ライブラリに頼らず power:GND を複製して作る
    # (ERCの「電源入力ピンが電源出力ピンで駆動されていない」対策)
    flag = copy.deepcopy(out["power:GND"])
    flag.entryName = "PWR_FLAG"
    for u in flag.units:
        u.entryName = "PWR_FLAG"
        for p in u.pins:
            p.electricalType = "power_out"
        for gi in u.graphicItems:
            pts = getattr(gi, "points", None)
            if pts is None:
                continue
            arrow = [(0, 0), (0, 1.27), (-1.016, 1.905), (0, 2.54), (1.016, 1.905), (0, 1.27)]
            base = copy.deepcopy(pts[0])
            gi.points = []
            for ax, ay in arrow:
                q = copy.deepcopy(base)
                q.X, q.Y = ax, ay
                gi.points.append(q)
    for pr in flag.properties:
        if pr.key == "Reference":
            pr.value = "#FLG"
        elif pr.key == "Value":
            pr.value = "PWR_FLAG"
    out["power:PWR_FLAG"] = flag
    return out


# --------------------------------------------------------------------------
# 各セクションの生成
# --------------------------------------------------------------------------


def build_mcu(b: Builder, x=70.0, y=70.0):
    u1 = b.place(XIAO_LIB_ID, "U1", "XIAO-nRF52840-Plus-SMD", x, y,
                 footprint="0_Seeed_Studio_XIAO_Series:XIAO-nRF52840-Plus-SMD")
    for num, net in XIAO_NETS.items():
        if net is None:
            b.no_connect(u1, num)        # D16 / SWDIO / SWDCLK / EN は未接続
            continue
        b.label_pin(u1, num, net)
    return u1


def build_trackball_conn(b: Builder, x=60.0, y=155.0):
    j = b.place("Connector:Conn_01x06_Socket", "JL1", "TrackBall", x, y,
                footprint="Connector_JST:JST_SH_SM06B-SRSS-TB_1x06-1MP_P1.00mm_Horizontal")
    for i, net in enumerate(JL1_NETS, start=1):
        b.label_pin(j, str(i), net)
    return j


def build_matrix(b: Builder):
    """47キー分の スイッチ + ダイオード + 行/列配線 を生成。"""
    sw_n = d_n = 0
    for block in (0, 1):                       # 0=左ブロック 1=右ブロック
        bx = MATRIX_X0 + block * (6 * COL_PITCH + BLOCK_GAP)
        for erow in range(4):                  # 電気行 (ブロック内 0..3)
            row_net = f"Row{erow + block * 4}"
            ry = MATRIX_Y0 + erow * ROW_PITCH
            # 行の水平配線
            b.wire((bx - 12.7, ry), (bx + 5 * COL_PITCH + 10.16, ry))
            b.glabel(row_net, bx - 12.7, ry, 180, "right")
            for ecol in range(6):
                phys_c = ecol + block * 6
                if (erow + block * 4, ecol) == (7, 2):
                    continue               # トラックボール位置はキーなし
                cx = bx + ecol * COL_PITCH
                sw_n += 1
                d_n += 1
                sw = b.place("Switch:SW_Push_45deg", f"SW{sw_n}", "SW_Push",
                             cx + 2.54, ry - 12.7,
                             footprint="")
                d = b.place("Device:D", f"D{d_n}", "1N4148W",
                            cx + 5.08, ry - 3.81, angle=90,
                            footprint="Diode_SMD:D_SOD-123")
                # スイッチ pin2 → ダイオード アノード
                b.wire(b.pin_of(sw, "2"), b.pin_of(d, "2"))
                # ダイオード カソード は行配線上に乗る (座標一致)
            # 列の縦配線 (ブロックごとに1本、4行を貫く)
            if erow == 3:
                for ecol in range(6):
                    cx = bx + ecol * COL_PITCH
                    top = MATRIX_Y0 - 25.4
                    bot = MATRIX_Y0 + 3 * ROW_PITCH - 15.24
                    b.wire((cx, top), (cx, bot))
                    b.glabel(f"Col{ecol}", cx, top, 90, "left")


def build_power(b: Builder, x0=250.0, y0=45.0):
    """単4電池1本 → TPS61021A で3.3Vへ昇圧 → XIAO VBAT。"""
    fp_r = "Resistor_SMD:R_0603_1608Metric"
    fp_c = "Capacitor_SMD:C_0603_1608Metric"

    # --- 電池コネクタ と 逆接保護 -------------------------------------
    jl2 = b.place("Connector:Conn_01x02_Pin", "JL2", "AAA x1", x0, y0 + 10,
                  footprint="")
    b.label_pin(jl2, "1", "VBAT_RAW")
    p2 = b.pin_of(jl2, "2")
    g = b.gnd(p2[0] + 7.62, p2[1] + 7.62)
    b.wire(p2, (g[0], p2[1]))
    b.wire((g[0], p2[1]), g)

    ql1 = b.place("Device:Q_PMOS_GSD", "QL1", "DMG3415U", x0 + 40, y0 + 10,
                  footprint="Package_TO_SOT_SMD:SOT-23")
    b.label_pin(ql1, "3", "VBAT_RAW")     # D = 電池側
    b.label_pin(ql1, "2", "VIN_B")        # S = 昇圧入力側
    rl1 = b.place("Device:R", "RL1", "150k", x0 + 35, y0 + 30, footprint=fp_r)
    b.wire(b.pin_of(ql1, "1"), (b.pin_of(rl1, "1")[0], b.pin_of(ql1, "1")[1]))
    b.wire((b.pin_of(rl1, "1")[0], b.pin_of(ql1, "1")[1]), b.pin_of(rl1, "1"))
    g = b.gnd(b.pin_of(rl1, "2")[0], b.pin_of(rl1, "2")[1] + 5.08)
    b.wire(b.pin_of(rl1, "2"), g)

    # --- 電池電圧モニタ (1M / 470k 分圧 → ADC) -------------------------
    rl2 = b.place("Device:R", "RL2", "1M", x0, y0 + 55, footprint=fp_r)
    rl3 = b.place("Device:R", "RL3", "470k", x0, y0 + 72, footprint=fp_r)
    b.label_pin(rl2, "1", "VIN_B")
    b.wire(b.pin_of(rl2, "2"), b.pin_of(rl3, "1"))
    mid = b.pin_of(rl2, "2")
    b.wire(mid, (mid[0] - 12.7, mid[1]))
    b.glabel("INPUT_VOLTAGE_L", mid[0] - 12.7, mid[1], 180, "right")
    cl1 = b.place("Device:C", "CL1", "10nF", x0 + 15, y0 + 72, footprint=fp_c)
    b.wire(b.pin_of(cl1, "1"), (b.pin_of(cl1, "1")[0], mid[1]))
    b.wire((b.pin_of(cl1, "1")[0], mid[1]), mid)
    for r in (rl3, cl1):
        p = b.pin_of(r, "2")
        g = b.gnd(p[0], p[1] + 5.08)
        b.wire(p, g)

    # --- 昇圧コンバータ -------------------------------------------------
    ul1 = b.place("0_dya-kbd:TPS61021A", "UL1", "TPS61021A", x0 + 115, y0 + 30,
                  footprint="Package_SON:WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm")
    ll1 = b.place("Device:L", "LL1", "0.47uH", x0 + 90, y0 + 22.5, angle=90,
                  footprint="Inductor_SMD:L_1008_2520Metric")
    # 電池レール → コイル → SW ピン
    b.label_pin(ll1, "1", "VIN_B")
    sw6 = b.pin_of(ul1, "6")
    sw7 = b.pin_of(ul1, "7")
    l2 = b.pin_of(ll1, "2")
    b.wire(l2, (sw7[0] + 7.62, l2[1]))
    b.wire((sw7[0] + 7.62, l2[1]), (sw7[0] + 7.62, sw7[1]))
    b.wire((sw7[0] + 7.62, sw7[1]), sw7)
    b.wire((sw7[0] + 7.62, sw7[1]), (sw7[0] + 7.62, sw6[1]))
    b.wire((sw7[0] + 7.62, sw6[1]), sw6)
    b.label_pin(ul1, "8", "VIN_B")           # VIN
    b.label_pin(ul1, "5", "EN_B")            # EN

    # 入力コンデンサ
    cl2 = b.place("Device:C", "CL2", "10uF", x0 + 75, y0 + 55, footprint=fp_c)
    b.label_pin(cl2, "1", "VIN_B")
    p = b.pin_of(cl2, "2"); g = b.gnd(p[0], p[1] + 5.08); b.wire(p, g)

    # GND (AGND / サーマルパッド)
    for num in ("1", "9"):
        p = b.pin_of(ul1, num)
        dx, dy = pin_dir(b.pin_rot(ul1, num))
        e = (p[0] + dx * 5.08, p[1] + dy * 5.08)
        b.wire(p, e)
        g = b.gnd(e[0], e[1] + (5.08 if dy >= 0 else -5.08) if dx == 0 else e[1] + 5.08)
        b.wire(e, g)

    # 出力
    for num in ("3", "4"):
        b.label_pin(ul1, num, "VOUT_B")

    # 出力コンデンサ (VOUTの直近に置くこと)
    for i, ref in enumerate(("CL4", "CL5")):
        c = b.place("Device:C", ref, "10uF", x0 + 60 + i * 15, y0 + 85, footprint=fp_c)
        b.label_pin(c, "1", "VOUT_B")
        p = b.pin_of(c, "2"); g = b.gnd(p[0], p[1] + 5.08); b.wire(p, g)

    # FB分圧: Vout = 0.5V * (1 + RL5/RL6) = 3.3V
    rl5 = b.place("Device:R", "RL5", FB_TOP, x0 + 150, y0 + 12, footprint=fp_r)
    rl6 = b.place("Device:R", "RL6", FB_BOTTOM, x0 + 150, y0 + 30, footprint=fp_r)
    b.label_pin(rl5, "1", "VOUT_B")
    b.wire(b.pin_of(rl5, "2"), b.pin_of(rl6, "1"))
    fb = b.pin_of(rl5, "2")
    b.wire(fb, (fb[0] - 20.32, fb[1]))
    b.glabel("FB_B", fb[0] - 20.32, fb[1], 180, "right")
    b.label_pin(ul1, "2", "FB_B")
    p = b.pin_of(rl6, "2"); g = b.gnd(p[0], p[1] + 5.08); b.wire(p, g)
    # FB フィードフォワード コンデンサ (RL5 と並列)
    cl3 = b.place("Device:C", "CL3", "20pF", x0 + 168, y0 + 21, footprint=fp_c)
    b.label_pin(cl3, "1", "VOUT_B")
    b.label_pin(cl3, "2", "FB_B")

    # --- 電源スイッチ と 低電圧カットオフ (BU42) ------------------------
    swb = b.place("Switch:SW_SPDT", "SW_BATL1", "MSK12C02", x0 + 40, y0 + 100,
                  footprint="")
    b.label_pin(swb, "1", "VIN_B")        # 常時ON側
    b.label_pin(swb, "3", "UVLO_OUT")     # 低電圧カットオフ側
    rl4 = b.place("Device:R", "RL4", "470k", x0 + 62, y0 + 100, angle=90, footprint=fp_r)
    b.wire(b.pin_of(swb, "2"), b.pin_of(rl4, "1"))
    p = b.pin_of(rl4, "2")
    b.wire(p, (p[0] + 10.16, p[1]))
    b.glabel("EN_B", p[0] + 10.16, p[1], 0, "left")

    ul2 = b.place("0_dya-kbd:BU42", "UL2", "BU4210", x0 + 110, y0 + 100,
                  footprint="Package_SO:SSOP-5_1.6x1.6mm_P0.5mm")
    b.label_pin(ul2, "1", "UVLO_OUT")     # Vout
    b.label_pin(ul2, "2", "VIN_B")        # VDD
    for n in ("4", "5"):
        b.no_connect(ul2, n)             # N.C. / CT は未接続
    p = b.pin_of(ul2, "3")
    dx, dy = pin_dir(b.pin_rot(ul2, "3"))
    e = (p[0] + dx * 5.08, p[1] + dy * 5.08)
    b.wire(p, e); g = b.gnd(e[0], e[1] + 5.08); b.wire(e, g)

    # --- USB逆流防止 -----------------------------------------------------
    ql2 = b.place("Device:Q_PMOS_GSD", "QL2", "DMG3415U", x0 + 175, y0 + 100,
                  footprint="Package_TO_SOT_SMD:SOT-23")
    b.label_pin(ql2, "3", "VOUT_B")       # D = 昇圧出力側
    b.label_pin(ql2, "2", "BAT_L")        # S = XIAO の VBAT へ
    b.label_pin(ql2, "1", "VBUS_L")       # G = USB検出
    rl7 = b.place("Device:R", "RL7", "150k", x0 + 158, y0 + 118, footprint=fp_r)
    b.label_pin(rl7, "1", "VBUS_L")
    p = b.pin_of(rl7, "2"); g = b.gnd(p[0], p[1] + 5.08); b.wire(p, g)


def build_pwr_flags(b: Builder, x=470.0, y=60.0):
    """ERC対策: 電源供給元であることを示す PWR_FLAG を置く。"""
    for i, net in enumerate(("VIN_B", "VOUT_B")):
        yy = y + i * 20.32
        f = b.place("power:PWR_FLAG", f"#FLG{i + 1}", "PWR_FLAG", x, yy,
                    hide_ref=True)
        p = b.pin_of(f, "1")
        b.wire(p, (p[0], p[1] + 5.08))
        b.glabel(net, p[0], p[1] + 5.08, 180, "right")


# --------------------------------------------------------------------------
# プロジェクトファイル / ライブラリテーブル
# --------------------------------------------------------------------------

KICAD_PRO = '''{
  "board": {"design_settings": {"defaults": {}}},
  "boards": [],
  "cvpcb": {"equivalence_files": []},
  "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
  "meta": {"filename": "wobo40.kicad_pro", "version": 3},
  "net_settings": {"classes": [{"name": "Default", "clearance": 0.2,
    "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3}]},
  "pcbnew": {"page_layout_descr_file": ""},
  "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
  "sheets": [],
  "text_variables": {}
}
'''

SYM_LIB_TABLE = '''(sym_lib_table
  (version 7)
  (lib (name "0_dya-kbd")(type "KiCad")(uri "${KIPRJMOD}/../lib/dya-kbd.kicad_sym")(options "")(descr "DYA Dash 由来 (TPS61021A / BU42)"))
  (lib (name "0_Seeed_Studio_XIAO_Series")(type "KiCad")(uri "${KIPRJMOD}/../lib/Seeed_Studio_XIAO_Series.kicad_sym")(options "")(descr "Seeed OPL"))
)
'''

FP_LIB_TABLE = '''(fp_lib_table
  (version 7)
  (lib (name "0_dya-kbd")(type "KiCad")(uri "${KIPRJMOD}/../lib/dya-kbd.pretty")(options "")(descr "DYA Dash 由来"))
  (lib (name "0_Seeed_Studio_XIAO_Series")(type "KiCad")(uri "${KIPRJMOD}/../lib/Seeed_Studio_XIAO_Series.pretty")(options "")(descr "Seeed OPL"))
)
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dya", required=True, type=Path)
    ap.add_argument("--opl", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    libs = load_lib_symbols(a.dya, a.opl)
    b = Builder(libs)

    build_mcu(b)
    build_trackball_conn(b)
    build_matrix(b)
    build_power(b)
    build_pwr_flags(b)

    a.out.mkdir(parents=True, exist_ok=True)
    sch_path = a.out / f"{PROJECT}.kicad_sch"
    b.sch.to_file(str(sch_path))

    (a.out / f"{PROJECT}.kicad_pro").write_text(KICAD_PRO, encoding="utf-8")
    (a.out / "sym-lib-table").write_text(SYM_LIB_TABLE, encoding="utf-8")
    (a.out / "fp-lib-table").write_text(FP_LIB_TABLE, encoding="utf-8")

    # 検証: 書き出したファイルを読み直せるか
    chk = Schematic().from_file(str(sch_path))
    n_sw = sum(1 for s in chk.schematicSymbols
               if any(p.key == "Reference" and p.value.startswith("SW")
                      and p.value != "SW_BATL1" for p in s.properties))
    n_d = sum(1 for s in chk.schematicSymbols
              if any(p.key == "Reference" and p.value.startswith("D") for p in s.properties))
    print(f"生成完了: {sch_path}")
    print(f"  部品総数   : {len(chk.schematicSymbols)}")
    print(f"  スイッチ    : {n_sw}  (期待 47)")
    print(f"  ダイオード  : {n_d}  (期待 47)")
    print(f"  配線       : {sum(1 for g in chk.graphicalItems if getattr(g, 'points', None))}")
    print(f"  グローバルラベル: {len(chk.globalLabels)}")


if __name__ == "__main__":
    main()
