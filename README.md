# Amazon Scraping Tools

## 概要
Amazonの商品ページから情報を自動取得し、Google Sheetsに出力するためのツール群です。  
書籍モードと電気製品モードを切り替えられ、在庫・価格・画像・レビューなどを効率的に収集できます。

## 主な機能
- **商品情報スクレイピング**  
  - 商品名 / 価格 / ブランド / 型番 / ISBN / ページ数 など  
- **価格・在庫分析**  
  - 出品者ごとの価格・在庫状況を収集  
  - FBA/FBM判定と在庫スコア計算  
- **画像スクレイピング**  
  - 高解像度の商品画像URLを最大10件まで取得  
- **Google Sheets連携**  
  - データを自動でスプレッドシートに反映  
- **GUI対応**  
  - Tkinterを利用し、非エンジニアでも簡単に操作可能  

## 使用技術
- Python 3.10+  
- Requests / BeautifulSoup / Selenium  
- gspread / Google Sheets API  
- Tkinter  

## 成果・効果
- 手作業リサーチの工数を大幅削減  
- 数百件単位の商品情報を1日で収集可能  
- Amazonリサーチや越境EC事業の効率化に直結  

## 実行方法
1. Google Service Account の認証JSONを準備  
2. GUIから設定を入力（スプレッドシートID、シート名など）  
3. 「処理実行」ボタンでスクレイピング開始  

```bash
python amazon_gui.py
