# amazon_price_core.py
# Seleniumを使用してAmazon商品ページから価格・在庫・出品者情報を取得するコアロジック (在庫スコア対応版)

import time
import re
import statistics
from urllib.parse import urlparse, parse_qs

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

from bs4 import BeautifulSoup

class AmazonPriceScraper:
    """
    Seleniumを使用し、メインページとサイドパネルを組み合わせて
    Amazonの価格、在庫、出品者情報を取得するクラス。
    """
    def __init__(self, logger_callback=print):
        self.logger = logger_callback
        self.driver = None

    def initialize_driver(self, headless=False):
        """Selenium WebDriverを初期化する。"""
        if not SELENIUM_AVAILABLE:
            self.logger("致命的エラー: Seleniumライブラリが見つかりません。")
            self.logger("ターミナルで 'pip install selenium webdriver-manager beautifulsoup4' を実行してください。")
            return False
        try:
            self.logger("🔧 Chromeドライバを初期化中...")
            service = ChromeService(ChromeDriverManager().install())
            options = webdriver.ChromeOptions()
            
            if headless:
                self.logger("  - ヘッドレスモードで実行します。")
                options.add_argument('--headless')
            
            options.add_argument('--log-level=3')
            options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            self.driver = webdriver.Chrome(service=service, options=options)
            self.logger("✅ Chromeドライバの初期化完了。")
            return True
        except Exception as e:
            self.logger(f"❌ Chromeドライバの初期化に失敗しました: {e}")
            return False

    def get_product_data(self, main_page_url, side_panel_url, lower_multiplier=0.85, upper_multiplier=1.15):
        """
        指定されたURLからハイブリッド戦略でデータを取得する。
        """
        if not self.driver:
            self.logger("❌ ドライバが初期化されていません。")
            return self._get_error_result()

        try:
            # --- ステップ1: メインページから購入ボックス情報取得 ---
            self.logger(f"🚀 メインページにアクセスします: {main_page_url[:70]}...")
            self.driver.get(main_page_url)
            WebDriverWait(self.driver, 15).until(EC.presence_of_element_located((By.ID, "dp-container")))
            self.logger("✅ メインページのコンテナを発見。")
            
            main_page_soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            buybox_data = self._parse_main_page_buybox(main_page_soup)
            self.logger(f"  - 実在庫数: {buybox_data['real_stock']}, 購入ボックス価格: {buybox_data['price']}")

            # --- ステップ2: サイドパネルから全出品者情報取得 (常時フィルタリング) ---
            side_offers = self._get_filtered_side_panel_offers(side_panel_url)

            # --- ステップ3: 全出品者情報を統合 ---
            all_offers = []
            if isinstance(buybox_data.get('price'), int):
                 all_offers.append(buybox_data)
            all_offers.extend(side_offers)
            
            unique_offers = []
            seen = set()
            for offer in all_offers:
                identifier = (offer.get('price'), offer.get('seller'), offer.get('shipper'))
                if identifier not in seen:
                    unique_offers.append(offer)
                    seen.add(identifier)
            
            total_offers_count = len(unique_offers)
            self.logger(f"🔍 全{total_offers_count}件の出品情報を処理します。")

            # --- FBA/FBMカウントと在庫スコア計算 ---
            fba_count = sum(1 for offer in unique_offers if 'Amazon' in offer.get('shipper', ''))
            fbm_count = total_offers_count - fba_count
            inventory_score = (fba_count * 2) + fbm_count
            self.logger(f"  - FBA数: {fba_count}, FBM数: {fbm_count}, 在庫スコア: {inventory_score}")
            
            # --- ステップ4: 最適価格の算出と有効出品者数の決定 ---
            optimal_price = 'N/A'
            optimal_price_condition = 'N/A'
            optimal_price_shipper = 'N/A'
            optimal_price_seller = 'N/A'
            effective_sellers_count = 0
            price_group = []

            is_buybox_fba = 'Amazon' in buybox_data.get('shipper', '')
            if buybox_data.get('real_stock', 0) > 2 and isinstance(buybox_data.get('price'), int) and is_buybox_fba:
                self.logger("  - 実在庫が3以上かつFBAのため、購入ボックス価格を最適価格とします。")
                optimal_price = buybox_data.get('price', 0) + buybox_data.get('shipping_fee', 0)
                optimal_price_condition = buybox_data.get('condition', 'N/A')
                optimal_price_shipper = buybox_data.get('shipper', 'N/A')
                optimal_price_seller = buybox_data.get('seller', 'N/A')
                price_group = unique_offers
                effective_sellers_count = len(price_group)
            else:
                self.logger("  - 購入ボックスが条件を満たさないため、価格グループで最適価格を判断します。")
                sorted_for_grouping = sorted(unique_offers, key=lambda x: x.get('price', float('inf')) + x.get('shipping_fee', 0))

                if len(sorted_for_grouping) >= 3:
                    self.logger("    - 価格グループを作成し、有効出品者数を計算します...")
                    base_price_item = sorted_for_grouping[2]
                    base_price = base_price_item.get('price', 0) + base_price_item.get('shipping_fee', 0)
                    
                    price_lower_bound = base_price * lower_multiplier
                    price_upper_bound = base_price * upper_multiplier
                    self.logger(f"    - 基準価格: ￥{base_price}, 有効範囲: ￥{price_lower_bound:.0f} ～ ￥{price_upper_bound:.0f}")

                    for offer in sorted_for_grouping:
                        offer_total_price = offer.get('price', 0) + offer.get('shipping_fee', 0)
                        if price_lower_bound <= offer_total_price <= price_upper_bound:
                            price_group.append(offer)
                    
                    effective_sellers_count = len(price_group)
                    self.logger(f"    - 有効出品者数: {effective_sellers_count}件")

                    if effective_sellers_count >= 3:
                        sorted_price_group = sorted(price_group, key=lambda x: x.get('price', 0) + x.get('shipping_fee', 0))
                        
                        n = len(sorted_price_group)
                        if n % 2 == 1:
                            median_index = n // 2
                            median_offer = sorted_price_group[median_index]
                        else:
                            median_index = n // 2 - 1
                            median_offer = sorted_price_group[median_index]
                        
                        optimal_price = median_offer.get('price', 0) + median_offer.get('shipping_fee', 0)
                        optimal_price_condition = median_offer.get('condition', 'N/A')
                        optimal_price_shipper = median_offer.get('shipper', 'N/A')
                        optimal_price_seller = median_offer.get('seller', 'N/A')
                        self.logger(f"    - 最適価格(中央値): ￥{optimal_price:.0f}, コンディション: {optimal_price_condition}")
                else:
                    self.logger("    - 出品者数が3件未満のため、価格グループは作成しません。")
                    price_group = sorted_for_grouping
                    effective_sellers_count = len(price_group)

            # --- ステップ5: 購入ボックス出品の重複を最終リストから削除 ---
            display_offers = []
            buybox_identifier = (buybox_data.get('price'), buybox_data.get('seller'), buybox_data.get('shipper'))
            
            for offer in price_group:
                offer_identifier = (offer.get('price'), offer.get('seller'), offer.get('shipper'))
                if offer_identifier != buybox_identifier:
                    display_offers.append(offer)
            
            sorted_display_offers = sorted(display_offers, key=lambda x: x.get('price', float('inf')) + x.get('shipping_fee', 0))

            return {
                'status': 'success',
                'real_stock': buybox_data['real_stock'],
                'total_offers': total_offers_count,
                'fba_count': fba_count,
                'fbm_count': fbm_count,
                'inventory_score': inventory_score,
                'effective_sellers_count': effective_sellers_count,
                'buybox_info': buybox_data,
                'offers': sorted_display_offers,
                'optimal_price': optimal_price,
                'optimal_price_condition': optimal_price_condition,
                'optimal_price_shipper': optimal_price_shipper,
                'optimal_price_seller': optimal_price_seller
            }

        except Exception as e:
            self.logger(f"❌ データ取得中に予期せぬエラーが発生しました: {e}")
            return self._get_error_result()

    def _get_filtered_side_panel_offers(self, side_panel_url):
        """サイドパネルにアクセスし、新品フィルターを確実に適用して出品者情報を取得する"""
        self.logger(f"🚀 サイドパネルにアクセスします...")
        self.driver.get(side_panel_url)
        WebDriverWait(self.driver, 15).until(EC.presence_of_element_located((By.ID, "aod-container")))
        self.logger("✅ サイドパネルのコンテナを発見。")
        
        self.logger("  - 「新品」フィルターの適用を試みます...")
        try:
            filter_button = self.driver.find_element(By.ID, "aod-show-filter-button")
            filter_button.click()
            self.logger("    ▶️ 「絞り込み」ボタンをクリックしました。")
            time.sleep(1)
            new_filter = self.driver.find_element(By.ID, "new")
            new_filter.click()
            self.logger("    ▶️ 「新品」フィルターをクリックしました。")
            
            self.logger("    ⏳ フィルター適用を待機中...")
            WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.ID, "aod-swatch-id-new"))
            )
            self.logger("    ✅ フィルター適用完了。")
            time.sleep(1)
        except Exception as filter_e:
            self.logger(f"    ⚠️ フィルター操作は不要か、または失敗しました。現在のページを解析します。")
        
        self.logger("    🔍 フィルタリング後のHTMLを解析します...")
        side_panel_soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        side_offers = self._parse_side_panel_offers(side_panel_soup)
        
        return side_offers


    def _parse_main_page_buybox(self, soup):
        """メインページの購入ボックスから情報を抽出する"""
        data = {'price': 'N/A', 'seller': 'N/A', 'shipper': 'N/A', 'real_stock': 0, 'shipping_fee': 0, 'condition': 'N/A'}
        
        price_span = soup.select_one('#corePrice_feature_div .a-price .a-offscreen')
        if price_span:
            data['price'] = self._clean_price(price_span.text)
            if isinstance(data['price'], int):
                data['condition'] = '新品'

        availability_div = soup.select_one('#availability')
        if availability_div:
            availability_text = availability_div.get_text(strip=True)
            if "在庫あり" in availability_text:
                data['real_stock'] = 30
            else:
                match = re.search(r'残り(\d+)点', availability_text)
                if match:
                    data['real_stock'] = int(match.group(1))

        seller_feature = soup.select_one('#merchantInfoFeature_feature_div .offer-display-feature-text-message')
        if seller_feature:
            data['seller'] = seller_feature.get_text(strip=True)

        shipper_feature = soup.select_one('#fulfillerInfoFeature_feature_div .offer-display-feature-text-message')
        if shipper_feature:
            data['shipper'] = shipper_feature.get_text(strip=True)
        
        return data

    def _parse_side_panel_offers(self, soup):
        """サイドパネルからピン留め以外の全出品者の情報をリストとして抽出する"""
        offers = []
        offer_elements = soup.select('#aod-offer')

        for offer_el in offer_elements:
            condition_span = offer_el.select_one('#aod-offer-heading .a-text-bold')
            if not condition_span:
                continue
            
            condition_text = ' '.join(condition_span.get_text(strip=True).split())
            
            if '中古' in condition_text:
                continue

            price_span = offer_el.select_one('#aod-offer-price span.aok-offscreen, .a-price .a-offscreen')
            price = self._clean_price(price_span.text if price_span else None)
            if price is None:
                continue

            shipping_fee = 0
            shipping_el = offer_el.select_one('[data-csa-c-delivery-price]')
            if shipping_el and 'data-csa-c-delivery-price' in shipping_el.attrs:
                shipping_fee = self._clean_shipping_fee(shipping_el['data-csa-c-delivery-price'])
            else:
                shipping_span = offer_el.select_one('#aod-offer-shipping-charge-string')
                if shipping_span:
                    shipping_fee = self._clean_shipping_fee(shipping_span.text)
            
            seller_el = offer_el.select_one('#aod-offer-soldBy a, #aod-offer-soldBy .a-size-small.a-color-base')
            seller = seller_el.get_text(strip=True) if seller_el else 'N/A'
            
            shipper_el = offer_el.select_one('#aod-offer-shipsFrom .a-size-small.a-color-base')
            shipper = shipper_el.get_text(strip=True) if shipper_el else 'N/A'

            offers.append({
                'price': price, 'shipping_fee': shipping_fee,
                'seller': seller, 'shipper': shipper,
                'condition': condition_text
            })
        
        return offers

    def _clean_price(self, price_text):
        if not price_text: return None
        try:
            numbers = re.findall(r'[\d,]+', price_text)
            if not numbers: return None
            price_digits = numbers[-1].replace(',', '')
            return int(price_digits) if price_digits else None
        except (ValueError, TypeError, IndexError):
            return None

    def _clean_shipping_fee(self, shipping_text):
        if not shipping_text: return 0
        if "無料" in shipping_text: return 0
        fee_digits = re.sub(r'[^\d]', '', shipping_text)
        return int(fee_digits) if fee_digits else 0

    def _get_error_result(self):
        return {
            'status': 'error', 'real_stock': 'エラー', 'total_offers': 'エラー',
            'fba_count': 'エラー', 'fbm_count': 'エラー', 'inventory_score': 'エラー',
            'buybox_info': {'price': 'エラー', 'seller': 'エラー', 'shipper': 'エラー', 'real_stock': 'エラー', 'condition': 'エラー'},
            'offers': [],
            'optimal_price': 'エラー', 'optimal_price_condition': 'エラー', 
            'optimal_price_shipper': 'エラー', 'optimal_price_seller': 'エラー',
            'effective_sellers_count': 'エラー'
        }

    def close_driver(self):
        if self.driver:
            self.driver.quit()
            self.logger("✅ Chromeドライバを終了しました。")
