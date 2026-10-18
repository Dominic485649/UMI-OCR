# Umi-OCR 3.0.1

メインリポジトリ：https://github.com/Dominic485649/UMI-OCR

正式版：3.0.1。Release tag は `v3.0.1` です。基本プログラムと CUDA プラグインを公開提供します。

作者と出典：Dominic485649（本 fork の作者・メンテナー）、[hiroi-sora](https://github.com/hiroi-sora/Umi-OCR)（Umi-OCR の原作者・原著作権の出典）。

<p align="left">
    <a href="README.md">
        中文
    </a>
    <span> • </span>
    <a href="README_en.md">
        English
    </a>
    <span> • </span>
    <span>
        <b>日本語</b>
    </span>
</p>

<p align="center">
  <a href="https://github.com/Dominic485649/UMI-OCR">
    <img width="200" height="128" src="https://tupian.li/images/2022/10/27/icon---256.png" alt="Umi-OCR">
  </a>
</p>

<h1 align="center">Umi-OCR</h1>

<p align="center">
  <a href="https://github.com/Dominic485649/UMI-OCR/releases">
    <img src="https://img.shields.io/github/v/release/Dominic485649/UMI-OCR?style=flat-square" alt="Umi-OCR">
  </a>
  <a href="#ダウンロード">
    <img src="https://img.shields.io/github/downloads/Dominic485649/UMI-OCR/total?style=flat-square" alt="ダウンロード">
  </a>
  <a href="https://github.com/Dominic485649/UMI-OCR">
    <img src="https://img.shields.io/github/stars/Dominic485649/UMI-OCR?style=flat-square" alt="スター">
  </a>
  <a href="https://github.com/Dominic485649/UMI-OCR/forks">
    <img src="https://img.shields.io/github/forks/Dominic485649/UMI-OCR?style=flat-square" alt="フォーク">
  </a>
  <a href="https://hosted.weblate.org/engage/umi-ocr/">
    <img src="https://hosted.weblate.org/widget/umi-ocr/svg-badge.svg" alt="翻译状态">
  </a>
</p>

<div align="center">
  <strong>オープンソース、一括処理対応のオフライン OCR ソフトウェア</strong><br>
  <sub>Umi-OCR 3.0.1：今回のリリースは Windows 10/11 x64 向けです</sub>
</div><br>

- **公開版**: 基本プログラムと CUDA プラグインを無料で公開します。サードパーティ製プラグインの開発・接続にも対応します。
- **便利**: 解凍して使用し、オフラインで実行し、ネットワークは必要ありません。
- **効率的**: オフラインの PP-OCRv6_medium 高精度パイプラインを標準で使用します。
- **柔軟**: カスタマイズ可能なインターフェースをサポートし、コマンドラインや HTTP API など、複数の呼び出し方法をサポートします。

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ec301b55.png" alt="1-タイトル-1.png" style="width: 80%;"></p>

![1-タイトル-2.png](https://tupian.li/images/2023/11/19/6559909fdeeba.png)

## ソースコードの使用:

開発者は続ける前に、[プロジェクトのビルド](#プロジェクトのビルド)を読んでください

### この fork のライセンス

元の Umi-OCR の MIT `LICENSE`、hiroi-sora の著作権表示と帰属は変更せず保持します。この fork が追加または変更したファイルは [AGPL-3.0-or-later](COPYING) で提供し、PyMuPDF を組み合わせる配布物全体も AGPL-3.0-or-later です。配布物には対応ソース、ビルドスクリプト、依存関係ロック、第三者通知を含めます。有償のソース提供、ビルド成果物、更新、サポートは可能ですが、受領者の複製、変更、再配布の権利を制限しません。詳細は [組み合わせ配布の説明](LICENSES/COMBINED_DISTRIBUTION.md) を参照してください。

## リリースのダウンロード:

今回は tag `v3.0.1` の **Windows x64 正式 Release** です。基本プログラムと CUDA プラグインを別々にダウンロードします。CPU と PaddleOCR-VL は公開アセットに含まれません。

- **基本プログラム**：[メインリポジトリ v3.0.1 Release](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.0.1)。
- **CUDA プラグイン**：[プラグインリポジトリ v3.0.1 Release](https://github.com/Dominic485649/UMI-OCR_plugins/releases/tag/v3.0.1)。

本体と CUDA worker は Python 3.13.16 を共有し、Qt は 6.11.2 のままです。アーカイブは標準 LZMA2 のデフォルト圧縮レベルによる `.tar.xz` です。基本プログラムを完全に解凍してから、CUDA プラグインを本体のルートへ解凍してください。CUDA 12.6 対応の NVIDIA GPU とドライバーが必要ですが、システムの CUDA Toolkit は不要です。

CPU と CUDA の認識結果は同等で、CPU の処理速度は遅くなります。PaddleOCR-VL は高精度で、速度は CPU に近いです。CPU と PaddleOCR-VL のプラグインは別途有料で提供します。連絡先：QQ グループ【AWJ | Umi-OCR】https://qm.qq.com/q/5XHoXCOU26 。料金は開発・テスト・保守の費用に充てます。作者にも生活費と継続投資の回収が必要です。購入を求めるのではなく、まず無料の CUDA 版をおすすめします。

## はじめに

正式版は直接実行できるポータブルディレクトリ形式です。起動前にアーカイブを完全に解凍してください。

このソフトウェアはインストールを必要としません。抽出後、`Umi-OCR.exe`をクリックしてプログラムを開始します。

問題が発生した場合は、[Issue](https://github.com/Dominic485649/UMI-OCR/issues)を提出してください。最善を尽くしてサポートします。

## インターフェース言語

Umi-OCR は、インターフェースの複数の言語をサポートしています。ソフトウェアを初めて開くと、コンピューターのシステム設定に基づいて自動的に言語が切り替わります。

言語を手動で切り替える必要がある場合は、以下の図を参照してください。`全局设置`→`语言/Language`。

<p align="center"><img src="https://tupian.li/images/2023/11/19/65599c3f9e600.png" alt="1-タイトル-1.png" style="width: 80%;"></p>

## タブインターフェース

Umi-OCR v3 は、一連の柔軟で使いやすい**タブインターフェース**で構成されています。好みに応じて必要なタブインターフェースを開くことができます。

タブバーの左上隅を使用して**ウィンドウ常に最前面**を切り替えることができます。右上隅は、日常使用中の偶発的な閉鎖を防ぐために**タブインターフェースをロック**するために使用できます。

### スクリーンショット OCR

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ecb4dfb4.png" alt="2-スクリーンショット-1.png" style="width: 80%;"></p>

**スクリーンショット OCR**: このページを開いた後、キーボードショートカットを使用してスクリーンショットをキャプチャし、画像内のテキストを認識することができます。

- 左側の画像プレビューパネルを使用して、マウスでテキストを選択してコピーすることができます。
- 右側の認識レコードパネルを使用して、テキストを編集し、複数のレコードを選択してコピーすることができます。
- 他の場所から画像をコピーして Umi-OCR に貼り付け、認識することもサポートしています。
- HDR 画面は WGC/D3D11 の浮動小数点キャプチャと sRGB tone mapping を使用します。OCR オーバーレイは四点ポリゴンと回転を保持し、ズームはマウスポインター位置を基準にします。

#### 段落マージ

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ecc62ac9.png" alt="2-スクリーンショット-2.png" style="width: 80%;"></p>

**OCR テキスト後処理 - 段落マージ**について: この機能は、OCR 結果のレイアウトと順序を整理し、テキストを読みやすく使用しやすくすることができます。プリセットスキームは以下の通りです。

- **単一行**: 同じ行上のテキストをマージします。ほとんどのシナリオに適しています。
- **複数行 - 自然な段落**: 同じ段落に属するテキストを知的に認識してマージします。ほとんどのシナリオに適しており、上記の図に示されています。
- **複数行 - コードブロック**: テキストの元のインデントとスペーシングを復元しようとします。コードスニペットやスペースを保持する必要があるシーンを認識するのに適しています。
- **縦書きレイアウト**: 縦書きレイアウトに適しています。縦書き認識もサポートするモデルライブラリと併用する必要があります。

---

### バッチ OCR

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ecdc5197.png" alt="3-バッチ-1.png" style="width: 80%;"></p>

**バッチ OCR**: このページでは、ローカル画像をバッチでインポートして認識することがサポートされています。

- JPEG、PNG、AVIF（dav1d）、WebP、JPEG XL、JPEG XR/WDP/HDP、BMP、TIFF を読み込み、OCR 前に連続 BGR 8-bit へ変換します。
- 認識されたコンテンツは、txt/jsonl/md/csv(Excel)などのさまざまな形式で保存できます。
- `テキスト後処理`技術をサポートし、同じ自然な段落に属するテキストを認識してマージすることができます。また、コードブロックや縦書きテキストなど、複数の処理スキームもサポートしています。
- 一度に処理できる画像の数に制限はなく、タスクを完了した後、ソフトウェアは自動的にシャットダウンまたはスリープすることができます。

#### 無視域

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ecbc0021.png" alt="3-バッチ-2.png" style="width: 80%;"></p>

**OCR テキスト後処理 - 無視域**について: これは、バッチ OCR の特別な機能で、画像内の望ましくないテキストを除外するために使用されます。

- 無視領域エディタは、バッチ認識ページ設定の右側の列でアクセスできます。
- 上記の例のように、画像の上部と右下隅に複数の透かし/LOGO があります。これらの画像がバッチで認識される場合、透かしは認識結果に干渉します。
- 右マウスボタンを押し続けて、複数の長方形ボックスを描画します。これらのエリア内のテキストは、タスク中に無視されます。
- 長方形ボックスをできるだけ大きく描画し、透かしのすべての可能な位置を完全に包むようにしてください。

---

### 大量文章のｏｃｒ

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ecc8bfd4.png" alt="" style="width: 80%;"></p>

---

### QR コード

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ed01f5b2.png" alt="4-QRコード-1.png" style="width: 80%;"></p>

**スキャンコード**:

- スクリーンショットをキャプチャしたり、貼り付けたり、ローカル画像をドラッグして、QR コードやバーコードを読み取ることができます。
- 1 つの画像で複数のコードをサポートします。
- 以下の 19 のプロトコルをサポートします:

`Aztec`,`Codabar`,`Code128`,`Code39`,`Code93`,`DataBar`,`DataBarExpanded`,`DataMatrix`,`EAN13`,`EAN8`,`ITF`,`LinearCodes`,`MatrixCodes`,`MaxiCode`,`MicroQRCode`,`PDF417`,`QRCode`,`UPCA`,`UPCE`,

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ed001437.png" alt="4-QRコード-2.png" style="width: 80%;"></p>

**コード生成**:

- テキストを入力して QR コード画像を生成します。
- **誤り訂正レベル**などのパラメータを含む 19 のプロトコルをサポートします。

---

### グローバル設定

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ed16f4e0.png" alt="5-グローバル設定-1.png" style="width: 80%;"></p>

**グローバル設定**: ここでは、ソフトウェアのグローバルパラメータを調整できます。一般的な機能には、以下が含まれます:

- ショートカットを一度に追加するか、自動起動を設定します。
- インターフェースの**言語**を変更します。Umi は繁体字中国語、英語、日本語などの言語をサポートしています。
- インターフェースの**テーマ**を切り替えます。システム追従時は Windows のライト/ダークそれぞれに別テーマを指定でき、Neutral Dark は `rgb(24, 24, 24)` を基調にします。
- インターフェーステキストの**フォントサイズ**と**フォント**を調整します。
- PP-OCRv6 のプリセット、補助段階、長辺、バッチ、しきい値、CUDA デバイスを設定します。認識モデルは PP-OCRv6_medium 固定です。
- Windows UI は Qt6 RHI/D3D11 ハードウェアレンダリング固定です。トレイアイコンは単クリックでスクリーンショット、ダブルクリックでメイン画面、右クリックでメニューを開きます。

---

## API の使用:

- [コマンドラインマニュアル](docs/README_CLI.md)
- [HTTP API マニュアル](docs/http/README.md)

## プロジェクト構造について

### リポジトリ:

- [メインリポジトリ](https://github.com/Dominic485649/UMI-OCR) 👈
- [公開 CUDA プラグインリポジトリ](https://github.com/Dominic485649/UMI-OCR_plugins)（作成予定、公開待ち）

サードパーティ製プラグインの開発、接続、置き換えはオープンです。商業目的であることを理由に参加や公開を制限しません。自分でプラグインを作成することもできます。本ブランチは旧 2.x の CPU/CUDA/VL 技術実装と互換性がありません。その他のプラグインの互換性は公開インターフェースとプラットフォーム依存関係によって異なり、すべての環境での動作は保証しません。

## プロジェクトのビルド

- [Windows](docs/BUILD_WINDOWS_CUDA.md)

Linux 版は将来検討するもので、今回のリリースには含まれません。

---

## ソフトウェアのローカライゼーション:

元の Umi-OCR は [Weblate](https://hosted.weblate.org/engage/umi-ocr/) で翻訳を共同作業しており、本フォークもその貢献を保持しています。このリンクは上流の翻訳プロジェクトであり、本フォーク専用の Weblate プロジェクトではありません。本フォークの新しい内容の翻訳やフィードバックは [本リポジトリ](https://github.com/Dominic485649/UMI-OCR/issues) にお寄せください。

以下に、Umi-OCRのローカライゼーションに貢献いただいた翻訳者の皆様を感謝とともに掲載します:

| 翻訳者                                                                               | 対応言語                  |
| ------------------------------------------------------------------------------------ | ------------------------- |
| [bob](https://hosted.weblate.org/user/q021)                                          | English, 繁體中文, 日本語 |
| [Qingzheng Gao](https://github.com/QZGao)                                            | English, 繁體中文         |
| [Weng, Chia-Ling](https://hosted.weblate.org/user/ChiaLingWeng)                      | English, 繁體中文         |
| [linzow](https://hosted.weblate.org/user/linzow)                                     | English, 繁體中文         |
| [Marcos i](https://hosted.weblate.org/user/ultramarkorj9)                            | English, Português        |
| [Eric Guo](https://hosted.weblate.org/user/qwedc001)                                 | English                   |
| [steven0081](https://hosted.weblate.org/user/steven0081)                             | English                   |
| [Brandon Cagle](https://hosted.weblate.org/user/random4t4x14)                        | English                   |
| [plum7x](https://hosted.weblate.org/user/plum7x)                                     | 繁體中文                  |
| [hugoalh](https://hosted.weblate.org/user/hugoalh)                                   | 繁體中文                  |
| Anarkiisto                             | 繁體中文                  |
| [ドコモ光](https://hosted.weblate.org/user/umren190402)                              | 日本語                    |
| [杨鹏](https://hosted.weblate.org/user/ypf)                                          | Português                 |
| Вячеслав Анатольевич Малышев                 | Русский                   |
| [Muhammadyusuf Kurbonov](https://hosted.weblate.org/user/muhammadyusuf.kurbonov2002) | Русский                   |
| [தமிழ்நேரம்](https://hosted.weblate.org/user/TamilNeram/)                                | தமிழ்                       |

情報の誤りや記載漏れがありましたら、[こちらのディスカッション](https://github.com/Dominic485649/UMI-OCR/issues) までご連絡ください。

---

## [変更ログ](CHANGE_LOG.md)
