# amazon_core.py
# Amazon商品ページのスクレイピングとGoogle Sheets操作のコアロジック (最終改善版)

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import requests
from bs4 import BeautifulSoup
import time
import re

class AmazonScraper:
    """
    Amazon商品ページの情報をスクレイピングし、Google Sheetsを更新するクラス。
    モードに応じて電気製品と書籍のスクレイピングを切り替える。
    """
    
    def __init__(self, config, logger_callback=print):
        self.config = config
        self.logger = logger_callback
        self.mode = config.get('scrape_mode', '電気製品') # GUIからモードを受け取る
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        })

        # --- モードに応じたヘッダーを定義 ---
        self.ELECTRONICS_HEADERS = [
            'ASIN', '商品名', 'ブランド', '価格', '商品の特徴', 'メーカー', 'メーカー型番', '製品型番', '商品モデル番号',
            '色', 'カラー', 'サイズ', '製品サイズ', '梱包サイズ', '商品の重量', '商品重量', '材質', '素材',
            '接続技術', 'ヘッドフォンジャック', 'ケーブルの特徴', 'ケーブルの形状', 'コネクタのオス/メス',
            '付属品', '付属コンポーネント', '電池使用', '電池付属', '保証について', 'メーカーにより製造中止になりました',
            'OS', '製品の特徴', 'レーザークラス', '対象年齢', '制御タイプ', '商品用途・使用方法', 'ユニット数', 'スタイル',
            '電池', '発売日', 'Amazon.co.jp での取り扱い開始日', 'Amazon 売れ筋ランキング', 'カスタマーレビュー評価', 'カスタマーレビュー数'
        ]
        
        self.BOOK_HEADERS = [
            'ASIN', '商品名', '著者', '価格', '出版社', '発売日', '言語', 
            'ページ数', '単行本', '文庫', 'ペーパーバック', # ページ数関連
            'ISBN-10', 'ISBN-13', '寸法', 'Amazon 売れ筋ランキング', 'カスタマーレビュー評価', 'カスタマーレビュー数'
        ]

        # 実行モードに応じて使用するヘッダーを決定
        if self.mode == '書籍':
            self.ALL_HEADERS = self.BOOK_HEADERS
            self.logger("📖 書籍モードで実行します。")
        else:
            self.ALL_HEADERS = self.ELECTRONICS_HEADERS
            self.logger("🔌 電気製品モードで実行します。")

        self._setup_gsheets()

    def _setup_gsheets(self):
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
        return gspread.utils.a1_to_rowcol(f"{column_letter}1")[1]

    def _clean_key(self, text):
        """キーからコロン、空白、目に見えない制御文字などを除去する"""
        if not text:
            return ""
        return re.sub(r'[\s:‎‏]', '', text)

    def _parse_details_table(self, table, data):
        """詳細情報テーブル(tr/th/td)を解析してdata辞書を更新する"""
        if not table:
            return
        for tr in table.find_all('tr'):
            th = tr.find(['th', 'td'], class_='prodDetSectionEntry')
            td = tr.find('td', class_='prodDetInfoEntry')
            if not th or not td:
                th = tr.find('th')
                td = tr.find('td')
            
            if th and td:
                key = self._clean_key(th.text)
                value = re.sub(r'\s+', ' ', td.text).strip()
                if key and key not in data:
                    data[key] = value

    def _get_authors(self, soup, data_from_table):
        """複数の場所から著者情報を探し、最初に見つかったものを返す"""
        # 1. 商品名下の bylineInfo から取得 (最優先)
        byline_tag = soup.find('div', id='bylineInfo_feature_div')
        if byline_tag:
            author_links = byline_tag.select('.author .a-link-normal')
            if author_links:
                authors = list(dict.fromkeys([a.text.strip() for a in author_links]))
                self.logger("  - 著者情報を bylineInfo から取得しました。")
                return ", ".join(authors)

        # 2. 「著者について」セクションから取得
        author_bio_div = soup.find('div', class_='a-row a-spacing-small about-author-container')
        if author_bio_div:
            name_tag = author_bio_div.find('a', class_='a-link-normal')
            if name_tag:
                self.logger("  - 著者情報を「著者について」セクションから取得しました。")
                return name_tag.text.strip()

        # 3. 詳細情報テーブルから取得
        if data_from_table.get('著者'):
            self.logger("  - 著者情報を詳細情報テーブルから取得しました。")
            return data_from_table.get('著者')
            
        return ""

    def _scrape_product_data(self, url):
        self.logger(f"🔍 URLを解析中: {url[:60]}...")
        max_retries = self.config.get('max_retries', 3)
        retry_delay = self.config.get('retry_delay', 5.0)

        for attempt in range(max_retries + 1):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                data = {}

                # ▼▼▼ 改善点: ASIN抽出の正規表現を修正 ▼▼▼
                asin_match = re.search(r'/(dp|gp/product)/([A-Z0-9]{10})', url)
                data['ASIN'] = asin_match.group(2) if asin_match else 'N/A'

                # --- 共通情報 ---
                # ▼▼▼ 改善点: 商品名をより堅牢に取得 ▼▼▼
                title_tag = soup.find('span', id='productTitle')
                if title_tag:
                    full_title = title_tag.text.strip()
                    cleaned_title = re.sub(r'\s*\(.+?\)$|\s*\[.+?\]$', '', full_title).strip()
                    data['商品名'] = cleaned_title
                else:
                    data['商品名'] = ''
                
                price_whole = soup.select_one('.a-price-whole')
                data['価格'] = price_whole.text.strip().replace(',', '') if price_whole else ''
                
                feature_ul = soup.find('ul', class_='a-unordered-list a-vertical a-spacing-mini')
                if feature_ul:
                    features = [li.text.strip() for li in feature_ul.find_all('li')]
                    data['商品の特徴'] = "\n".join(features)

                # --- 詳細情報の取得 ---
                details_section_list = soup.find('div', id='detailBullets_feature_div')
                if details_section_list:
                    self.logger("  - 詳細情報(detailBullets List)を解析中...")
                    for li in details_section_list.select('li'):
                        key_tag = li.select_one('span.a-text-bold')
                        if not key_tag: continue
                        key = self._clean_key(key_tag.text)
                        
                        if "Amazon売れ筋ランキング" in key:
                            value = li.text.replace(key_tag.text, '').strip()
                            data['Amazon 売れ筋ランキング'] = re.sub(r'\s+', ' ', value)
                        elif "カスタマーレビュー" in key:
                            rating_span = li.select_one('span.a-icon-alt')
                            data['カスタマーレビュー評価'] = rating_span.text.strip() if rating_span else ''
                            count_span = li.select_one('#acrCustomerReviewText')
                            data['カスタマーレビュー数'] = count_span.text.strip() if count_span else ''
                        else:
                            value_span = key_tag.find_next_sibling('span')
                            if value_span and key not in data:
                                data[key] = value_span.text.strip()
                
                details_table_book = soup.find('table', id='productDetails_detailBullets_sections1')
                if details_table_book:
                    self.logger("  - 詳細情報(Book Table)を解析中...")
                    self._parse_details_table(details_table_book, data)

                details_table_tech = soup.find('table', id='productDetails_techSpec_section_1')
                if details_table_tech:
                    self.logger("  - 詳細情報(Tech Spec Table)を解析中...")
                    self._parse_details_table(details_table_tech, data)
                
                # --- モード別情報の取得 ---
                if self.mode == '書籍':
                    data['著者'] = self._get_authors(soup, data)
                    page_info_found = False
                    page_keys = ['単行本', '文庫', 'ペーパーバック', '単行本（ソフトカバー）', '大型本']
                    for p_key in page_keys:
                        if p_key in data and 'ページ' in data[p_key]:
                            data['ページ数'] = data[p_key]
                            page_info_found = True
                            break
                    if not page_info_found:
                        for key, value in data.items():
                            if 'ページ' in str(value):
                                data['ページ数'] = value
                                break
                else: # 電気製品モード
                    byline_tag = soup.find('div', id='bylineInfo_feature_div')
                    if byline_tag:
                        data['ブランド'] = byline_tag.text.strip()

                self.logger("✅ 解析成功。")
                return data

            except requests.exceptions.RequestException as e:
                self.logger(f"❌ リクエストエラー (試行 {attempt + 1}/{max_retries + 1}): {e}")
                if attempt < max_retries:
                    wait_time = retry_delay * (2 ** attempt)
                    self.logger(f"🔄 {wait_time:.1f}秒待機して再試行します...")
                    time.sleep(wait_time)
                else:
                    self.logger("❌ 最大再試行回数に達しました。")
                    return None
        return None

    def _check_and_create_headers(self):
        self.logger("🔍 ヘッダーの確認...")
        try:
            start_col_letter = self.config['output_start_col_letter'].upper()
            
            current_headers = self.sheet.row_values(1)
            start_col_num = self._column_letter_to_number(start_col_letter)

            if len(current_headers) < start_col_num + len(self.ALL_HEADERS):
                padding = (start_col_num + len(self.ALL_HEADERS)) - len(current_headers)
                current_headers.extend([""] * padding)
            
            actual_headers = current_headers[start_col_num - 1 : start_col_num - 1 + len(self.ALL_HEADERS)]

            if actual_headers != self.ALL_HEADERS:
                self.logger(f"ℹ️ '{self.mode}' モードのヘッダーを作成または更新します...")
                self.sheet.update(f"{start_col_letter}1", [self.ALL_HEADERS], value_input_option='USER_ENTERED')
                self.logger("✅ ヘッダーの作成/更新が完了しました。")
            else:
                self.logger("✅ ヘッダーは既に存在します。")
        except Exception as e:
            self.logger(f"⚠️ ヘッダーの確認・作成中にエラーが発生しました: {e}")
            raise

    def run_process(self):
        try:
            self.logger(f"\n🚀 Amazon商品情報スクレイピング処理開始 ({self.mode}モード) 🚀")
            self._check_and_create_headers()
        except Exception as e:
            self.logger(f"CRITICAL: ヘッダーの準備に失敗したため、処理を中止します。: {e}")
            return

        current_row = self.config["start_row"]
        url_col_num = self._column_letter_to_number(self.config["url_col_letter"])
        output_start_col_letter = self.config["output_start_col_letter"]
        consecutive_empty_count = 0

        while True:
            self.logger(f"\n--- {current_row}行目の処理を開始 ---")
            try:
                row_values = self.sheet.row_values(current_row)
                url = row_values[url_col_num - 1] if len(row_values) >= url_col_num else None
            except gspread.exceptions.APIError as e:
                 if e.response.status_code == 400:
                    self.logger("ℹ️ これ以上処理する行がありません。処理を終了します。")
                    break
                 else:
                    self.logger(f"❌ Google APIエラー: {e}")
                    break
            except Exception as e:
                self.logger(f"❌ {current_row}行目のデータ読み込みに失敗しました: {e}")
                break

            if not url or not url.strip():
                consecutive_empty_count += 1
                self.logger(f"ℹ️ URLが空です。({consecutive_empty_count}/10)")
                if consecutive_empty_count >= 10:
                    self.logger("🛑 10件連続でURLが空のため、処理を終了します。")
                    break
                current_row += 1
                continue
            
            consecutive_empty_count = 0
            
            scraped_data = self._scrape_product_data(url)
            
            if scraped_data:
                self.logger(f"📝 {current_row}行目に取得した情報を書き込みます...")
                values_to_write = [scraped_data.get(header, "") for header in self.ALL_HEADERS]
                
                self.sheet.update(f"{output_start_col_letter}{current_row}", [values_to_write], value_input_option='USER_ENTERED')
                self.logger("✅ 書き込み完了。")
            else:
                self.logger(f"⚠️ {current_row}行目のURLの情報取得に失敗しました。")

            time.sleep(self.config.get("delay", 3))
            current_row += 1
        
        self.logger("\n🎉 全処理完了！ 🎉")
