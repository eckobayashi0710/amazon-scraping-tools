# amazon_image_core.py
# Amazon商品ページの画像URLをスクレイピングし、Google Sheetsを更新するコアロジック (v6.1 - 正規表現を貪欲マッチに変更)

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import requests
from bs4 import BeautifulSoup
import time
import re
import json

class AmazonImageScraper:
    """
    Amazon商品ページの画像URLをスクレイピングし、Google Sheetsを更新するクラス。
    """
    
    def __init__(self, config, logger_callback=print):
        """
        コンストラクタ。設定情報とロガーを初期化します。
        """
        self.config = config
        self.logger = logger_callback
        self.session = requests.Session()
        # ブラウザを偽装するためのヘッダー情報
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        })
        self._setup_gsheets()

    def _setup_gsheets(self):
        """
        Google Sheets APIへの接続をセットアップします。
        """
        self.logger("🔧 Google Sheets サービスを初期化中...")
        try:
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_file(self.config["json_path"], scopes=scopes)
            self.sheets_service = build("sheets", "v4", credentials=creds, cache_discovery=False)
            gc = gspread.authorize(creds)
            spreadsheet = gc.open_by_key(self.config["spreadsheet_id"])
            self.sheet = spreadsheet.worksheet(self.config["sheet_name"])
            self.logger("✅ Google Sheets サービス初期化完了")
        except gspread.exceptions.WorksheetNotFound:
            self.logger(f"❌ ワークシート '{self.config['sheet_name']}' が見つかりません。")
            raise
        except Exception as e:
            self.logger(f"❌ Google Sheetsの認証に失敗しました: {e}")
            raise

    def _column_letter_to_number(self, column_letter):
        """
        列のアルファベット（'A', 'B'など）を数値に変換します。
        """
        return gspread.utils.a1_to_rowcol(f"{column_letter}1")[1]

    def _get_image_id(self, url):
        """
        画像URLからユニークなIDを抽出します。
        例: /I/xxxxxxxx.jpg -> xxxxxxxx
        """
        if not isinstance(url, str):
            return None
        match = re.search(r'/I/([a-zA-Z0-9\-_+]+)\.', url)
        return match.group(1) if match else None

    def _scrape_image_urls(self, url):
        """
        指定されたAmazon商品ページのURLから高画質の画像URLを最大10件まで取得します。
        ★★★ロジックを刷新(v6.1)★★★
        """
        self.logger(f"🖼️ 画像URLを解析中: {url[:60]}...")
        max_retries = self.config.get('max_retries', 3)
        retry_delay = self.config.get('retry_delay', 5.0)

        for attempt in range(max_retries + 1):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                html_content = response.text
                
                ordered_urls = []
                processed_ids = set()

                # --- 【メインロジック: scriptタグ内のJSONデータを直接解析】 ---
                self.logger("  - メインロジック (script内のJSON解析) を試行...")
                
                # 'colorImages'の'initial'配列データを正規表現で抽出
                # re.DOTALLで改行をまたいだ検索を可能にし、'.+'(貪欲マッチ)で配列全体を確実に取得する
                match = re.search(r"'colorImages'\s*:\s*{\s*'initial'\s*:\s*(\[.+\])\s*}", html_content, re.DOTALL)
                
                if match:
                    image_data_str = match.group(1)
                    # 抽出した文字列から 'hiRes' のURLをすべて見つける
                    urls_in_script = re.findall(r'"hiRes"\s*:\s*"(https?://[^"]+)"', image_data_str)
                    
                    for img_url in urls_in_script:
                        # URLに含まれる可能性のあるユニコードエスケープをデコード (例: \u002F -> /)
                        img_url = img_url.encode('utf-8').decode('unicode_escape')
                        
                        img_id = self._get_image_id(img_url)
                        if img_id and img_id not in processed_ids:
                            ordered_urls.append(img_url)
                            processed_ids.add(img_id)
                            self.logger(f"    - 取得成功: {img_url}")

                # --- 【代替ロジック: サムネイルから取得】 ---
                if not ordered_urls:
                    self.logger("  - 代替ロジック ('altImages'のサムネイル) を試行...")
                    soup = BeautifulSoup(html_content, 'html.parser')
                    alt_images_div = soup.find('div', id='altImages')
                    if alt_images_div:
                        thumbnails = alt_images_div.select('li.item.imageThumbnail img, li.item img')
                        for thumb in thumbnails:
                            src = thumb.get('src')
                            if src:
                                # サムネイルURLを高解像度URLに変換
                                hires_url = re.sub(r'\._.*?_\.', '._SL1500_.', src)
                                thumb_id = self._get_image_id(hires_url)
                                if thumb_id and thumb_id not in processed_ids:
                                    ordered_urls.append(hires_url)
                                    processed_ids.add(thumb_id)
                                    self.logger(f"    - 取得成功 (代替): {hires_url}")

                if not ordered_urls:
                    self.logger("⚠️ このページではどの方法でも画像URLを取得できませんでした。")
                    return []

                self.logger(f"✅ 解析完了。合計{len(ordered_urls)}件のユニークなURLを取得。")
                return ordered_urls[:10]

            except requests.exceptions.RequestException as e:
                self.logger(f"❌ リクエストエラー (試行 {attempt + 1}/{max_retries + 1}): {e}")
                if attempt < max_retries:
                    time.sleep(retry_delay * (2 ** attempt))
                else:
                    self.logger("❌ 最大再試行回数に達しました。")
                    return None
        return None


    def _check_and_create_headers(self):
        """
        スプレッドシートのヘッダー行を確認し、必要であれば作成します。
        """
        self.logger("🔍 ヘッダーの確認...")
        try:
            start_col_letter = self.config['output_start_col_letter'].upper()
            expected_headers = [f"画像URL {i+1}" for i in range(10)]
            
            current_headers = self.sheet.row_values(1)
            start_col_num = self._column_letter_to_number(start_col_letter)

            if len(current_headers) < start_col_num + len(expected_headers):
                padding = (start_col_num + len(expected_headers)) - len(current_headers)
                current_headers.extend([""] * padding)
            
            actual_headers = current_headers[start_col_num - 1 : start_col_num - 1 + len(expected_headers)]

            if actual_headers != expected_headers:
                self.logger("ℹ️ ヘッダーを作成または更新します...")
                self.sheet.update(f"{start_col_letter}1", [expected_headers], value_input_option='USER_ENTERED')
                self.logger("✅ ヘッダーの作成/更新が完了しました。")
            else:
                self.logger("✅ ヘッダーは既に存在します。")
        except Exception as e:
            self.logger(f"⚠️ ヘッダーの確認・作成中にエラーが発生しました: {e}")
            raise

    def run_process(self):
        """
        メインの処理を実行します。スプレッドシートからURLを読み取り、スクレイピングして結果を書き込みます。
        """
        try:
            self.logger("\n🚀 Amazon商品画像スクレイピング処理開始 (バッチモード) 🚀")
            self._check_and_create_headers()
        except Exception as e:
            self.logger(f"CRITICAL: ヘッダーの準備に失敗したため、処理を中止します。: {e}")
            return

        start_row = self.config["start_row"]
        url_col_num = self._column_letter_to_number(self.config["url_col_letter"])
        output_start_col_letter = self.config["output_start_col_letter"]
        output_start_col_num = self._column_letter_to_number(output_start_col_letter)
        batch_size = self.config["batch_size"]
        
        current_row = start_row
        
        while True:
            self.logger(f"\n--- バッチ処理開始: {current_row}行目から{batch_size}行分 ---")
            
            range_to_get = f"A{current_row}:Z{current_row + batch_size - 1}"
            try:
                self.logger(f"🚚 スプレッドシートからデータを取得中... (範囲: {range_to_get})")
                batch_data = self.sheet.get(range_to_get, major_dimension='ROWS', value_render_option='FORMATTED_VALUE')

            except gspread.exceptions.APIError as e:
                if e.response.status_code == 400:
                     self.logger(f"ℹ️ 指定範囲({range_to_get})のデータ取得に失敗しました。シートの終端の可能性があります。")
                else:
                    self.logger(f"❌ APIエラーによりデータ取得に失敗: {e}")
                break
            
            if not batch_data:
                self.logger("ℹ️ これ以上処理するデータがありません。")
                break

            update_payload = []
            
            for i, row_values in enumerate(batch_data):
                actual_row_num = current_row + i
                
                url = row_values[url_col_num - 1] if len(row_values) >= url_col_num else None
                
                if not url or not url.strip():
                    continue
                
                output_cell_value = row_values[output_start_col_num - 1] if len(row_values) >= output_start_col_num else None
                if output_cell_value and output_cell_value.strip():
                    self.logger(f"  - {actual_row_num}行目: 処理済みのためスキップ")
                    continue

                image_urls = self._scrape_image_urls(url)
                
                if image_urls is not None:
                    values_to_write = image_urls + [""] * (10 - len(image_urls))
                    update_payload.append({
                        'range': f"{output_start_col_letter}{actual_row_num}",
                        'values': [values_to_write]
                    })
                else:
                    self.logger(f"⚠️ {actual_row_num}行目のURLの情報取得に失敗しました。")

                time.sleep(self.config.get("delay", 3))

            if update_payload:
                self.logger(f"💾 {len(update_payload)}件の処理結果をスプレッドシートに一括書き込み中...")
                try:
                    self.sheet.batch_update(update_payload, value_input_option='USER_ENTERED')
                    self.logger("✅ 書き込み完了。")
                except gspread.exceptions.APIError as e:
                    self.logger(f"❌ APIエラーにより一括書き込みに失敗: {e}")
            else:
                self.logger("ℹ️ このバッチでは書き込むデータがありませんでした。")

            current_row += len(batch_data)
            
            if len(batch_data) < batch_size:
                self.logger("ℹ️ シートの最終行まで処理しました。")
                break

        self.logger("\n🎉 全処理完了！ 🎉")
