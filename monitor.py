import threading
import time
import json
import os
from typing import Optional
import requests
from bs4 import BeautifulSoup
from config import BASE_URL
from boost import get_boost_card_info
from trade import cancel_all_sent_trades


class BoostMonitor:
    """Монитор страницы буста клуба"""
    
    def __init__(self, session: requests.Session, club_url: str, output_dir: str = "created_files"):
        self.session = session
        self.club_url = club_url
        self.output_dir = output_dir
        self.running = False
        self.thread = None
        self.boost_available = False
        self.card_changed = False  # Флаг изменения карты
        self.current_card_id = None  # ID текущей карты
        
    def check_boost_available(self) -> Optional[str]:
        """
        Проверяет доступность кнопки пожертвования
        
        Returns:
            URL буста если доступен, иначе None
        """
        try:
            resp = self.session.get(self.club_url, timeout=(4, 8))
            if resp.status_code != 200:
                return None
            
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Ищем кнопку по разным критериям
            boost_button = None
            
            # Вариант 1: по классу club_boost-btn
            boost_button = soup.select_one('.club_boost-btn, .club-boost-btn')
            
            # Вариант 2: по тексту "Пожертвовать карту"
            if not boost_button:
                boost_button = soup.find('button', string=lambda text: text and 'Пожертвовать карту' in text)
            
            if not boost_button:
                boost_button = soup.find('a', string=lambda text: text and 'Пожертвовать карту' in text)
            
            # Вариант 3: ищем любую кнопку/ссылку содержащую текст
            if not boost_button:
                for elem in soup.find_all(['a', 'button']):
                    text = elem.get_text(strip=True)
                    if 'Пожертвовать' in text or 'пожертвовать' in text:
                        boost_button = elem
                        break
            
            if boost_button:
                # Если это форма или кнопка без href - возвращаем текущую страницу
                href = boost_button.get('href')
                if href:
                    if not href.startswith('http'):
                        return f"{BASE_URL}{href}"
                    return href
                else:
                    # Кнопка найдена, но без href - значит это текущая страница
                    return self.club_url
            
            return None
            
        except Exception as e:
            print(f"⚠️  Ошибка проверки буста: {e}")
            return None
    
    def contribute_card(self, boost_url: str) -> bool:
        """
        Вносит карту в клуб
        
        Args:
            boost_url: URL страницы буста
        
        Returns:
            True если успешно, False если ошибка
        """
        try:
            # Получаем информацию о карте для буста
            boost_card = get_boost_card_info(self.session, boost_url)
            
            if not boost_card:
                print("❌ Не удалось получить информацию о карте для буста")
                return False
            
            instance_id = boost_card.get('id', 0)
            new_card_id = boost_card.get('card_id', 0)
            
            if not instance_id:
                print("❌ Не удалось получить instance_id карты")
                return False
            
            # Проверяем, изменилась ли карта
            if self.current_card_id and self.current_card_id != new_card_id:
                self.card_changed = True
                print(f"\n⚠️  КАРТА ИЗМЕНИЛАСЬ! Старая: {self.current_card_id} -> Новая: {new_card_id}")
            
            self.current_card_id = new_card_id
            
            # Сохраняем информацию о карте
            boost_output = os.path.join(self.output_dir, "boost_card.json")
            with open(boost_output, "w", encoding="utf-8") as f:
                json.dump(boost_card, f, ensure_ascii=False, indent=2)
            
            print("\n" + "="*60)
            print("🎁 ОБНАРУЖЕНА ВОЗМОЖНОСТЬ ВНЕСТИ КАРТУ!")
            print("="*60)
            print(f"   Название: {boost_card['name'] or '(не удалось получить)'}")
            print(f"   ID карты: {boost_card['card_id']} | Instance ID: {instance_id} | Ранг: {boost_card['rank'] or '(не удалось получить)'}")
            print(f"   Владельцев: {boost_card['owners_count']} | Желающих: {boost_card['wanters_count']}")
            print(f"💾 Карточка для буста перезаписана в: {boost_output}")
            print("="*60 + "\n")
            
            # Отправляем запрос на внесение карты
            contribute_url = f"{BASE_URL}/clubs/boost"
            
            # Получаем CSRF токен из сессии
            csrf_token = self.session.headers.get('X-CSRF-TOKEN', '')
            
            data = {
                "card_id": instance_id,
                "_token": csrf_token
            }
            
            resp = self.session.post(
                contribute_url,
                data=data,
                headers={
                    "Referer": boost_url,
                    "Origin": BASE_URL,
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
                timeout=(4, 8)
            )
            
            if resp.status_code == 200:
                print("✅ Карта успешно внесена в клуб!")
                
                # Отменяем все отправленные обмены
                print("🔄 Отменяем все отправленные обмены...")
                cancel_success = cancel_all_sent_trades(self.session, debug=False)
                
                if cancel_success:
                    print("✅ Все отправленные обмены успешно отменены!")
                else:
                    print("⚠️  Не удалось отменить обмены (возможно, их не было)")
                
                return True
            else:
                print(f"⚠️  Ошибка внесения карты: статус {resp.status_code}")
                print(f"   Ответ: {resp.text[:200]}")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка при внесении карты: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def monitor_loop(self):
        """Основной цикл мониторинга"""
        print(f"\n🔄 Запущен мониторинг страницы: {self.club_url}")
        print("   Проверка каждые 2 секунды...")
        print("   Нажмите Ctrl+C для остановки\n")
        
        check_count = 0
        
        while self.running:
            check_count += 1
            
            # Проверяем доступность буста
            boost_url = self.check_boost_available()
            
            if boost_url:
                print(f"\n🎯 [{time.strftime('%H:%M:%S')}] Проверка #{check_count}: БУСТ ДОСТУПЕН!")
                
                # Вносим карту
                success = self.contribute_card(boost_url)
                
                if success:
                    self.boost_available = True
                    print("   ✅ Продолжаем мониторинг для следующего буста...")
                else:
                    print("   ⚠️  Продолжаем мониторинг...")
            else:
                # Выводим статус каждые 30 проверок (60 секунд)
                if check_count == 1 or check_count % 30 == 0:
                    print(f"⏳ [{time.strftime('%H:%M:%S')}] Проверка #{check_count}: буст недоступен")
            
            # Задержка 2 секунды
            time.sleep(2)
    
    def start(self):
        """Запускает мониторинг в отдельном потоке"""
        if self.running:
            print("⚠️  Мониторинг уже запущен")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Останавливает мониторинг"""
        if not self.running:
            return
        
        print("\n🛑 Остановка мониторинга...")
        self.running = False
        
        if self.thread:
            self.thread.join(timeout=5)
        
        print("✅ Мониторинг остановлен")
    
    def is_running(self) -> bool:
        """Проверяет, запущен ли мониторинг"""
        return self.running


def start_boost_monitor(session: requests.Session, club_url: str, output_dir: str = "created_files") -> BoostMonitor:
    """
    Удобная функция для запуска мониторинга
    
    Args:
        session: Сессия requests
        club_url: URL страницы буста клуба
        output_dir: Директория для файлов
    
    Returns:
        Объект BoostMonitor
    """
    monitor = BoostMonitor(session, club_url, output_dir)
    monitor.start()
    return monitor