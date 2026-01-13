"""Главный модуль с системой восстановления при сбоях."""

import argparse
import sys
import time
import os
import traceback
from typing import Optional

from config import (
    OUTPUT_DIR,
    BOOST_CARD_FILE,
    WAIT_AFTER_ALL_OWNERS,
    WAIT_CHECK_INTERVAL
)
from auth import login
from inventory import get_user_inventory, InventoryManager
from boost import get_boost_card_info
from card_selector import select_trade_card
from owners_parser import process_owners_page_by_page, OwnersProcessor
from monitor import start_boost_monitor
from trade import (
    send_trade_to_owner,
    cancel_all_sent_trades,
    TradeHistoryMonitor
)
from card_replacement import check_and_replace_if_needed
from daily_stats import create_stats_manager
from proxy_manager import create_proxy_manager
from rate_limiter import get_rate_limiter
from utils import (
    ensure_dir_exists,
    save_json,
    load_json,
    format_card_info,
    print_section,
    print_success,
    print_error,
    print_warning,
    print_info
)


# 🔧 НОВОЕ: Константы для системы восстановления
RECOVERY_RETRY_INTERVAL = 300  # 5 минут между попытками
MAX_RECOVERY_ATTEMPTS = 0  # 0 = бесконечно


class RecoveryManager:
    """Менеджер восстановления при критических ошибках."""
    
    def __init__(self, retry_interval: int = RECOVERY_RETRY_INTERVAL):
        self.retry_interval = retry_interval
        self.attempt_count = 0
    
    def should_retry(self, max_attempts: int = MAX_RECOVERY_ATTEMPTS) -> bool:
        """Проверяет, нужна ли еще одна попытка."""
        if max_attempts == 0:  # Бесконечные попытки
            return True
        return self.attempt_count < max_attempts
    
    def wait_before_retry(self):
        """Ожидает перед следующей попыткой."""
        self.attempt_count += 1
        
        print_section(
            f"🔄 ПОПЫТКА ВОССТАНОВЛЕНИЯ #{self.attempt_count}",
            char="="
        )
        print(f"⏳ Ожидание {self.retry_interval // 60} минут перед повтором...\n")
        
        # Разбиваем на части для возможности прерывания
        chunks = 30  # Проверяем каждые 10 секунд
        chunk_time = self.retry_interval / chunks
        
        for i in range(chunks):
            time.sleep(chunk_time)
            if (i + 1) % 6 == 0:  # Каждую минуту
                remaining = self.retry_interval - (i + 1) * chunk_time
                print(f"⏳ Осталось {int(remaining // 60)} мин...")
    
    def reset(self):
        """Сбрасывает счетчик попыток."""
        self.attempt_count = 0
    
    @staticmethod
    def is_recoverable_error(error: Exception) -> bool:
        """Определяет, можно ли восстановиться от ошибки."""
        error_str = str(error).lower()
        
        # Ошибки сети
        network_errors = [
            'connection', 'timeout', 'network', 
            'unreachable', 'refused', 'reset by peer',
            'temporary failure', 'name resolution'
        ]
        
        # Ошибки сервера 500+
        server_errors = ['500', '502', '503', '504']
        
        # Проверяем на сетевые ошибки
        if any(err in error_str for err in network_errors):
            return True
        
        # Проверяем на серверные ошибки
        if any(err in error_str for err in server_errors):
            return True
        
        # Проверяем статус код если есть
        if hasattr(error, 'response') and error.response:
            status = error.response.status_code
            if status >= 500:
                return True
        
        return False


class MangaBuffApp:
    """Главное приложение с системой восстановления."""
    
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.session = None
        self.monitor = None
        self.history_monitor = None
        self.output_dir = OUTPUT_DIR
        self.inventory_manager = InventoryManager(self.output_dir)
        self.stats_manager = None
        self.processor = None
        self.proxy_manager = None
        self.rate_limiter = get_rate_limiter()
        self.recovery_manager = RecoveryManager()  # 🔧 НОВОЕ
    
    def setup(self) -> bool:
        """Настройка приложения."""
        try:
            ensure_dir_exists(self.output_dir)
            
            # Инициализируем прокси
            self.proxy_manager = create_proxy_manager(
                proxy_url=self.args.proxy,
                proxy_file=self.args.proxy_file
            )
            
            # Выводим информацию о rate limiting
            print(f"⏱️  Rate Limiting: {self.rate_limiter.max_requests} req/min")
            
            print("\n🔐 Вход в аккаунт...")
            self.session = login(
                self.args.email,
                self.args.password,
                self.proxy_manager
            )
            
            if not self.session:
                print_error("Ошибка авторизации")
                return False
            
            print_success("Авторизация успешна\n")
            return True
            
        except Exception as e:
            print_error(f"Ошибка инициализации: {e}")
            if self.recovery_manager.is_recoverable_error(e):
                print_warning("Это восстанавливаемая ошибка")
            return False
    
    def init_stats_manager(self) -> bool:
        """Инициализирует менеджер статистики."""
        try:
            if not self.args.boost_url:
                print_warning("URL буста не указан")
                return False
            
            print("📊 Инициализация менеджера статистики...")
            self.stats_manager = create_stats_manager(
                self.session,
                self.args.boost_url
            )
            self.stats_manager.print_stats(force_refresh=True)
            return True
            
        except Exception as e:
            print_error(f"Ошибка инициализации статистики: {e}")
            return False
    
    def init_history_monitor(self) -> bool:
        """Инициализирует монитор истории обменов."""
        try:
            print("📊 Инициализация монитора истории обменов...")
            
            self.history_monitor = TradeHistoryMonitor(
                session=self.session,
                user_id=int(self.args.user_id),
                inventory_manager=self.inventory_manager,
                debug=self.args.debug
            )
            
            self.history_monitor.start(check_interval=10)
            
            print_success("Монитор истории запущен\n")
            return True
            
        except Exception as e:
            print_error(f"Ошибка инициализации монитора: {e}")
            return False
    
    def init_processor(self) -> None:
        """Инициализирует процессор владельцев."""
        if not self.processor:
            self.processor = OwnersProcessor(
                session=self.session,
                select_card_func=select_trade_card,
                send_trade_func=send_trade_to_owner,
                dry_run=self.args.dry_run,
                debug=self.args.debug
            )
    
    def load_inventory(self) -> Optional[list]:
        """Загружает инвентарь пользователя."""
        try:
            if self.args.skip_inventory:
                return []
            
            print(f"📦 Загрузка инвентаря пользователя {self.args.user_id}...")
            inventory = get_user_inventory(self.session, self.args.user_id)
            
            print_success(f"Всего загружено: {len(inventory)} карточек")
            
            if self.inventory_manager.save_inventory(inventory):
                print(f"💾 Инвентарь сохранен\n")
            
            return inventory
            
        except Exception as e:
            print_error(f"Ошибка загрузки инвентаря: {e}")
            if self.recovery_manager.is_recoverable_error(e):
                raise  # Пробрасываем для восстановления
            return []
    
    def load_boost_card(self) -> Optional[dict]:
        """Загружает информацию о буст-карте."""
        try:
            if not self.args.boost_url:
                return None
            
            boost_card = get_boost_card_info(self.session, self.args.boost_url)
            
            if not boost_card:
                print_error("Не удалось получить карту для буста")
                return None
            
            print_success("Карточка для вклада:")
            print(f"   {format_card_info(boost_card)}")
            
            # 🆕 НОВОЕ: Выводим информацию об участниках клуба
            from boost import format_club_members_info
            club_members = boost_card.get('club_members', [])
            members_info = format_club_members_info(club_members)
            print(f"   {members_info}")
            
            if boost_card.get('needs_replacement', False):
                print_warning(f"\n⚠️  Карта требует замены!")
                
                new_card = check_and_replace_if_needed(
                    self.session,
                    self.args.boost_url,
                    boost_card,
                    self.stats_manager
                )
                
                if new_card:
                    boost_card = new_card
            
            save_json(f"{self.output_dir}/{BOOST_CARD_FILE}", boost_card)
            print(f"💾 Карточка сохранена\n")
            
            return boost_card
            
        except Exception as e:
            print_error(f"Ошибка загрузки буст-карты: {e}")
            if self.recovery_manager.is_recoverable_error(e):
                raise
            return None
    
    def start_monitoring(self, boost_card: dict):
        """Запускает мониторинг буста."""
        try:
            if not self.args.enable_monitor:
                return
            
            self.monitor = start_boost_monitor(
                self.session,
                self.args.boost_url,
                self.stats_manager,
                self.output_dir
            )
            
            self.monitor.current_card_id = boost_card['card_id']
            
        except Exception as e:
            print_error(f"Ошибка запуска мониторинга: {e}")
    
    def wait_for_boost_or_timeout(
        self,
        card_id: int,
        timeout: int = WAIT_AFTER_ALL_OWNERS
    ) -> bool:
        """Ожидает буст или таймаут."""
        try:
            if not self.monitor:
                return False
            
            print_section(
                f"⏳ ВСЕ ВЛАДЕЛЬЦЫ ОБРАБОТАНЫ - Ожидание {timeout // 60} мин",
                char="="
            )
            print(f"   Текущая карта: ID {card_id}")
            print(f"   Мониторинг продолжает работать...\n")
            
            start_time = time.time()
            check_count = 0
            
            while time.time() - start_time < timeout:
                check_count += 1
                
                if self.monitor.card_changed:
                    elapsed = int(time.time() - start_time)
                    print(f"\n✅ БУСТ ПРОИЗОШЕЛ через {elapsed}с!")
                    return True
                
                if check_count % 15 == 0:
                    elapsed = int(time.time() - start_time)
                    remaining = timeout - elapsed
                    print(f"⏳ Ожидание: {elapsed}с / {remaining}с осталось")
                
                time.sleep(WAIT_CHECK_INTERVAL)
            
            print(f"\n⏱️  ТАЙМАУТ: {timeout // 60} минут")
            return False
            
        except Exception as e:
            print_error(f"Ошибка в ожидании: {e}")
            return False
    
    def run_processing_mode(self, boost_card: dict):
        """Режим обработки владельцев."""
        self.init_processor()
        
        while True:
            try:
                current_boost_card = self._load_current_boost_card(boost_card)
                current_card_id = current_boost_card['card_id']
                
                if current_boost_card.get('needs_replacement', False):
                    print_warning(f"\n⚠️  Карта требует автозамены!")
                    
                    new_card = check_and_replace_if_needed(
                        self.session,
                        self.args.boost_url,
                        current_boost_card,
                        self.stats_manager
                    )
                    
                    if new_card:
                        current_boost_card = new_card
                        current_card_id = new_card['card_id']
                        
                        if self.monitor:
                            self.monitor.current_card_id = current_card_id
                        
                        self.processor.reset_state()
                
                if self.monitor:
                    self.monitor.card_changed = False
                
                print(f"\n🎯 Обработка: {current_boost_card['name']} (ID: {current_card_id})")
                
                # Выводим текущий rate
                current_rate = self.rate_limiter.get_current_rate()
                print(f"📊 Текущий rate: {current_rate}/{self.rate_limiter.max_requests} req/min\n")
                
                # Обрабатываем владельцев
                total = process_owners_page_by_page(
                    session=self.session,
                    card_id=str(current_card_id),
                    boost_card=current_boost_card,
                    output_dir=self.output_dir,
                    select_card_func=select_trade_card,
                    send_trade_func=send_trade_to_owner,
                    monitor_obj=self.monitor,
                    processor=self.processor,
                    dry_run=self.args.dry_run,
                    debug=self.args.debug
                )
                
                if total > 0:
                    print_success(f"Обработано {total} владельцев")
                else:
                    print_warning("Нет доступных владельцев")
                
                if self._should_restart():
                    self.processor.reset_state()
                    self._prepare_restart()
                    time.sleep(1)
                    continue
                
                if self.monitor and self.monitor.is_running() and total > 0:
                    boost_happened = self.wait_for_boost_or_timeout(current_card_id)
                    
                    if boost_happened:
                        self.processor.reset_state()
                        self._prepare_restart()
                        time.sleep(1)
                        continue
                    else:
                        print("🔄 Отменяем обмены...")
                        if not self.args.dry_run:
                            success = cancel_all_sent_trades(
                                self.session,
                                self.processor.trade_manager,
                                self.history_monitor,
                                self.args.debug
                            )
                            if success:
                                print_success("Обмены отменены, история проверена!")
                            else:
                                print_warning("Не удалось отменить")
                        
                        print_section("🔄 ПЕРЕЗАПУСК с той же картой", char="=")
                        time.sleep(1)
                        continue
                
                break
                
            except Exception as e:
                print_error(f"Ошибка обработки: {e}")
                
                # Проверяем, можно ли восстановиться
                if self.recovery_manager.is_recoverable_error(e):
                    print_warning("Обнаружена восстанавливаемая ошибка!")
                    traceback.print_exc()
                    raise  # Пробрасываем для восстановления на верхнем уровне
                else:
                    print_error("Невосстанавливаемая ошибка!")
                    traceback.print_exc()
                    break
    
    def _load_current_boost_card(self, default: dict) -> dict:
        """Загружает текущую карту из файла."""
        path = f"{self.output_dir}/{BOOST_CARD_FILE}"
        current = load_json(path, default=default)
        return current if current else default
    
    def _should_restart(self) -> bool:
        """Проверяет нужен ли перезапуск."""
        return (
            self.monitor and
            self.monitor.is_running() and
            self.monitor.card_changed
        )
    
    def _prepare_restart(self):
        """Подготавливает перезапуск."""
        print_section("🔄 ПЕРЕЗАПУСК с новой картой", char="=")
    
    def wait_for_monitor(self):
        """Ожидает завершения мониторинга."""
        if not self.monitor or not self.monitor.is_running():
            return
        
        try:
            print_section("Мониторинг активен. Ctrl+C для выхода", char="=")
            
            while self.monitor.is_running():
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n\n⚠️  Прерывание...")
            self.cleanup()
    
    def cleanup(self):
        """Очищает ресурсы."""
        try:
            if self.monitor:
                self.monitor.stop()
            if self.history_monitor:
                self.history_monitor.stop()
        except Exception as e:
            print_error(f"Ошибка очистки: {e}")
    
    def run(self) -> int:
        """Главный метод запуска."""
        if not self.setup():
            return 1
        
        if self.args.boost_url:
            if not self.init_stats_manager():
                print_warning("Работа без статистики")
        
        if not self.args.skip_inventory:
            self.init_history_monitor()
        
        inventory = self.load_inventory()
        boost_card = self.load_boost_card()
        
        if not boost_card:
            return 0
        
        self.start_monitoring(boost_card)
        
        if not self.args.only_list_owners:
            self.run_processing_mode(boost_card)
        
        self.wait_for_monitor()
        self.cleanup()
        
        return 0
    
    def run_with_recovery(self) -> int:
        """🔧 НОВОЕ: Запуск с системой восстановления."""
        while self.recovery_manager.should_retry():
            try:
                result = self.run()
                
                # Если успешно - сбрасываем счетчик и выходим
                self.recovery_manager.reset()
                return result
                
            except KeyboardInterrupt:
                print("\n\n⚠️  Прерывание пользователем")
                self.cleanup()
                return 130
                
            except Exception as e:
                print_error(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
                traceback.print_exc()
                
                # Проверяем, восстанавливаемая ли ошибка
                if not self.recovery_manager.is_recoverable_error(e):
                    print_error("Невосстанавливаемая ошибка. Завершение.")
                    self.cleanup()
                    return 1
                
                print_warning("Попытка восстановления...")
                
                # Очищаем ресурсы перед повтором
                self.cleanup()
                
                # Ждем перед повтором
                self.recovery_manager.wait_before_retry()
        
        print_error("Достигнут лимит попыток восстановления")
        return 1


def create_argument_parser() -> argparse.ArgumentParser:
    """Создает парсер аргументов."""
    parser = argparse.ArgumentParser(
        description="MangaBuff с прокси, rate limiting и системой восстановления"
    )
    
    # Основные параметры
    parser.add_argument("--email", required=True, help="Email")
    parser.add_argument("--password", required=True, help="Пароль")
    parser.add_argument("--user_id", required=True, help="ID пользователя")
    parser.add_argument("--boost_url", help="URL буста")
    
    # Прокси
    parser.add_argument(
        "--proxy",
        help="URL прокси (http://host:port или socks5://user:pass@host:port)"
    )
    parser.add_argument(
        "--proxy_file",
        help="Файл с прокси (первая строка)"
    )
    
    # Режимы работы
    parser.add_argument(
        "--skip_inventory",
        action="store_true",
        help="Пропустить инвентарь"
    )
    parser.add_argument(
        "--only_list_owners",
        action="store_true",
        help="Только список владельцев"
    )
    parser.add_argument(
        "--enable_monitor",
        action="store_true",
        help="Включить мониторинг"
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Тестовый режим"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Отладка"
    )
    
    # 🔧 НОВОЕ: Параметры восстановления
    parser.add_argument(
        "--no_recovery",
        action="store_true",
        help="Отключить систему восстановления"
    )
    
    return parser


def main():
    """Точка входа."""
    parser = create_argument_parser()
    args = parser.parse_args()
    
    # Можно задать прокси через переменную окружения
    if not args.proxy and not args.proxy_file:
        args.proxy = os.getenv('PROXY_URL')
    
    app = MangaBuffApp(args)
    
    # 🔧 НОВОЕ: Используем систему восстановления если не отключена
    if args.no_recovery:
        sys.exit(app.run())
    else:
        print_section("🛡️  СИСТЕМА ВОССТАНОВЛЕНИЯ АКТИВНА", char="=")
        print("   Автоматическое восстановление при сбоях")
        print("   Интервал между попытками: 5 минут\n")
        sys.exit(app.run_with_recovery())


if __name__ == "__main__":
    main()