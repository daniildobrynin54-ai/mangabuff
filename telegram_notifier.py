"""Модуль для отправки уведомлений в Telegram с защитой от дублирования."""

import os
import json
import requests
from typing import Optional, List, Dict, Any
from datetime import datetime
from config import OUTPUT_DIR, SENT_CARDS_FILE


class TelegramNotifier:
    """Отправщик уведомлений в Telegram с защитой от дублей."""
    
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        thread_id: Optional[int] = None,
        enabled: bool = True
    ):
        """
        Инициализация Telegram бота.
        
        Args:
            bot_token: Токен бота
            chat_id: ID чата/группы
            thread_id: ID темы (опционально)
            enabled: Включен ли бот
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.enabled = enabled and bool(bot_token) and bool(chat_id)
        self.api_url = f"https://api.telegram.org/bot{bot_token}" if bot_token else None
        self.sent_cards_file = os.path.join(OUTPUT_DIR, SENT_CARDS_FILE)
        self._sent_cards = self._load_sent_cards()
    
    def _load_sent_cards(self) -> Dict[int, Dict[str, Any]]:
        """
        🔧 НОВОЕ: Загружает историю отправленных карт.
        
        Returns:
            Словарь {card_id: {timestamp, name, ...}}
        """
        try:
            if os.path.exists(self.sent_cards_file):
                with open(self.sent_cards_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"⚠️  Ошибка загрузки истории отправленных карт: {e}")
        
        return {}
    
    def _save_sent_cards(self) -> None:
        """🔧 НОВОЕ: Сохраняет историю отправленных карт."""
        try:
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            with open(self.sent_cards_file, 'w', encoding='utf-8') as f:
                json.dump(self._sent_cards, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️  Ошибка сохранения истории: {e}")
    
    def _is_card_already_sent(self, card_id: int) -> bool:
        """
        🔧 НОВОЕ: Проверяет, была ли уже отправлена эта карта.
        
        Args:
            card_id: ID карты
        
        Returns:
            True если карта уже отправлялась сегодня
        """
        card_id_str = str(card_id)
        
        if card_id_str not in self._sent_cards:
            return False
        
        # Проверяем дату отправки
        sent_info = self._sent_cards[card_id_str]
        sent_date = sent_info.get('date', '')
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Если карта отправлена сегодня - это дубль
        return sent_date == today
    
    def _mark_card_as_sent(self, card_id: int, card_name: str) -> None:
        """🔧 НОВОЕ: Отмечает карту как отправленную."""
        card_id_str = str(card_id)
        
        self._sent_cards[card_id_str] = {
            'name': card_name,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat()
        }
        
        self._save_sent_cards()
    
    def is_enabled(self) -> bool:
        """Проверяет, включен ли бот."""
        return self.enabled
    
    def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = False
    ) -> bool:
        """Отправляет текстовое сообщение."""
        if not self.enabled:
            return False
        
        try:
            url = f"{self.api_url}/sendMessage"
            
            data = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview
            }
            
            if self.thread_id:
                data["message_thread_id"] = self.thread_id
            
            response = requests.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                return True
            else:
                print(f"⚠️  Telegram API error: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"⚠️  Telegram send error: {e}")
            return False
    
    def send_photo(
        self,
        photo_url: str,
        caption: str = "",
        parse_mode: str = "HTML"
    ) -> bool:
        """Отправляет фото с подписью."""
        if not self.enabled:
            return False
        
        try:
            url = f"{self.api_url}/sendPhoto"
            
            data = {
                "chat_id": self.chat_id,
                "photo": photo_url,
                "caption": caption,
                "parse_mode": parse_mode
            }
            
            if self.thread_id:
                data["message_thread_id"] = self.thread_id
            
            response = requests.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                return True
            else:
                print(f"⚠️  Telegram API error: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"⚠️  Telegram send error: {e}")
            return False
    
    def notify_card_change(
        self,
        card_info: Dict[str, Any],
        boost_url: str,
        club_members: List[Dict[str, str]]
    ) -> bool:
        """
        🔧 ИСПРАВЛЕНО: Отправляет уведомление с проверкой на дубли.
        
        Args:
            card_info: Информация о карте
            boost_url: URL страницы буста
            club_members: Список участников клуба с картой
        
        Returns:
            True если успешно
        """
        if not self.enabled:
            return False
        
        card_id = card_info.get('card_id')
        card_name = card_info.get('name', 'Неизвестно')
        
        # 🔧 ПРОВЕРКА: Была ли уже отправлена эта карта сегодня
        if self._is_card_already_sent(card_id):
            print(f"ℹ️  Карта {card_name} (ID: {card_id}) уже отправлялась в Telegram сегодня")
            return False
        
        # Формируем текст сообщения
        rank = card_info.get('rank', '?')
        owners = card_info.get('owners_count', '?')
        wanters = card_info.get('wanters_count', '?')
        
        # Время
        current_time = datetime.now().strftime('%H:%M:%S')
        
        # Формируем список участников
        if club_members:
            members_text = ", ".join([m['nickname'] for m in club_members])
            members_line = f"\nКарта есть у: {members_text}"
        else:
            members_line = "\nКарты ни у кого из клуба нет"
        
        # Формируем сообщение в HTML формате
        message = (
            f"<b>🎴 Карта сменилась</b>\n"
            f"🕐 {current_time}\n"
            f"<a href='{boost_url}'>{boost_url}</a>\n"
            f"\n"
            f"📝 <b>{card_name}</b>\n"
            f"🆔 ID: {card_id} | Ранг: {rank}\n"
            f"👥 Владельцев: {owners} | Желающих: {wanters}"
            f"{members_line}"
        )
        
        # Получаем URL изображения карты
        card_image_url = card_info.get('image_url')
        
        # Отправляем
        success = False
        if card_image_url:
            success = self.send_photo(
                photo_url=card_image_url,
                caption=message,
                parse_mode="HTML"
            )
        else:
            success = self.send_message(
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=False
            )
        
        # 🔧 ОТМЕЧАЕМ: Карта отправлена
        if success:
            self._mark_card_as_sent(card_id, card_name)
            print(f"✅ Уведомление отправлено: {card_name} (ID: {card_id})")
        
        return success
    
    def test_connection(self) -> bool:
        """Тестирует подключение к Telegram."""
        if not self.enabled:
            print("⚠️  Telegram bot disabled")
            return False
        
        try:
            url = f"{self.api_url}/getMe"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    bot_info = data.get('result', {})
                    bot_name = bot_info.get('username', 'Unknown')
                    print(f"✅ Telegram bot connected: @{bot_name}")
                    return True
            
            print(f"⚠️  Telegram bot test failed: {response.status_code}")
            return False
            
        except Exception as e:
            print(f"⚠️  Telegram connection error: {e}")
            return False


def create_telegram_notifier(
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    thread_id: Optional[int] = None,
    enabled: bool = True
) -> TelegramNotifier:
    """Фабричная функция для создания Telegram notifier."""
    notifier = TelegramNotifier(bot_token, chat_id, thread_id, enabled)
    
    if notifier.is_enabled():
        notifier.test_connection()
    else:
        print("ℹ️  Telegram notifications disabled")
    
    return notifier