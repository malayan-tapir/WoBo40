#!/usr/bin/env python3
"""
生成した回路図のネット接続を検証する。

KiCad を起動せずに、
  - 配線同士 / 配線とピン / 同名グローバルラベル
を結合してネットを構成し、期待どおりの接続になっているか確認する。

    python3 tools/check_netlist.py hardware/wobo40/wobo40.kicad_sch
"""
from __future__ import annotations

import math
import sys
from collections import defaultdict

from kiutils.schematic import Schematic

EPS = 0.01
FB_TOP_V, FB_BOT_V = "560k", "100k"


def key(p):
    return (round(p[0], 2), round(p[1], 2))


class UF:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def pin_xy(sx, sy, angle, px, py, mirror=None):
    a = math.radians(angle or 0)
    ca, sa = round(math.cos(a), 6), round(math.sin(a), 6)
    x, y = px, py
    if mirror == "y":
        x = -x
    elif mirror == "x":
        y = -y
    return (sx + (x * ca - y * sa), sy - (x * sa + y * ca))


def on_segment(pt, a, b):
    (x, y), (x1, y1), (x2, y2) = pt, a, b
    if abs(x1 - x2) < EPS:
        return abs(x - x1) < EPS and min(y1, y2) - EPS <= y <= max(y1, y2) + EPS
    if abs(y1 - y2) < EPS:
        return abs(y - y1) < EPS and min(x1, x2) - EPS <= x <= max(x1, x2) + EPS
    return False


def main(path):
    sch = Schematic().from_file(path)

    libpins = {}
    for ls in sch.libSymbols:
        libpins[ls.libId] = [
            (p.number, p.position.X, p.position.Y) for u in ls.units for p in u.pins
        ]

    segs = []
    for g in sch.graphicalItems:
        pts = getattr(g, "points", None)
        if pts and len(pts) == 2 and getattr(g, "type", "") == "wire":
            segs.append(((pts[0].X, pts[0].Y), (pts[1].X, pts[1].Y)))

    nc_points = {key((n.position.X, n.position.Y)) for n in sch.noConnects}

    uf = UF()
    for a, b in segs:
        uf.union(key(a), key(b))

    # ピンを配線へ結合 (端点一致 or 線分上)
    pin_at = defaultdict(list)   # point -> [(ref, pinnum)]
    unconnected = []
    for sym in sch.schematicSymbols:
        ref = next((p.value for p in sym.properties if p.key == "Reference"), "?")
        if sym.libId not in libpins:
            continue
        for num, px, py in libpins[sym.libId]:
            pt = pin_xy(sym.position.X, sym.position.Y, sym.position.angle,
                        px, py, sym.mirror)
            k = key(pt)
            pin_at[k].append((ref, num))
            hit = False
            for a, b in segs:
                if on_segment(pt, a, b):
                    uf.union(k, key(a))
                    hit = True
                    break
            if not hit and k not in nc_points and not ref.startswith(("#PWR", "#FLG")):
                unconnected.append((ref, num, k))

    # 同じ点にある複数ピンは直結
    for k, lst in pin_at.items():
        for other in lst[1:]:
            uf.union(k, k)

    # グローバルラベル → ネット名
    netname = {}
    for gl in sch.globalLabels:
        k = key((gl.position.X, gl.position.Y))
        netname.setdefault(uf.find(k), set()).add(gl.text) if False else None
        netname.setdefault(uf.find(k), set())
        netname[uf.find(k)].add(gl.text)

    # 電源シンボルはその Value がネット名として働く
    power_pts = []      # (netname, point)
    for sym in sch.schematicSymbols:
        if not sym.libId.startswith("power:"):
            continue
        val = next((p.value for p in sym.properties if p.key == "Value"), None)
        if not val or val == "PWR_FLAG":
            continue
        for num, px, py in libpins.get(sym.libId, []):
            power_pts.append((val, key(pin_xy(sym.position.X, sym.position.Y,
                                              sym.position.angle, px, py, sym.mirror))))

    # ラベル同士(同名)を結合
    byname = defaultdict(list)
    for gl in sch.globalLabels:
        byname[gl.text].append(key((gl.position.X, gl.position.Y)))
    for val, pt in power_pts:
        byname[val].append(pt)
    for name, pts in byname.items():
        for q in pts[1:]:
            uf.union(pts[0], q)

    # ネット構成
    net_of_pin = {}
    for k, lst in pin_at.items():
        r = uf.find(k)
        for ref, num in lst:
            net_of_pin[(ref, num)] = r
    names = defaultdict(set)
    for gl in sch.globalLabels:
        names[uf.find(key((gl.position.X, gl.position.Y)))].add(gl.text)
    for val, pt in power_pts:
        names[uf.find(pt)].add(val)

    def net(ref, num):
        r = net_of_pin.get((ref, num))
        if r is None:
            return None
        n = names.get(r)
        return sorted(n)[0] if n else f"<unnamed:{r}>"

    ok = True
    print(f"=== 未接続ピン (意図的な未接続フラグ {len(nc_points)}個を除く) ===")
    if unconnected:
        ok = False
        for ref, num, k in unconnected[:20]:
            print(f"  ! {ref} pin{num} @ {k}")
        print(f"  合計 {len(unconnected)} 本")
    else:
        print("  なし")

    # スイッチ + ダイオードの検証
    print("\n=== マトリクス検証 ===")
    sw_refs = sorted([p.value for s in sch.schematicSymbols
                      for p in s.properties
                      if p.key == "Reference" and p.value.startswith("SW")
                      and p.value != "SW_BATL1"],
                     key=lambda r: int(r[2:]))
    pairs = {}
    bad = 0
    for i, sw in enumerate(sw_refs, start=1):
        d = f"D{i}"
        col = net(sw, "1")
        row = net(d, "1")        # カソード
        link_sw = net(sw, "2")
        link_d = net(d, "2")     # アノード
        problems = []
        if not (col or "").startswith("Col"):
            problems.append(f"pin1のネットが列でない: {col}")
        if not (row or "").startswith("Row"):
            problems.append(f"{d}カソードのネットが行でない: {row}")
        if link_sw != link_d:
            problems.append(f"SW-D間が未接続 ({link_sw} != {link_d})")
        if problems:
            bad += 1
            if bad <= 8:
                print(f"  ! {sw}/{d}: " + " / ".join(problems))
        else:
            pairs[(row, col)] = sw
    if bad:
        ok = False
        print(f"  異常 {bad} 個")
    else:
        print(f"  {len(sw_refs)}キー すべて Row x Col に正しく接続")

    # 電気マトリクスの網羅性
    print("\n=== 電気マトリクス (8行x6列) の使用状況 ===")
    missing = []
    for r in range(8):
        line = []
        for c in range(6):
            k = (f"Row{r}", f"Col{c}")
            line.append("O" if k in pairs else ".")
            if k not in pairs:
                missing.append(k)
        print(f"  Row{r}: " + " ".join(line))
    print(f"  未使用: {missing}  (期待: Row7 x Col2 のみ = トラックボール位置)")
    if missing != [("Row7", "Col2")]:
        ok = False
        print("  ! 未使用セルが期待と違います")

    # XIAO のピンネット
    print("\n=== U1 (XIAO) ピンネット ===")
    expect = {
        "1": "Row0", "2": "Row2", "3": "Row4", "4": "Row6", "5": "INPUT_VOLTAGE_L",
        "6": "SDIO_L", "7": "SCLK_L", "8": "MOTION_L", "9": "Col4", "10": "Col2",
        "11": "Col0", "12": "3.3V_L", "13": "GNDL", "14": "VBUS_L", "15": "Row1",
        "16": "Row3", "17": "Row5", "18": "Row7", "19": "CS", "21": "Col5",
        "22": "Col3", "23": "Col1", "27": "GNDL", "28": "BAT_L", "29": "GNDL",
    }
    mismatch = 0
    for num, want in sorted(expect.items(), key=lambda kv: int(kv[0])):
        got = net("U1", num)
        mark = "OK " if got == want else "NG "
        if got != want:
            mismatch += 1
            ok = False
        if got != want:
            print(f"  {mark} pin{num}: 期待={want} 実際={got}")
    print(f"  一致 {len(expect) - mismatch}/{len(expect)}")

    # 電源部の要点
    print("\n=== 電源部ネット ===")
    for ref, num, label in (
        ("UL1", "8", "VIN (昇圧入力)"), ("UL1", "7", "SW"), ("UL1", "6", "SW"),
        ("UL1", "3", "VOUT"), ("UL1", "4", "VOUT"), ("UL1", "2", "FB"),
        ("UL1", "5", "EN"), ("UL1", "1", "AGND"), ("UL1", "9", "GND(パッド)"),
        ("LL1", "1", "コイル 電池側"), ("LL1", "2", "コイル SW側"),
        ("QL1", "3", "逆接保護 D(電池)"), ("QL1", "2", "逆接保護 S(負荷)"),
        ("QL2", "3", "逆流防止 D(昇圧出力)"), ("QL2", "2", "逆流防止 S(→VBAT)"),
        ("QL2", "1", "逆流防止 G(USB検出)"),
        ("RL5", "1", f"FB上側 {FB_TOP_V}"), ("RL6", "2", f"FB下側 {FB_BOT_V}"),
        ("JL2", "1", "電池 +"),
    ):
        print(f"  {ref:<4} pin{num:<2} {label:<22} -> {net(ref, num)}")

    print("\n" + ("=== 総合: OK ===" if ok else "=== 総合: 要修正 ==="))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else "hardware/wobo40/wobo40.kicad_sch"))
