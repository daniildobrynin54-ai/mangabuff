"""Модуль для работы с обменами с отслеживанием статусов обменов."""

import json
import time
import threading
from typing import Any, Dict, Optional, Set, List
import requests
from bs4 import BeautifulSoup

from config import (
    BASE_URL,
    REQUEST_TIMEOUT,
    CARD_API_DELAY,
    CARDS_PER_BATCH
)
from rate_limiter import get_rate_limiter


class TradeHistoryMonitor:
    """Монитор истории обменов с отслеживанием статусов."""
    
    def __init__(
        self,
        session,
        user_id: int,
        inventory_manager,
        debug: bool = False
    ):
        self.session = session
        self.user_id = user_id
        self.inventory_manager = inventory_manager
        self.debug = debug
        self.running = False
        self.thread = None
        # 🔧 ИСПРАВЛЕНО: Храним статус каждого обмена
        self.trade_statuses: Dict[int, str] = {}  # trade_id -> status
        self.traded_away_cards: Set[int] = set()
    
    def _log(self, message: str) -> None:
        if self.debug:
            print(f"[HISTORY] {message}")
    
    def _parse_trade_status(self, trade_elem) -> str:
        """
        Определяет статус обмена.
        
        Returns:
            'completed' - завершен
            'cancelled' - отменен
            'pending' - в процессе
        """
        # Проверяем наличие индикаторов статуса
        if trade_elem.select_one('.history__item--completed'):
            return 'completed'
        
        if trade_elem.select_one('.history__item--cancelled'):
            return 'cancelled'
        
        # Проверяем текст статуса
        status_elem = trade_elem.select_one('.history__status')
        if status_elem:
            status_text = status_elem.get_text().lower()
            if 'отменен' in status_text or 'отклонен' in status_text:
                return 'cancelled'
            if 'завершен' in status_text or 'принят' in status_text:
                return 'completed'
        
        return 'pending'
    
    def fetch_recent_trades(self) -> List[Dict[str, Any]]:
        """Загружает последние обмены с их статусами."""
        url = f"{BASE_URL}/users/{self.user_id}/trades"
        
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                self._log(f"Ошибка загрузки истории: {response.status_code}")
                return []
            
            soup = BeautifulSoup(response.text, "html.parser")
            trades = []
            
            for trade_elem in soup.select('.history__item'):
                trade_id_elem = trade_elem.get('data-id')
                if not trade_id_elem:
                    continue
                
                trade_id = int(trade_id_elem)
                status = self._parse_trade_status(trade_elem)
                
                lost_cards = []
                for lost_elem in trade_elem.select('.history__body--lost .history__body-item'):
                    href = lost_elem.get('href', '')
                    import re
                    match = re.search(r'/cards/(\d+)', href)
                    if match:
                        lost_cards.append(int(match.group(1)))
                
                gained_cards = []
                for gained_elem in trade_elem.select('.history__body--gained .history__body-item'):
                    href = gained_elem.get('href', '')
                    match = re.search(r'/cards/(\d+)', href)
                    if match:
                        gained_cards.append(int(match.group(1)))
                
                if lost_cards:
                    trades.append({
                        'trade_id': trade_id,
                        'status': status,
                        'lost_cards': lost_cards,
                        'gained_cards': gained_cards
                    })
            
            return trades
            
        except Exception as e:
            self._log(f"Ошибка парсинга истории: {e}")
            return []
    
    def check_and_remove_traded_cards(self) -> int:
        """
        🔧 ИСПРАВЛЕНО: Проверяет историю с учетом статусов обменов.
        
        Логика:
        1. Если обмен новый и completed -> удаляем карту
        2. Если обмен был completed, а стал cancelled -> возвращаем карту
        3. Если обмен pending -> ничего не делаем
        """
        trades = self.fetch_recent_trades()
        
        if not trades:
            self._log("Нет записей в истории")
            return 0
        
        removed_count = 0
        restored_count = 0
        
        self._log(f"Проверка истории: найдено {len(trades)} записей")
        
        for trade in trades:
            trade_id = trade['trade_id']
            current_status = trade['status']
            previous_status = self.trade_statuses.get(trade_id)
            
            # 🔧 НОВАЯ ЛОГИКА: Обрабатываем изменения статуса
            
            # Случай 1: Новый завершенный обмен -> удаляем карты
            if previous_status is None and current_status == 'completed':
                self._log(f"Новый завершенный обмен: ID {trade_id}")
                
                for card_id in trade['lost_cards']:
                    if card_id not in self.traded_away_cards:
                        self._log(f"  Отдана карта: {card_id}")
                        
                        if self._remove_card_from_inventory(card_id):
                            removed_count += 1
                            self.traded_away_cards.add(card_id)
                            print(f"🗑️  Карта {card_id} удалена из инвентаря")
                        else:
                            self._log(f"  Не удалось удалить карту {card_id}")
                
                self.trade_statuses[trade_id] = 'completed'
            
            # Случай 2: Обмен был completed, стал cancelled -> возвращаем карты
            elif previous_status == 'completed' and current_status == 'cancelled':
                self._log(f"⚠️  Обмен {trade_id} отменен! Возвращаем карты в инвентарь")
                
                for card_id in trade['lost_cards']:
                    if card_id in self.traded_away_cards:
                        self._log(f"  Карта {card_id} возвращена в инвентарь")
                        self.traded_away_cards.discard(card_id)
                        restored_count += 1
                        print(f"♻️  Карта {card_id} возвращена в инвентарь (обмен отменен)")
                
                self.trade_statuses[trade_id] = 'cancelled'
            
            # Случай 3: Обмен pending -> просто обновляем статус
            elif previous_status != current_status:
                self._log(f"Обмен {trade_id}: {previous_status} -> {current_status}")
                self.trade_statuses[trade_id] = current_status
            
            # Случай 4: Статус не изменился
            else:
                if previous_status is None:
                    # Первая загрузка - просто сохраняем статус
                    self._log(f"Обмен {trade_id}: начальный статус = {current_status}")
                    self.trade_statuses[trade_id] = current_status
                else:
                    self._log(f"Обмен {trade_id} уже обработан (статус: {current_status})")
        
        if removed_count > 0:
            self._log(f"✅ Удалено карт: {removed_count}")
        if restored_count > 0:
            self._log(f"♻️  Возвращено карт: {restored_count}")
        if removed_count == 0 and restored_count == 0:
            self._log("Нет изменений в истории")
        
        return removed_count
    
    def _remove_card_from_inventory(self, card_id: int) -> bool:
        """Удаляет карту из инвентаря по card_id."""
        try:
            self._log(f"Попытка удаления карты {card_id} из инвентаря...")
            inventory = self.inventory_manager.load_inventory()
            
            if not inventory:
                self._log(f"Инвентарь пуст или не загружен")
                return False
            
            self._log(f"Загружен инвентарь: {len(inventory)} карт")
            
            cards_to_remove = []
            for card in inventory:
                c_id = card.get('card_id')
                if not c_id and isinstance(card.get('card'), dict):
                    c_id = card['card'].get('id')
                
                if c_id == card_id:
                    cards_to_remove.append(card)
                    self._log(f"Найдена карта для удаления: card_id={card_id}")
            
            if not cards_to_remove:
                self._log(f"Карта {card_id} не найдена в инвентаре")
                return False
            
            self._log(f"Найдено карт с ID {card_id}: {len(cards_to_remove)}")
            
            inventory.remove(cards_to_remove[0])
            success = self.inventory_manager.save_inventory(inventory)
            
            if success:
                self._log(f"✅ Карта {card_id} удалена из инвентаря ({len(inventory)} осталось)")
            else:
                self._log(f"❌ Не удалось сохранить инвентарь после удаления")
            
            return success
            
        except Exception as e:
            self._log(f"Ошибка удаления карты {card_id}: {e}")
            import traceback
            if self.debug:
                traceback.print_exc()
            return False
    
    def monitor_loop(self, check_interval: int = 10):
        """Основной цикл мониторинга."""
        self._log(f"Запущен мониторинг истории (каждые {check_interval}с)")
        
        # 🔧 ИСПРАВЛЕНО: При старте загружаем начальное состояние
        initial_trades = self.fetch_recent_trades()
        for trade in initial_trades:
            self.trade_statuses[trade['trade_id']] = trade['status']
        
        self._log(f"Начальное состояние: {len(self.trade_statuses)} обменов")
        
        check_count = 0
        
        while self.running:
            try:
                check_count += 1
                self._log(f"Проверка истории #{check_count}")
                
                removed = self.check_and_remove_traded_cards()
                
                if removed > 0:
                    self._log(f"✅ Изменений в этой проверке: {removed}")
                    print(f"[HISTORY] ✅ Обработано изменений: {removed}")
                else:
                    self._log(f"Нет изменений в истории")
                    
            except Exception as e:
                self._log(f"Ошибка в цикле: {e}")
                if self.debug:
                    import traceback
                    traceback.print_exc()
            
            time.sleep(check_interval)
    
    def start(self, check_interval: int = 10):
        """Запускает мониторинг."""
        if self.running:
            self._log("Мониторинг уже запущен")
            return
        
        self.running = True
        self.thread = threading.Thread(
            target=self.monitor_loop,
            args=(check_interval,),
            daemon=True
        )
        self.thread.start()
        print("📊 Мониторинг истории запущен")
    
    def stop(self):
        """Останавливает мониторинг."""
        if not self.running:
            return
        
        self._log("Остановка мониторинга...")
        self.running = False
        
        if self.thread:
            self.thread.join(timeout=5)
        
        print("📊 Мониторинг истории остановлен")
    
    def force_check(self) -> int:
        """Принудительная проверка."""
        self._log("🔍 Принудительная проверка истории обменов...")
        removed = self.check_and_remove_traded_cards()
        if removed > 0:
            self._log(f"✅ Принудительная проверка: обработано {removed} изменений")
            print(f"[HISTORY] ✅ Принудительная проверка: обработано {removed} изменений")
        else:
            self._log("Принудительная проверка: изменений нет")
        return removed


class TradeManager:
    """Менеджер обменов с исправленным поиском карт."""
    
    def __init__(self, session, debug: bool = False):
        self.session = session
        self.debug = debug
        self.sent_trades: Set[tuple[int, int]] = set()
        self.limiter = get_rate_limiter()
        # 🔧 НОВОЕ: Отслеживаем заблокированные карты (отправленные в обменах)
        self.locked_cards: Set[int] = set()  # instance_id карт в активных обменах
    
    def _log(self, message: str) -> None:
        if self.debug:
            print(f"[TRADE] {message}")
    
    def _get_csrf_token(self) -> str:
        """Получает CSRF токен."""
        return self.session.headers.get('X-CSRF-TOKEN', '')
    
    def _prepare_headers(self, receiver_id: int) -> Dict[str, str]:
        """Подготавливает заголовки."""
        headers = {
            "Referer": f"{BASE_URL}/trades/offers/{receiver_id}",
            "Origin": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        
        csrf_token = self._get_csrf_token()
        if csrf_token:
            headers["X-CSRF-TOKEN"] = csrf_token
        
        return headers
    
    def _is_success_response(self, response: requests.Response) -> bool:
        """Проверяет успешность ответа."""
        if response.status_code == 200:
            return True
            
        if response.status_code in (301, 302):
            location = response.headers.get("Location", "")
            if "/trades/" in location:
                return True
        
        try:
            data = response.json()
            if isinstance(data, dict):
                if data.get("success") or data.get("ok"):
                    return True
                
                if isinstance(data.get("trade"), dict) and data["trade"].get("id"):
                    return True
                
                body_text = json.dumps(data).lower()
                if any(word in body_text for word in ["успеш", "отправ", "создан"]):
                    return True
        except ValueError:
            pass
        
        body = (response.text or "").lower()
        if any(word in body for word in ["успеш", "отправ", "создан"]):
            return True
        
        return False
    
    def find_partner_card_instance(
        self,
        partner_id: int,
        card_id: int
    ) -> Optional[int]:
        """
        Поиск instance_id с правильным offset.
        
        Args:
            partner_id: ID партнера
            card_id: ID карточки
        
        Returns:
            Instance ID или None
        """
        self._log(f"🔍 Поиск instance_id карты {card_id} у владельца {partner_id}...")
        
        try:
            url = f"{BASE_URL}/trades/{partner_id}/availableCardsLoad"
            
            headers = {
                "Referer": f"{BASE_URL}/trades/offers/{partner_id}",
                "Origin": BASE_URL,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }
            
            csrf_token = self._get_csrf_token()
            if csrf_token:
                headers["X-CSRF-TOKEN"] = csrf_token
            
            offset = 0
            max_batches = 100
            batch_count = 0
            
            while batch_count < max_batches:
                self.limiter.wait_and_record()
                
                self._log(f"  Проверка батча offset={offset}")
                
                response = self.session.post(
                    url,
                    data={"offset": offset},
                    headers=headers,
                    timeout=REQUEST_TIMEOUT
                )
                
                if response.status_code == 429:
                    self._log("⚠️  Rate limit 429")
                    self.limiter.pause_for_429()
                    continue
                
                if response.status_code != 200:
                    self._log(f"Ошибка API: {response.status_code}")
                    break
                
                data = response.json()
                cards = data.get("cards", [])
                
                if not cards:
                    self._log(f"  Батч пуст, карта не найдена")
                    break
                
                for card in cards:
                    c_card_id = card.get("card_id")
                    
                    if isinstance(card.get("card"), dict):
                        c_card_id = card["card"].get("id") or c_card_id
                    
                    if c_card_id and int(c_card_id) == card_id:
                        instance_id = card.get("id")
                        if instance_id:
                            self._log(f"✅ Найден instance_id={instance_id}")
                            return int(instance_id)
                
                if len(cards) < 60:
                    self._log(f"  Последний батч, карта не найдена")
                    break
                
                offset += CARDS_PER_BATCH
                batch_count += 1
                
                time.sleep(CARD_API_DELAY)
            
            self._log(f"❌ Instance_id не найден (проверено батчей: {batch_count})")
            return None
            
        except Exception as e:
            self._log(f"Ошибка поиска: {e}")
            return None
    
    def create_trade_direct_api(
        self,
        receiver_id: int,
        my_instance_id: int,
        his_instance_id: int
    ) -> bool:
        """Прямая отправка обмена через API."""
        url = f"{BASE_URL}/trades/create"
        headers = self._prepare_headers(receiver_id)
        
        data = [
            ("receiver_id", int(receiver_id)),
            ("creator_card_ids[]", int(my_instance_id)),
            ("receiver_card_ids[]", int(his_instance_id)),
        ]
        
        self._log(f"⚡ ПРЯМАЯ отправка:")
        self._log(f"  receiver_id: {receiver_id}")
        self._log(f"  my_instance_id: {my_instance_id}")
        self._log(f"  his_instance_id: {his_instance_id}")
        
        try:
            self.limiter.wait_and_record()
            
            response = self.session.post(
                url,
                data=data,
                headers=headers,
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT
            )
            
            self._log(f"Response status: {response.status_code}")
            
            if response.status_code == 429:
                self._log("⚠️  Rate limit (429)")
                self.limiter.pause_for_429()
                return False
            
            if self._is_success_response(response):
                self._log("✅ Обмен успешно создан")
                # 🔧 НОВОЕ: Блокируем карту
                self.locked_cards.add(my_instance_id)
                return True
            
            if response.status_code == 422:
                self._log("❌ Карта уже участвует в обмене (422)")
                return False
            
            self._log(f"❌ Обмен не удался: {response.status_code}")
            return False
            
        except requests.RequestException as e:
            self._log(f"❌ Ошибка сети: {e}")
            return False
    
    def has_trade_sent(self, receiver_id: int, card_id: int) -> bool:
        """Проверяет, был ли отправлен обмен."""
        return (receiver_id, card_id) in self.sent_trades
    
    def is_my_card_locked(self, instance_id: int) -> bool:
        """🔧 НОВОЕ: Проверяет, заблокирована ли карта."""
        return instance_id in self.locked_cards
    
    def mark_trade_sent(self, receiver_id: int, card_id: int) -> None:
        """Отмечает обмен как отправленный."""
        self.sent_trades.add((receiver_id, card_id))
        self._log(f"Обмен помечен: owner={receiver_id}, card_id={card_id}")
    
    def clear_sent_trades(self) -> None:
        """🔧 ОБНОВЛЕНО: Очищает список отправленных обменов и разблокирует карты."""
        count = len(self.sent_trades)
        self.sent_trades.clear()
        self.locked_cards.clear()
        self._log(f"Список обменов очищен ({count} записей), карты разблокированы")
    
    def cancel_all_sent_trades(
        self,
        history_monitor: Optional[TradeHistoryMonitor] = None
    ) -> bool:
        """Отменяет все обмены."""
        url = f"{BASE_URL}/trades/rejectAll?type_trade=sender"
        
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{BASE_URL}/trades/offers",
        }
        
        self._log("Отмена всех обменов...")
        
        try:
            response = self.session.get(
                url,
                headers=headers,
                allow_redirects=True,
                timeout=REQUEST_TIMEOUT
            )
            
            self._log(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                self.clear_sent_trades()
                time.sleep(2)
                
                if history_monitor:
                    self._log("Проверка истории...")
                    removed = history_monitor.force_check()
                    if removed > 0:
                        print(f"🗑️  Обработано {removed} изменений в инвентаре")
                
                return True
            
            return False
            
        except requests.RequestException as e:
            self._log(f"Ошибка сети: {e}")
            return False


def send_trade_to_owner(
    session,
    owner_id: int,
    owner_name: str,
    my_instance_id: int,
    his_card_id: int,
    my_card_name: str = "",
    my_wanters: int = 0,
    trade_manager: Optional[TradeManager] = None,
    dry_run: bool = True,
    debug: bool = False
) -> bool:
    """Отправляет обмен владельцу."""
    if not my_instance_id:
        if debug:
            print(f"[TRADE] Отсутствует my_instance_id")
        return False
    
    if not trade_manager:
        trade_manager = TradeManager(session, debug)
    
    if not dry_run and trade_manager.has_trade_sent(owner_id, his_card_id):
        if debug:
            print(f"[TRADE] Обмен уже отправлен {owner_name}")
        print(f"⏭️  Обмен уже отправлен → {owner_name}")
        return False
    
    if dry_run:
        print(f"[DRY-RUN] 📤 Обмен → {owner_name}")
        return True
    
    his_instance_id = trade_manager.find_partner_card_instance(owner_id, his_card_id)
    
    if not his_instance_id:
        print(f"❌ Карта не найдена → {owner_name}")
        return False
    
    success = trade_manager.create_trade_direct_api(
        owner_id,
        my_instance_id,
        his_instance_id
    )
    
    if success:
        trade_manager.mark_trade_sent(owner_id, his_card_id)
        print(f"✅ Обмен отправлен → {owner_name} | {my_card_name} ({my_wanters} желающих)")
    else:
        print(f"❌ Ошибка → {owner_name}")
    
    return success


def cancel_all_sent_trades(
    session,
    trade_manager: Optional[TradeManager] = None,
    history_monitor: Optional[TradeHistoryMonitor] = None,
    debug: bool = False
) -> bool:
    """Отменяет все обмены."""
    if not trade_manager:
        trade_manager = TradeManager(session, debug)
    
    return trade_manager.cancel_all_sent_trades(history_monitor)