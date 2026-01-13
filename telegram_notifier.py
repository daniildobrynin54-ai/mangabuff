"""Модуль для отправки уведомлений в Telegram."""

import requests
from typing import Optional, List, Dict, Any
from datetime import datetime


class TelegramNotifier:
    """Отправщик уведомлений в Telegram."""
    
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
            bot_token: Токен бота (от @BotFather)
            chat_id: ID чата/группы (может быть отрицательным для групп)
            thread_id: ID темы в группе (опционально, для топиков)
            enabled: Включен ли бот
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.enabled = enabled and bool(bot_token) and bool(chat_id)
        self.api_url = f"https://api.telegram.org/bot{bot_token}" if bot_token else None
    
    def is_enabled(self) -> bool:
        """Проверяет, включен ли бот."""
        return self.enabled
    
    def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = False
    ) -> bool:
        """
        Отправляет текстовое сообщение.
        
        Args:
            text: Текст сообщения (поддерживает HTML или Markdown)
            parse_mode: Режим форматирования ("HTML" или "Markdown")
            disable_web_page_preview: Отключить превью ссылок
        
        Returns:
            True если успешно
        """
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
            
            # Добавляем thread_id если указан (для топиков)
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
        """
        Отправляет фото с подписью.
        
        Args:
            photo_url: URL изображения
            caption: Подпись к фото
            parse_mode: Режим форматирования
        
        Returns:
            True если успешно
        """
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
        Отправляет уведомление о смене карты в клубе.
        
        Args:
            card_info: Информация о карте
            boost_url: URL страницы буста
            club_members: Список участников клуба с картой
        
        Returns:
            True если успешно
        """
        if not self.enabled:
            return False
        
        # Формируем текст сообщения
        card_name = card_info.get('name', 'Неизвестно')
        card_id = card_info.get('card_id', '?')
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
            f"<b>Карта сменилась</b>\n"
            f"{current_time}\n"
            f"<a href='{boost_url}'>{boost_url}</a>\n"
            f"\n"
            f"📝 <b>{card_name}</b>\n"
            f"🆔 ID: {card_id} | Ранг: {rank}\n"
            f"👥 Владельцев: {owners} | Желающих: {wanters}"
            f"{members_line}"
        )
        
        # Получаем URL изображения карты
        card_image_url = card_info.get('image_url')
        
        # Если есть изображение - отправляем с фото, иначе просто текст
        if card_image_url:
            return self.send_photo(
                photo_url=card_image_url,
                caption=message,
                parse_mode="HTML"
            )
        else:
            return self.send_message(
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=False
            )
    
    def test_connection(self) -> bool:
        """
        Тестирует подключение к Telegram.
        
        Returns:
            True если бот работает
        """
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
    """
    Фабричная функция для создания Telegram notifier.
    
    Args:
        bot_token: Токен бота
        chat_id: ID чата
        thread_id: ID темы (опционально)
        enabled: Включен ли бот
    
    Returns:
        TelegramNotifier
    """
    notifier = TelegramNotifier(bot_token, chat_id, thread_id, enabled)
    
    if notifier.is_enabled():
        notifier.test_connection()
    else:
        print("ℹ️  Telegram notifications disabled")
    
    return notifier