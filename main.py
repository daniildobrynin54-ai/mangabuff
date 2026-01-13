"""Главный модуль с режимом ожидания при достижении лимитов."""

import argparse
import sys
import time
import os
from typing import Optional

from config import (
    OUTPUT_DIR,
    BOOST_CARD_FILE,
    WAIT_AFTER_ALL_OWNERS,
    WAIT_CHECK_INTERVAL,
    WAIT_MODE_CHECK_INTERVAL,
    WAIT_MODE_STATS_INTERVAL,
    HISTORY_CHECK_INTERVAL,
    TELEGRAM_ENABLED,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_THREAD_ID
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
from telegram_notifier import create_telegram_notifier
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


class MangaBuffApp:
    """Главное приложение с режимом ожидания."""
    
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
        self.telegram_notifier = None
    
    def setup(self) -> bool:
        """Настройка приложения."""
        ensure_dir_exists(self.output_dir)
        
        # Инициализируем прокси
        self.proxy_manager = create_proxy_manager(
            proxy_url=self.args.proxy,
            proxy_file=self.args.proxy_file
        )
        
        # Инициализируем Telegram бота
        self.telegram_notifier = create_telegram_notifier(
            bot_token=self.args.telegram_token or TELEGRAM_BOT_TOKEN,
            chat_id=self.args.telegram_chat_id or TELEGRAM_CHAT_ID,
            thread_id=self.args.telegram_thread_id or TELEGRAM_THREAD_ID,
            enabled=self.args.telegram_enabled if hasattr(self.args, 'telegram_enabled') else TELEGRAM_ENABLED
        )
        
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
    
    def init_stats_manager(self) -> bool:
        """Инициализирует менеджер статистики."""
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
    
    def init_history_monitor(self) -> bool:
        """🔧 ИСПРАВЛЕНО: Инициализирует монитор истории с интервалом 1 минута."""
        print("📊 Инициализация монитора истории обменов...")
        
        self.history_monitor = TradeHistoryMonitor(
            session=self.session,
            user_id=int(self.args.user_id),
            inventory_manager=self.inventory_manager,
            debug=self.args.debug
        )
        
        # 🔧 ИЗМЕНЕНО: Интервал проверки 60 секунд вместо 10
        self.history_monitor.start(check_interval=HISTORY_CHECK_INTERVAL)
        
        print_success(f"Монитор истории запущен (проверка каждые {HISTORY_CHECK_INTERVAL}с)\n")
        return True
    
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
        if self.args.skip_inventory:
            return []
        
        print(f"📦 Загрузка инвентаря пользователя {self.args.user_id}...")
        inventory = get_user_inventory(self.session, self.args.user_id)
        
        print_success(f"Всего загружено: {len(inventory)} карточек")
        
        if self.inventory_manager.save_inventory(inventory):
            print(f"💾 Инвентарь сохранен\n")
        
        return inventory
    
    def load_boost_card(self) -> Optional[dict]:
        """Загружает информацию о буст-карте."""
        if not self.args.boost_url:
            return None
        
        boost_card = get_boost_card_info(self.session, self.args.boost_url)
        
        if not boost_card:
            print_error("Не удалось получить карту для буста")
            return None
        
        print_success("Карточка для вклада:")
        print(f"   {format_card_info(boost_card)}")
        
        # Отправляем уведомление о первой карте
        if self.telegram_notifier and self.telegram_notifier.is_enabled():
            print("\n📱 Отправка уведомления о текущей карте в Telegram...")
            club_members = boost_card.get('club_members', [])
            success = self.telegram_notifier.notify_card_change(
                card_info=boost_card,
                boost_url=self.args.boost_url,
                club_members=club_members
            )
            if success:
                print_success("Уведомление отправлено в Telegram")
            else:
                print_warning("Не удалось отправить уведомление")
        
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
    
    def start_monitoring(self, boost_card: dict):
        """Запускает мониторинг буста."""
        if not self.args.enable_monitor:
            return
        
        self.monitor = start_boost_monitor(
            self.session,
            self.args.boost_url,
            self.stats_manager,
            self.output_dir,
            self.telegram_notifier
        )
        
        self.monitor.current_card_id = boost_card['card_id']
    
    def wait_for_boost_or_timeout(
        self,
        card_id: int,
        timeout: int = WAIT_AFTER_ALL_OWNERS
    ) -> bool:
        """Ожидает буст или таймаут."""
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
    
    def enter_wait_mode(self) -> None:
        """
        🔧 НОВОЕ: Режим ожидания при достижении лимитов.
        
        В этом режиме:
        - Мониторинг карты для вклада продолжает работать
        - Telegram бот активен
        - Парсинг истории обменов раз в минуту
        - Проверка сброса лимитов каждые 30 секунд
        """
        print_section("⏸️  РЕЖИМ ОЖИДАНИЯ", char="=")
        print("   📊 Достигнуты дневные лимиты")
        print("   🔄 Мониторинг карты: АКТИВЕН")
        print("   📱 Telegram уведомления: АКТИВНЫ")
        print(f"   📜 История обменов: проверка каждые {HISTORY_CHECK_INTERVAL}с")
        print(f"   ⏰ Проверка сброса лимитов: каждые {WAIT_MODE_CHECK_INTERVAL}с")
        print("   Нажмите Ctrl+C для завершения\n")
        
        self.stats_manager.print_stats(force_refresh=True)
        
        check_count = 0
        last_stats_time = time.time()
        
        while True:
            check_count += 1
            
            # Проверяем сброс лимитов
            if not self.stats_manager.is_limits_reached(force_refresh=True):
                print_success("\n✅ Лимиты обновились! Возобновляем работу...")
                self.stats_manager.print_stats()
                return
            
            # Периодически выводим статистику
            current_time = time.time()
            if current_time - last_stats_time >= WAIT_MODE_STATS_INTERVAL:
                print_section("📊 РЕЖИМ ОЖИДАНИЯ - Статистика", char="-")
                self.stats_manager.print_stats()
                last_stats_time = current_time
            
            # Проверяем изменение карты
            if self.monitor and self.monitor.card_changed:
                print_info("ℹ️  Карта в клубе изменилась (режим ожидания)")
                # Сбрасываем флаг, но продолжаем ждать
                self.monitor.card_changed = False
            
            time.sleep(WAIT_MODE_CHECK_INTERVAL)
    
    def run_processing_mode(self, boost_card: dict):
        """Режим обработки владельцев с проверкой лимитов."""
        self.init_processor()
        
        while True:
            # 🔧 ПРОВЕРКА: Достигнуты ли лимиты?
            if self.stats_manager.is_limits_reached(force_refresh=True):
                print_warning("\n⛔ Достигнуты все дневные лимиты!")
                self.enter_wait_mode()
                # После выхода из режима ожидания продолжаем
                continue
            
            current_boost_card = self._load_current_boost_card(boost_card)
            current_card_id = current_boost_card['card_id']
            
            # Проверка на автозамену
            if current_boost_card.get('needs_replacement', False):
                # 🔧 ПРОВЕРКА: Можем ли делать замену?
                if not self.stats_manager.can_replace(force_refresh=True):
                    print_warning(f"\n⚠️  Карта требует замены, но лимит замен исчерпан!")
                    self.stats_manager.print_stats()
                    # Продолжаем работать с текущей картой
                else:
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
            
            # 🔧 ЕЩЕ РАЗ проверяем лимит перед обработкой
            if not self.stats_manager.can_donate(force_refresh=True):
                print_warning("⛔ Лимит вкладов достигнут!")
                self.enter_wait_mode()
                continue
            
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
            self.monitor.stop()
            if self.history_monitor:
                self.history_monitor.stop()
    
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
        
        if self.history_monitor:
            self.history_monitor.stop()
        
        return 0


def create_argument_parser() -> argparse.ArgumentParser:
    """Создает парсер аргументов."""
    parser = argparse.ArgumentParser(
        description="MangaBuff с режимом ожидания при достижении лимитов"
    )
    
    # Основные параметры
    parser.add_argument("--email", required=True, help="Email")
    parser.add_argument("--password", required=True, help="Пароль")
    parser.add_argument("--user_id", required=True, help="ID пользователя")
    parser.add_argument("--boost_url", help="URL буста")
    
    # Прокси
    parser.add_argument(
        "--proxy",
        help="URL прокси"
    )
    parser.add_argument(
        "--proxy_file",
        help="Файл с прокси"
    )
    
    # Telegram
    parser.add_argument(
        "--telegram_token",
        help="Telegram Bot Token"
    )
    parser.add_argument(
        "--telegram_chat_id",
        help="Telegram Chat ID"
    )
    parser.add_argument(
        "--telegram_thread_id",
        type=int,
        help="Telegram Thread ID"
    )
    parser.add_argument(
        "--telegram_enabled",
        action="store_true",
        default=None,
        help="Включить Telegram"
    )
    parser.add_argument(
        "--telegram_disabled",
        action="store_true",
        help="Отключить Telegram"
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
    
    return parser


def main():
    """Точка входа."""
    parser = create_argument_parser()
    args = parser.parse_args()
    
    if not args.proxy and not args.proxy_file:
        args.proxy = os.getenv('PROXY_URL')
    
    if args.telegram_disabled:
        args.telegram_enabled = False
    elif args.telegram_enabled is None:
        args.telegram_enabled = TELEGRAM_ENABLED
    
    app = MangaBuffApp(args)
    sys.exit(app.run())


if __name__ == "__main__":
    main()