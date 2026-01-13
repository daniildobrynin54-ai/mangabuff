"""Модуль для работы с обменами карт с улучшенной системой отслеживания."""

import json
import time
import threading
from typing import Any, Dict, Optional, Set, List
import requests
from bs4 import BeautifulSoup
from config import BASE_URL, REQUEST_TIMEOUT, CARD_API_DELAY


class TradeHistoryMonitor:
    """Монитор истории обменов для отслеживания отданных карт."""
    
    def __init__(self, session: requests.Session, user_id: int, inventory_manager, debug: bool = False):
        """
        Инициализация монитора истории.
        
        Args:
            session: Сессия requests
            user_id: ID пользователя
            inventory_manager: Менеджер инвентаря
            debug: Режим отладки
        """
        self.session = session
        self.user_id = user_id
        self.inventory_manager = inventory_manager
        self.debug = debug
        self.running = False
        self.thread = None
        self.last_trade_ids: Set[int] = set()
        self.traded_away_cards: Set[int] = set()  # card_id отданных карт
    
    def _log(self, message: str) -> None:
        """Выводит отладочное сообщение."""
        if self.debug:
            print(f"[HISTORY] {message}")
    
    def fetch_recent_trades(self) -> List[Dict[str, Any]]:
        """
        Загружает последние обмены пользователя.
        
        Returns:
            Список обменов с информацией о картах
        """
        url = f"{BASE_URL}/users/{self.user_id}/trades"
        
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                self._log(f"Ошибка загрузки истории: {response.status_code}")
                return []
            
            soup = BeautifulSoup(response.text, "html.parser")
            trades = []
            
            # Парсим каждый обмен
            for trade_elem in soup.select('.history__item'):
                trade_id_elem = trade_elem.get('data-id')
                if not trade_id_elem:
                    continue
                
                trade_id = int(trade_id_elem)
                
                # Извлекаем отданные карты (history__body--lost)
                lost_cards = []
                for lost_elem in trade_elem.select('.history__body--lost .history__body-item'):
                    href = lost_elem.get('href', '')
                    # Формат: /cards/85415/users
                    import re
                    match = re.search(r'/cards/(\d+)', href)
                    if match:
                        lost_cards.append(int(match.group(1)))
                
                # Извлекаем полученные карты (history__body--gained)
                gained_cards = []
                for gained_elem in trade_elem.select('.history__body--gained .history__body-item'):
                    href = gained_elem.get('href', '')
                    match = re.search(r'/cards/(\d+)', href)
                    if match:
                        gained_cards.append(int(match.group(1)))
                
                if lost_cards:  # Интересуют только обмены где мы отдали карты
                    trades.append({
                        'trade_id': trade_id,
                        'lost_cards': lost_cards,
                        'gained_cards': gained_cards
                    })
            
            return trades
            
        except Exception as e:
            self._log(f"Ошибка парсинга истории: {e}")
            return []
    
    def check_and_remove_traded_cards(self) -> int:
        """
        Проверяет историю и удаляет отданные карты из инвентаря.
        
        Returns:
            Количество удаленных карт
        """
        trades = self.fetch_recent_trades()
        
        if not trades:
            return 0
        
        removed_count = 0
        new_traded_cards = set()
        
        for trade in trades:
            trade_id = trade['trade_id']
            
            # Если это новый обмен
            if trade_id not in self.last_trade_ids:
                self._log(f"Новый обмен обнаружен: ID {trade_id}")
                
                # Обрабатываем отданные карты
                for card_id in trade['lost_cards']:
                    if card_id not in self.traded_away_cards:
                        self._log(f"  Отдана карта: {card_id}")
                        
                        # Удаляем из инвентаря
                        if self._remove_card_from_inventory(card_id):
                            removed_count += 1
                            self.traded_away_cards.add(card_id)
                            print(f"🗑️  Карта {card_id} удалена из инвентаря (завершенный обмен)")
                
                new_traded_cards.add(trade_id)
        
        # Обновляем список известных обменов
        self.last_trade_ids.update(new_traded_cards)
        
        return removed_count
    
    def _remove_card_from_inventory(self, card_id: int) -> bool:
        """
        Удаляет карту из инвентаря по card_id.
        
        Args:
            card_id: ID карты для удаления
        
        Returns:
            True если успешно удалено
        """
        try:
            inventory = self.inventory_manager.load_inventory()
            
            # Ищем и удаляем карту
            cards_to_remove = []
            for card in inventory:
                # Проверяем card_id в разных местах структуры
                c_id = card.get('card_id')
                if not c_id and isinstance(card.get('card'), dict):
                    c_id = card['card'].get('id')
                
                if c_id == card_id:
                    cards_to_remove.append(card)
            
            if not cards_to_remove:
                self._log(f"Карта {card_id} не найдена в инвентаре")
                return False
            
            # Удаляем первое совпадение (instance)
            inventory.remove(cards_to_remove[0])
            
            # Сохраняем обновленный инвентарь
            success = self.inventory_manager.save_inventory(inventory)
            
            if success:
                self._log(f"✅ Карта {card_id} удалена из инвентаря")
            
            return success
            
        except Exception as e:
            self._log(f"Ошибка удаления карты {card_id}: {e}")
            return False
    
    def monitor_loop(self, check_interval: int = 10):
        """
        Основной цикл мониторинга.
        
        Args:
            check_interval: Интервал проверки в секундах
        """
        self._log(f"Запущен мониторинг истории обменов (проверка каждые {check_interval}с)")
        
        # Начальная загрузка для установки baseline
        initial_trades = self.fetch_recent_trades()
        self.last_trade_ids = {t['trade_id'] for t in initial_trades}
        self._log(f"Начальное состояние: {len(self.last_trade_ids)} известных обменов")
        
        while self.running:
            try:
                removed = self.check_and_remove_traded_cards()
                
                if removed > 0:
                    self._log(f"Удалено карт из инвентаря: {removed}")
                
            except Exception as e:
                self._log(f"Ошибка в цикле мониторинга: {e}")
            
            time.sleep(check_interval)
    
    def start(self, check_interval: int = 10):
        """Запускает мониторинг в отдельном потоке."""
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
        print("📊 Мониторинг истории обменов запущен")
    
    def stop(self):
        """Останавливает мониторинг."""
        if not self.running:
            return
        
        self._log("Остановка мониторинга истории...")
        self.running = False
        
        if self.thread:
            self.thread.join(timeout=5)
        
        print("📊 Мониторинг истории остановлен")
    
    def force_check(self) -> int:
        """
        Принудительная проверка истории.
        
        Returns:
            Количество удаленных карт
        """
        return self.check_and_remove_traded_cards()


class TradeManager:
    """Менеджер обменов с прямой отправкой через API."""
    
    def __init__(self, session: requests.Session, debug: bool = False):
        """
        Инициализация менеджера обменов.
        
        Args:
            session: Сессия requests
            debug: Режим отладки
        """
        self.session = session
        self.debug = debug
        # Отслеживание отправленных обменов (owner_id, card_id)
        self.sent_trades: Set[tuple[int, int]] = set()
    
    def _log(self, message: str) -> None:
        """Выводит отладочное сообщение."""
        if self.debug:
            print(f"[TRADE] {message}")
    
    def _get_csrf_token(self) -> str:
        """Получает CSRF токен из заголовков сессии."""
        return self.session.headers.get('X-CSRF-TOKEN', '')
    
    def _prepare_headers(self, receiver_id: int) -> Dict[str, str]:
        """
        Подготавливает заголовки для запроса.
        
        Args:
            receiver_id: ID получателя
        
        Returns:
            Словарь заголовков
        """
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
        """
        Проверяет, является ли ответ успешным.
        
        Args:
            response: Ответ от сервера
        
        Returns:
            True если успешно
        """
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
    
    def has_trade_sent(self, receiver_id: int, card_id: int) -> bool:
        """
        Проверяет, был ли уже отправлен обмен этому владельцу на эту карту.
        
        Args:
            receiver_id: ID получателя
            card_id: ID карточки
        
        Returns:
            True если обмен уже отправлен
        """
        return (receiver_id, card_id) in self.sent_trades
    
    def mark_trade_sent(self, receiver_id: int, card_id: int) -> None:
        """
        Отмечает обмен как отправленный.
        
        Args:
            receiver_id: ID получателя
            card_id: ID карточки
        """
        self.sent_trades.add((receiver_id, card_id))
        self._log(f"Обмен помечен как отправленный: owner={receiver_id}, card_id={card_id}")
    
    def clear_sent_trades(self) -> None:
        """Очищает список отправленных обменов."""
        count = len(self.sent_trades)
        self.sent_trades.clear()
        self._log(f"Список отправленных обменов очищен ({count} записей)")
    
    def create_trade_direct_api(
        self,
        receiver_id: int,
        my_instance_id: int,
        his_instance_id: int
    ) -> bool:
        """
        ⚡ ПРЯМАЯ отправка обмена через API БЕЗ поиска instance_id.
        
        Args:
            receiver_id: ID получателя обмена
            my_instance_id: Instance ID моей карточки
            his_instance_id: Instance ID карточки получателя (УЖЕ ИЗВЕСТЕН)
        
        Returns:
            True если обмен успешно отправлен
        """
        url = f"{BASE_URL}/trades/create"
        headers = self._prepare_headers(receiver_id)
        
        # Формируем данные
        data = [
            ("receiver_id", int(receiver_id)),
            ("creator_card_ids[]", int(my_instance_id)),
            ("receiver_card_ids[]", int(his_instance_id)),
        ]
        
        self._log(f"⚡ ПРЯМАЯ отправка через API:")
        self._log(f"  receiver_id: {receiver_id}")
        self._log(f"  my_instance_id: {my_instance_id}")
        self._log(f"  his_instance_id: {his_instance_id}")
        
        try:
            response = self.session.post(
                url,
                data=data,
                headers=headers,
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT
            )
            
            self._log(f"Response status: {response.status_code}")
            
            if self._is_success_response(response):
                self._log("✅ Обмен успешно создан")
                return True
            
            if response.status_code == 422:
                self._log("❌ Карта уже участвует в обмене (422)")
                return False
            
            if response.status_code == 429:
                self._log("⚠️  Rate limit (429)")
                return False
            
            self._log(f"❌ Обмен не удался: {response.status_code}")
            return False
            
        except requests.RequestException as e:
            self._log(f"❌ Ошибка сети: {e}")
            return False
    
    def find_partner_card_instance(
        self,
        partner_id: int,
        card_id: int
    ) -> Optional[int]:
        """
        Находит instance_id карточки у партнера через API.
        
        Args:
            partner_id: ID партнера
            card_id: ID карточки
        
        Returns:
            Instance ID карточки или None
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
            max_attempts = 50
            attempts = 0
            
            while attempts < max_attempts:
                response = self.session.post(
                    url,
                    data={"offset": offset},
                    headers=headers,
                    timeout=REQUEST_TIMEOUT
                )
                
                if response.status_code != 200:
                    self._log(f"Ошибка API: {response.status_code}")
                    break
                
                data = response.json()
                cards = data.get("cards", [])
                
                if not cards:
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
                
                offset += len(cards)
                
                if len(cards) < 60:
                    break
                
                time.sleep(CARD_API_DELAY)
                attempts += 1
            
            self._log(f"❌ Instance_id не найден")
            return None
            
        except Exception as e:
            self._log(f"Ошибка поиска: {e}")
            return None
    
    def cancel_all_sent_trades(self, history_monitor: Optional[TradeHistoryMonitor] = None) -> bool:
        """
        Отменяет все отправленные обмены и обновляет историю.
        
        Args:
            history_monitor: Монитор истории для немедленной проверки
        
        Returns:
            True если успешно
        """
        url = f"{BASE_URL}/trades/rejectAll?type_trade=sender"
        
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{BASE_URL}/trades/offers",
        }
        
        self._log("Отмена всех отправленных обменов...")
        
        try:
            response = self.session.get(
                url,
                headers=headers,
                allow_redirects=True,
                timeout=REQUEST_TIMEOUT
            )
            
            self._log(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                # Очищаем список отправленных обменов
                self.clear_sent_trades()
                
                # Ждем обновления на сервере
                time.sleep(2)
                
                # Принудительная проверка истории
                if history_monitor:
                    self._log("Проверка истории обменов после отмены...")
                    removed = history_monitor.force_check()
                    if removed > 0:
                        print(f"🗑️  Удалено {removed} карт(ы) из инвентаря после проверки истории")
                
                return True
            
            return False
            
        except requests.RequestException as e:
            self._log(f"Ошибка сети: {e}")
            return False


def send_trade_direct(
    session: requests.Session,
    owner_id: int,
    owner_name: str,
    my_instance_id: int,
    his_instance_id: int,
    my_card_name: str = "",
    my_wanters: int = 0,
    trade_manager: Optional[TradeManager] = None,
    dry_run: bool = True,
    debug: bool = False
) -> bool:
    """
    ⚡ ПРЯМАЯ отправка обмена когда instance_id УЖЕ ИЗВЕСТЕН.
    
    Args:
        session: Сессия requests
        owner_id: ID владельца
        owner_name: Имя владельца
        my_instance_id: Instance ID моей карты
        his_instance_id: Instance ID карты владельца (УЖЕ ИЗВЕСТЕН!)
        my_card_name: Название моей карты
        my_wanters: Количество желающих
        trade_manager: Менеджер обменов
        dry_run: Тестовый режим
        debug: Режим отладки
    
    Returns:
        True если обмен отправлен успешно
    """
    if not trade_manager:
        trade_manager = TradeManager(session, debug)
    
    if dry_run:
        print(f"[DRY-RUN] ⚡ Прямой обмен → {owner_name}")
        print(f"           My: {my_instance_id}, His: {his_instance_id}")
        return True
    
    # Отправляем напрямую
    success = trade_manager.create_trade_direct_api(
        owner_id,
        my_instance_id,
        his_instance_id
    )
    
    if success:
        # Отмечаем (используем 0 для card_id т.к. нам не важно в данном контексте)
        trade_manager.mark_trade_sent(owner_id, 0)
        print(f"✅ Обмен отправлен → {owner_name} | {my_card_name} ({my_wanters} желающих)")
    else:
        print(f"❌ Ошибка → {owner_name}")
    
    return success


def send_trade_to_owner(
    session: requests.Session,
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
    """
    Отправляет обмен с автопоиском instance_id (старый метод).
    
    Для прямой отправки используйте send_trade_direct().
    """
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
    
    # Ищем instance_id
    his_instance_id = trade_manager.find_partner_card_instance(owner_id, his_card_id)
    
    if not his_instance_id:
        print(f"❌ Карта не найдена → {owner_name}")
        return False
    
    # Используем прямую отправку
    return send_trade_direct(
        session, owner_id, owner_name,
        my_instance_id, his_instance_id,
        my_card_name, my_wanters,
        trade_manager, dry_run, debug
    )


def cancel_all_sent_trades(
    session: requests.Session,
    trade_manager: Optional[TradeManager] = None,
    history_monitor: Optional[TradeHistoryMonitor] = None,
    debug: bool = False
) -> bool:
    """
    Отменяет все обмены с проверкой истории.
    
    Args:
        session: Сессия requests
        trade_manager: Менеджер обменов
        history_monitor: Монитор истории
        debug: Режим отладки
    
    Returns:
        True если успешно
    """
    if not trade_manager:
        trade_manager = TradeManager(session, debug)
    
    return trade_manager.cancel_all_sent_trades(history_monitor)