# WoBo40 ハードウェア

単4電池1本(アルカリ1.5V / ニッケル水素1.2V)で動作する、47キー + 1Uトラックボールの
ZMKキーボード用 KiCad プロジェクトです。

```
hardware/
├── wobo40/                  ← KiCad プロジェクト
│   ├── wobo40.kicad_pro
│   ├── wobo40.kicad_sch     ← 回路図 (スクリプト生成)
│   ├── sym-lib-table
│   └── fp-lib-table
└── lib/                     ← 同梱ライブラリ (パス設定不要)
    ├── dya-kbd.kicad_sym / .pretty                  (TPS61021A, BU42 など)
    └── Seeed_Studio_XIAO_Series.kicad_sym / .pretty (XIAO nRF52840 Plus)
```

## 開き方

`hardware/wobo40/wobo40.kicad_pro` を KiCad 9 で開くだけです。
ライブラリはリポジトリ内に同梱し、プロジェクト固有のライブラリテーブル
(`sym-lib-table` / `fp-lib-table`)が `../lib/` を相対参照しているので、
**KiCad 側のライブラリ設定は不要**です。

回路図は古い形式で書き出してあるため、初回オープン時に KiCad が新形式へ
自動変換します(そのまま保存すれば以降は KiCad 9 形式になります)。

## 電源構成 (単4電池1本 → 3.3V)

```
JL2 (単4 x1)
  └─ QL1 (逆接保護 PMOS)
      └─ VIN_B ──┬─ LL1 0.47µH ─┬─ UL1 SW(6,7)
                 ├─ UL1 VIN(8)  │
                 ├─ CL2 10µF    │   UL1 = TPS61021A 昇圧コンバータ
                 ├─ RL2/RL3 (電池電圧モニタ → D4/AIN2)
                 ├─ UL2 VDD (BU4210 = 1.0V 低電圧カットオフ)
                 └─ SW_BATL1 (電源スイッチ) ─ RL4 ─ UL1 EN(5)
                                     │
      UL1 VOUT(3,4) ─ VOUT_B ─┬─ CL4/CL5 10µF
                              ├─ RL5 560k ─┬─ UL1 FB(2)   ← 分圧で3.3Vを決定
                              │            └─ RL6 100k ─ GND
                              └─ QL2 (USB逆流防止 PMOS) ─ BAT_L ─ XIAO VBAT(28)
```

**出力電圧**: TPS61021A の VFB = 0.5V なので

```
Vout = 0.5V × (1 + RL5/RL6) = 0.5 × (1 + 560/100) = 3.3V
```

> 参考にした [cormoran/dya-dash-keyboard](https://github.com/cormoran/dya-dash-keyboard)
> では別の分圧値でしたが、本プロジェクトでは 3.3V になる値を採用しています。

## マトリクス

物理 4行 × 12列 のうち、4行目9列目がトラックボールなので **47キー**。
GPIO 節約のため左右ブロックで列線を共用する「行2段重ね」方式で、
電気的には **8行 × 6列** です。

- 左ブロック (物理C1〜C6) … Row0〜Row3
- 右ブロック (物理C7〜C12) … Row4〜Row7
- 列 Col0〜Col5 は左右で共用
- 未使用セルは **Row7 × Col2**(= トラックボール位置)のみ

ダイオードは COL2ROW(カソードを行側へ)、1N4148W(SOD-123)を47本。

## ピンアサイン

PCB 配線しやすいよう、XIAO のパッドの物理的な並び順に沿って
**行8本を上辺・列6本を下辺に連番で**割り当てています。

| 上辺(左→右) | 信号 | | 下辺(左→右) | 信号 |
|---|---|---|---|---|
| D0 | Row0 | | D10 | Col0 |
| D11 | Row1 | | D19 | Col1 |
| D1 | Row2 | | D9 | Col2 |
| D12 | Row3 | | D18 | Col3 |
| D2 | Row4 | | D8 | Col4 |
| D13 | Row5 | | D17 | Col5 |
| D3 | Row6 | | D7 | MOTION |
| D14 | Row7 | | | |
| D4 | 電池電圧 ADC | | | |
| D15 | トラボ nCS | | | |
| D5 | トラボ SDIO | | | |
| **D16** | **使用禁止** | | | |
| D6 | トラボ SCLK | | | |

- **D16 (P0.31) は XIAO 内部の電池電圧測定に使われる**ため未接続
- D14/D15 は NFC 兼用ピン。ファーム側で `CONFIG_NFCT_PINS_AS_GPIOS=y` によりGPIO化
- SWDIO / SWDCLK / EN は未接続(必要ならテストポイントを残すと便利)

この割当は `config/` 以下の ZMK ファームウェア(`wobo40.overlay`)と1対1で一致します。

## 回路図の再生成

回路図はスクリプトから生成しています。ピン割当やマトリクス構成を変えるときは、
`tools/gen_schematic.py` を編集して作り直すのが確実です。

```bash
pip install kiutils
git clone https://github.com/cormoran/dya-dash-keyboard  /tmp/dya
git clone https://github.com/Seeed-Studio/OPL_Kicad_Library /tmp/opl

python3 tools/gen_schematic.py --dya /tmp/dya --opl /tmp/opl --out hardware/wobo40
python3 tools/check_netlist.py hardware/wobo40/wobo40.kicad_sch
```

`check_netlist.py` は KiCad を起動せずにネット接続を検証します
(47キーが正しく Row×Col に繋がっているか、XIAO のピンがファームと一致するか等)。

## 基板レイアウトの指針

回路図から PCB を起こすときの推奨:

1. **XIAO は基板中央上部へ** — 行2段重ね構成では、左ブロック=Row0〜3 /
   右ブロック=Row4〜7 なので、中央に置くと行が左右対称に展開でき、
   列も中央から左右へ分岐できて横断配線が不要になります
2. **電源部は1本の帯にまとめる** — 電流の流れ順に一直線に並べ、
   XIAO へは `BAT_L` / `VBUS_L` / `3.3V_L` / `INPUT_VOLTAGE_L` の4本だけ引く
3. **昇圧回路のクリティカル配置**(優先度順)
   - 出力コンデンサ CL4/CL5 を VOUT(3,4)と GND に最短接続(最重要)
   - 入力コンデンサ CL2 を VIN(8)直近へ
   - インダクタ LL1 を SW(6,7)直近へ。SWノードの銅箔面積は最小限に
   - FB分圧 RL5/RL6 を FB(2)直近へ。FB配線はSWノードから離す
   - サーマルパッド(9)は複数ビアで GND ベタへ
4. **マトリクスは2層で分離** — 列(縦)を片面、行(横)をもう片面にすると
   ビアなしで交差が解決します。残りは両面 GND ベタ

## 部品表(電源部)

| Ref | 部品 | 値 / 型番 | 備考 |
|---|---|---|---|
| UL1 | 昇圧コンバータ | TPS61021A | WSON-8 2×2mm (LCSC C193037) |
| UL2 | 低電圧検出 | BU4210 | 1.0V でカットオフ。省略可 |
| QL1 | PMOS (逆接保護) | DMG3415U | **低Vth必須**(電池1本でゲート電圧が低いため) |
| QL2 | PMOS (USB逆流防止) | DMG3415U | 3.3Vレールなので汎用品でも可 |
| LL1 | インダクタ | 0.47µH | 飽和電流 3.5A以上、1008サイズ |
| CL2, CL4, CL5 | コンデンサ | 10µF/25V X5R | CL4/CL5 は出力直近に |
| CL3 | コンデンサ | 20pF | FB フィードフォワード |
| CL1 | コンデンサ | 10nF | 電池電圧モニタ用 |
| RL5 / RL6 | 抵抗 | 560k / 100k | **3.3V を決める分圧。変更不可** |
| RL1, RL7 | 抵抗 | 150k | ゲートプルダウン |
| RL2 / RL3 | 抵抗 | 1M / 470k | 電池電圧モニタ分圧 |
| RL4 | 抵抗 | 470k | EN プルアップ |
| SW_BATL1 | スライドスイッチ | MSK12C02 | 電源 ON/OFF |
| JL2 | 電池コネクタ | 単4×1 ホルダー | |
| JL1 | コネクタ | 1×6 | トラックボール(PAW3222)接続 |

トラックボール側の結線は本体 [README](../README.md) を参照してください。
