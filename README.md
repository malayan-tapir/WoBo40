# WoBo40

Seeed XIAO BLE (nRF52840) + ZMK で動く、1Uトラックボール内蔵の40%オーソリニアキーボードです。

```
┌────┬────┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬─────┐
│ C1 │Esc │ Q │ W │ E │ R │ T │ Y │ U │ I │ O │ P │BSpc │
├────┼────┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼─────┤
│ C2 │Tab │ A │ S │ D │ F │ G │ H │ J │ K │ L │ - │Enter│
├────┼────┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼─────┤
│ C3 │Sft │ Z │ X │ C │ V │ B │ N │ M │ , │ . │ ↑ │ Sft │
├────┼────┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼─────┤
│ C4 │Ctl │Opt│Cmd│英数│Spc│Spc│かな│●TB│fn │ ← │ ↓ │ →  │
└────┴────┴───┴───┴───┴───┴───┴───┴───┴───┴───┴───┴─────┘
```

- 51キー (4行 × 13列、トラックボール位置はキーなし)
- `●TB` = 1U トラックボール (PMW3610 センサー)
- Bluetooth / USB 両対応、ZMK Studio 対応

## 部品構成

| 部品 | 個数 | 備考 |
|---|---|---|
| Seeed XIAO BLE (nRF52840) | 1 | 無線 (BLE) + USB |
| PMW3610 トラックボールモジュール | 1 | 1U サイズ、3.3V/SPI 接続のもの |
| 74HC595 (シフトレジスタ) | 2 | 列駆動用にデイジーチェーン接続 |
| ダイオード 1N4148 | 51 | キーごとに1本 (COL2ROW) |
| キースイッチ / キーキャップ | 51 | MX など |
| リチウムポリマー電池 | 1 | XIAO BLE の BAT+/BAT- に接続 (任意) |

XIAO は GPIO が 11 本しかないため、13列の駆動には 74HC595 ×2 を SPI で使用します
(ZMK 標準の `zmk,gpio-595` ドライバを使用)。

## ピンアサイン

| XIAO ピン | nRF52840 | 接続先 |
|---|---|---|
| D0 | P0.02 | Row0 (最上段) |
| D1 | P0.03 | Row1 |
| D2 | P0.28 | Row2 |
| D3 | P0.29 | Row3 (最下段) |
| D4 | P0.04 | PMW3610 SCLK |
| D5 | P0.05 | PMW3610 SDIO |
| D6 | P1.11 | PMW3610 nCS |
| D7 | P1.12 | PMW3610 MOTION (割り込み) |
| D8 | P1.13 | 74HC595 SRCLK (11番ピン, 両方に共通) |
| D9 | P1.14 | 74HC595 RCLK (12番ピン, 両方に共通) |
| D10 | P1.15 | 74HC595 #1 SER (14番ピン) |

### 74HC595 の配線

- 2個をデイジーチェーン: XIAO D10 → #1 の SER (14番)、#1 の QH' (9番) → #2 の SER (14番)
- SRCLK (11番) と RCLK (12番) は 2個で共通に XIAO D8 / D9 へ
- 各ICの /OE (13番) → GND、/SRCLR (10番) → 3V3、VCC → 3V3、GND → GND
- 列の対応: **C0〜C7 = #1 の QA〜QH、C8〜C12 = #2 の QA〜QE** (C0 が左端の列)

### マトリクス配線

- ダイオード方向は **COL2ROW** (列 → スイッチ → ダイオード → 行。カソード帯を行側に)
- 行は上から Row0〜Row3、列は左から C0〜C12
- トラックボール位置 (Row3 × C8) はスイッチなし

### PMW3610 の配線

- 3線SPI です。モジュールの SDIO を XIAO D5 に接続 (MOSI/MISO はファームウェア側で同一ピンに束ねています)
- VCC は 3.3V (XIAO の 3V3 から)

## ファームウェアのビルド

GitHub Actions で自動ビルドされます。

1. このリポジトリに push すると Actions が走ります
2. Actions の実行結果ページから Artifacts をダウンロード:
   - `wobo40-studio` … ZMK Studio 対応版 (通常はこちら)
   - `wobo40` … Studio なしの軽量版
   - `settings-reset` … ペアリング情報などを消去するリセット用

## 書き込み方法

1. XIAO BLE のリセットボタンを素早く2回押す (UF2 ブートローダーモードに入り、`XIAO-SENSE` ドライブがマウントされる)
2. ダウンロードした `.uf2` ファイルをドライブにコピーする
3. 自動的に再起動して書き込み完了

動作がおかしくなった場合は `settings-reset` を一度書き込んでから、本体ファームウェアを入れ直してください。

## キーマップ

`config/wobo40.keymap` で定義しています。Mac / JIS 環境を想定しています。

| レイヤー | 出し方 | 内容 |
|---|---|---|
| 0: Base | 常時 | 通常入力。`英数`=LANG2 / `かな`=LANG1 |
| 1: Mouse | ボールを動かすと自動有効 (400ms で解除) | `かな`=左クリック、`,`=右クリック、`.`=中クリック |
| 2: Fn | `fn` 押下中 | Q〜P=数字、A〜`-`=F1〜F10、記号 (`=` `[` `]` `\` `;` `'` `/`)、PgUp/PgDn/Home/End。**トラックボールはスクロールに切替** |
| 3: Sys | `C1` 押下中 | Bluetooth 切替 (Q〜T=接続先0〜4、BSpc=ペアリング解除)、Tab=ブートローダー、Enter=Studio アンロック、メディアキー |

左端の C1〜C4 は自由割当のカスタムキーです。デフォルトは:

- C1 = Sys レイヤー (押しながら他キー)
- C2 = ⌘C (コピー) / C3 = ⌘V (ペースト) / C4 = ⌘Z (取り消し)

最下段の無刻印2キーはどちらもスペースです。

### ZMK Studio

`wobo40-studio` 版を書き込めば、[ZMK Studio](https://zmk.studio/) から USB 経由でキーマップをリアルタイムに変更できます (Sys レイヤーの Enter = `&studio_unlock` でアンロック)。

## トラックボールの調整

`config/wobo40.conf` で調整できます:

- `CONFIG_PMW3610_CPI` … 感度 (200〜3200)
- `CONFIG_PMW3610_ORIENTATION_90/180/270` … センサーの実装向きに合わせて回転
- `CONFIG_PMW3610_INVERT_X/Y` … カーソルの反転
- `CONFIG_PMW3610_INVERT_SCROLL_X/Y` … スクロール方向の反転 (自然スクロール化)
- `CONFIG_PMW3610_SCROLL_TICK` … スクロール速度 (大きいほど遅い)
- `CONFIG_PMW3610_AUTOMOUSE_TIMEOUT_MS` … Mouse レイヤー自動解除までの時間

ドライバ: [inorichi/zmk-pmw3610-driver](https://github.com/inorichi/zmk-pmw3610-driver)

## ファイル構成

```
├── build.yaml                     # GitHub Actions ビルドマトリクス
├── config/
│   ├── west.yml                   # ZMK v0.3 + PMW3610 ドライバの取得設定
│   ├── wobo40.keymap              # キーマップ
│   └── wobo40.conf                # 機能設定 (トラックボール感度など)
└── boards/shields/wobo40/
    ├── wobo40.overlay             # ハード定義 (マトリクス/595/PMW3610/物理レイアウト)
    ├── Kconfig.shield
    ├── Kconfig.defconfig
    └── wobo40.zmk.yml
```
