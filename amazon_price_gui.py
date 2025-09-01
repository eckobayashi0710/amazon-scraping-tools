# amazon_price_gui.py
# Amazon新品価格取得ツールのGUIとメイン処理 (在庫スコア対応版)

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
import threading
import os
import json
import time
import gspread
from google.oauth2.service_account import Credentials

try:
    from amazon_price_core import AmazonPriceScraper
except ImportError:
    print("エラー: amazon_price_core.py が同じディレクトリに見つかりません。")
    exit()

class App(tk.Tk):
    CONFIG_FILE = "amazon_price_config.json"
    MAX_OFFERS_TO_DISPLAY = 10 #シートに出力する最大出品者数

    def __init__(self):
        super().__init__()
        self.title("Amazon価格・在庫 取得ツール (v5.3)")
        self.geometry("800x680")

        self.config_vars = {
            "json_path": tk.StringVar(),
            "spreadsheet_id": tk.StringVar(),
            "sheet_name": tk.StringVar(),
            "main_page_url_col_letter": tk.StringVar(value="A"),
            "side_panel_url_col_letter": tk.StringVar(value="B"),
            "output_start_col_letter": tk.StringVar(value="C"),
            "start_row": tk.IntVar(value=2),
            "headless_mode": tk.BooleanVar(value=True),
            "price_range_lower": tk.DoubleVar(value=0.85),
            "price_range_upper": tk.DoubleVar(value=1.15),
        }

        self.create_widgets()
        self.load_config()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        settings_frame = ttk.LabelFrame(main_frame, text="設定", padding="10")
        settings_frame.pack(fill=tk.X, expand=True)

        ttk.Label(settings_frame, text="Google認証JSON:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        json_frame = ttk.Frame(settings_frame)
        json_frame.grid(row=0, column=1, sticky=tk.EW)
        ttk.Entry(json_frame, textvariable=self.config_vars["json_path"], width=50).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(json_frame, text="参照...", command=self.browse_json).pack(side=tk.LEFT, padx=(5,0))

        ttk.Label(settings_frame, text="スプレッドシートID:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(settings_frame, textvariable=self.config_vars["spreadsheet_id"]).grid(row=1, column=1, sticky=tk.EW)

        ttk.Label(settings_frame, text="シート名:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(settings_frame, textvariable=self.config_vars["sheet_name"]).grid(row=2, column=1, sticky=tk.EW)

        col_frame = ttk.Frame(settings_frame)
        col_frame.grid(row=3, column=1, sticky=tk.EW, pady=2)
        ttk.Label(settings_frame, text="URL列 (メイン/サイド) / 出力開始列:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        
        ttk.Entry(col_frame, textvariable=self.config_vars["main_page_url_col_letter"], width=5).pack(side=tk.LEFT)
        ttk.Label(col_frame, text="/").pack(side=tk.LEFT, padx=5)
        ttk.Entry(col_frame, textvariable=self.config_vars["side_panel_url_col_letter"], width=5).pack(side=tk.LEFT)
        ttk.Label(col_frame, text="/").pack(side=tk.LEFT, padx=5)
        ttk.Entry(col_frame, textvariable=self.config_vars["output_start_col_letter"], width=5).pack(side=tk.LEFT)

        ttk.Label(settings_frame, text="開始行:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(settings_frame, textvariable=self.config_vars["start_row"], width=5).grid(row=4, column=1, sticky=tk.W)
        
        ttk.Label(settings_frame, text="価格グループ倍率 (下限/上限):").grid(row=5, column=0, sticky=tk.W, padx=5, pady=5)
        range_frame = ttk.Frame(settings_frame)
        range_frame.grid(row=5, column=1, sticky=tk.W)
        ttk.Entry(range_frame, textvariable=self.config_vars["price_range_lower"], width=5).pack(side=tk.LEFT)
        ttk.Label(range_frame, text="/").pack(side=tk.LEFT, padx=5)
        ttk.Entry(range_frame, textvariable=self.config_vars["price_range_upper"], width=5).pack(side=tk.LEFT)

        headless_check = ttk.Checkbutton(
            settings_frame,
            text="ヘッドレスモードで実行 (ブラウザを非表示)",
            variable=self.config_vars["headless_mode"]
        )
        headless_check.grid(row=6, column=0, columnspan=2, sticky=tk.W, padx=5, pady=8)

        settings_frame.columnconfigure(1, weight=1)

        self.run_button = ttk.Button(main_frame, text="処理実行", command=self.start_process)
        self.run_button.pack(pady=10, fill=tk.X)

        log_frame = ttk.LabelFrame(main_frame, text="ログ", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=15)
        self.log_area.pack(fill=tk.BOTH, expand=True)

    def browse_json(self):
        file_path = filedialog.askopenfilename(title="Google Service Account JSONを選択", filetypes=[("JSON files", "*.json")])
        if file_path:
            self.config_vars["json_path"].set(file_path)

    def log(self, message):
        self.log_area.insert(tk.END, str(message) + '\n')
        self.log_area.see(tk.END)
        self.update_idletasks()

    def load_config(self):
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                for key, value in config_data.items():
                    if key in self.config_vars:
                        self.config_vars[key].set(value)
                self.log("ℹ️ 保存された設定を読み込みました。")
            except Exception as e:
                self.log(f"⚠️ 設定ファイルの読み込みに失敗しました: {e}")
        else:
            self.log("ℹ️ 設定ファイルが見つかりません。初回は各項目を設定してください。")

    def save_config(self):
        config_data = {key: var.get() for key, var in self.config_vars.items()}
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            self.log(f"💾 設定を {self.CONFIG_FILE} に保存しました。")
        except IOError as e:
            self.log(f"⚠️ 設定の保存に失敗しました: {e}")

    def on_closing(self):
        self.save_config()
        self.destroy()

    def start_process(self):
        config = {key: var.get() for key, var in self.config_vars.items()}
        if not all([config["json_path"], config["spreadsheet_id"], config["sheet_name"]]):
            self.log("❌ エラー: 認証JSON、スプレッドシートID、シート名は必須です。")
            return
        
        self.save_config()
        self.run_button.config(state=tk.DISABLED, text="処理中...")
        self.log_area.delete('1.0', tk.END)

        thread = threading.Thread(target=self.run_in_thread, args=(config,))
        thread.daemon = True
        thread.start()

    def _check_and_create_headers(self, sheet, start_col_letter):
        self.log("🔍 ヘッダーを確認中...")
        try:
            headers = [
                "最適価格", "最適価格コンディション", "最適価格出荷元", "最適価格販売元",
                "在庫判定", "在庫スコア", "実在庫数", "有効出品者数", "総出品者数", "FBA数", "FBM数",
                "購入ボックス価格", "購入ボックスコンディション", "購入ボックス出荷元", "購入ボックス販売元"
            ]
            for i in range(self.MAX_OFFERS_TO_DISPLAY):
                headers.extend([
                    f"出品{i+1} 価格", f"出品{i+1} 送料", f"出品{i+1} コンディション",
                    f"出品{i+1} 出荷元", f"出品{i+1} 販売元"
                ])
            
            sheet.update(f"{start_col_letter}1", [headers])
            self.log("✅ ヘッダー行を作成/更新しました。")
            return len(headers)
        except Exception as e:
            self.log(f"⚠️ ヘッダーの作成に失敗しました: {e}")
            return 0

    def run_in_thread(self, config):
        scraper = None
        try:
            self.log("🔧 Google Sheetsサービスを初期化中...")
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_file(config["json_path"], scopes=scopes)
            gc = gspread.authorize(creds)
            spreadsheet = gc.open_by_key(config["spreadsheet_id"])
            sheet = spreadsheet.worksheet(config["sheet_name"])
            self.log("✅ Google Sheets初期化完了。")

            num_of_output_cols = self._check_and_create_headers(sheet, config["output_start_col_letter"])
            if num_of_output_cols == 0:
                raise Exception("ヘッダーの作成に失敗したため、処理を中断します。")

            scraper = AmazonPriceScraper(logger_callback=self.log)
            if not scraper.initialize_driver(headless=config["headless_mode"]):
                raise Exception("WebDriverの初期化に失敗しました。")

            current_row = config["start_row"]
            main_url_col_num = gspread.utils.a1_to_rowcol(f"{config['main_page_url_col_letter']}1")[1]
            side_url_col_num = gspread.utils.a1_to_rowcol(f"{config['side_panel_url_col_letter']}1")[1]
            output_start_col_letter = config['output_start_col_letter']
            
            cells_to_clear = [[''] * num_of_output_cols]

            consecutive_empty_count = 0
            while True:
                self.log(f"\n--- {current_row}行目の処理を開始 ---")
                try:
                    row_values = sheet.row_values(current_row)
                    main_page_url = row_values[main_url_col_num - 1] if len(row_values) >= main_url_col_num else None
                    side_panel_url = row_values[side_url_col_num - 1] if len(row_values) >= side_url_col_num else None
                except gspread.exceptions.APIError as e:
                    if e.response.status_code == 400:
                        self.log("ℹ️ これ以上処理する行がありません。")
                        break
                    raise
                
                if not main_page_url or not side_panel_url or not main_page_url.strip().startswith("http") or not side_panel_url.strip().startswith("http"):
                    consecutive_empty_count += 1
                    self.log(f"ℹ️ URLが空か無効です。({consecutive_empty_count}/10)")
                    if consecutive_empty_count >= 10:
                        self.log("🛑 10件連続でURLが空のため、処理を終了します。")
                        break
                    current_row += 1
                    continue
                
                consecutive_empty_count = 0
                
                data = scraper.get_product_data(
                    main_page_url, 
                    side_panel_url,
                    config["price_range_lower"],
                    config["price_range_upper"]
                )
                
                values_to_write = []
                if data['status'] == 'success':
                    # --- 在庫スコア判定ロジック ---
                    stock_status = "不十分"
                    is_buybox_fba = 'Amazon' in data['buybox_info'].get('shipper', '')
                    inventory_score = data.get('inventory_score', 0)
                    
                    if (isinstance(data['real_stock'], int) and data['real_stock'] > 2 and is_buybox_fba) or \
                       (isinstance(inventory_score, int) and inventory_score >= 4):
                        stock_status = "十分"
                    # --- 判定ロジックここまで ---

                    buybox = data['buybox_info']
                    values_to_write.extend([
                        data.get('optimal_price', 'N/A'),
                        data.get('optimal_price_condition', 'N/A'),
                        data.get('optimal_price_shipper', 'N/A'),
                        data.get('optimal_price_seller', 'N/A'),
                        stock_status, data.get('inventory_score', 'N/A'), data['real_stock'], 
                        data.get('effective_sellers_count', 'N/A'), data['total_offers'],
                        data.get('fba_count', 'N/A'), data.get('fbm_count', 'N/A'),
                        buybox.get('price', ''), buybox.get('condition', ''), 
                        buybox.get('shipper', ''), buybox.get('seller', '')
                    ])
                    for offer in data['offers'][:self.MAX_OFFERS_TO_DISPLAY]:
                        values_to_write.extend([
                            offer.get('price', ''), offer.get('shipping_fee', ''),
                            offer.get('condition', ''), offer.get('shipper', ''), 
                            offer.get('seller', '')
                        ])
                else:
                    values_to_write = ["エラー"] * 15

                self.log(f"  => 書き込みデータ: {values_to_write}")
                
                self.log(f"  - {current_row}行目の出力範囲をクリアします。")
                sheet.update(f"{output_start_col_letter}{current_row}", cells_to_clear, value_input_option='USER_ENTERED')
                
                if values_to_write:
                    sheet.update(f"{output_start_col_letter}{current_row}", [values_to_write], value_input_option='USER_ENTERED')
                self.log(f"  => {output_start_col_letter}{current_row} から書き込みました。")

                time.sleep(2)
                current_row += 1

        except Exception as e:
            self.log(f"\n❌ 処理中にエラーが発生しました: {e}")
        finally:
            if scraper:
                scraper.close_driver()
            self.run_button.config(state=tk.NORMAL, text="処理実行")
            self.log("\n🎉 全処理完了！ 🎉")

if __name__ == "__main__":
    app = App()
    app.mainloop()
