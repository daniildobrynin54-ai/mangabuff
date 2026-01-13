"""Главный модуль приложения MangaBuff."""

import argparse
import os
import sys
import time
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
from owners_parser import process_owners_page_by_page, find_all_available_owners, OwnersProcessor
from monitor import start_boost_monitor
from trade import send_trade_to_owner, cancel_all_sent_trades
from card_replacement import check_and_replace_if_needed
from daily_stats import create_stats_manager, DailyStatsManager
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
    """Главное приложение MangaBuff."""
    
    def __init__(self, args: argparse.Namespace):
        """
        Инициализация приложения.
        
        Args:
            args: Аргументы командной строки
        """
        self.args = args
        self.session = None
        self.monitor = None
        self.output_dir = OUTPUT_DIR
        self.inventory_manager = InventoryManager(self.output_dir)
        self.stats_manager = None  # Инициализируется после получения boost_url
        self.processor = None  # Процессор владельцев (для сохранения состояния)
    
    def setup(self) -> bool:
        """
        Настройка приложения.
        
        Returns:
            True если настройка успешна
        """
        # Создаем выходную директорию
        ensure_dir_exists(self.output_dir)
        
        # Авторизация
        print("🔐 Вход в аккаунт...")
        self.session = login(self.args.email, self.args.password)
        
        if not self.session:
            print_error("Ошибка авторизации")
            return False
        
        print_success("Авторизация успешна\n")
        
        return True
    
    def init_stats_manager(self) -> bool:
        """
        Инициализирует менеджер статистики после получения URL буста.
        
        Returns:
            True если инициализация успешна
        """
        if not self.args.boost_url:
            print_warning("URL буста не указан, статистика недоступна")
            return False
        
        print("📊 Инициализация менеджера статистики...")
        self.stats_manager = create_stats_manager(
            self.session,
            self.args.boost_url
        )
        
        # Загружаем и выводим статистику с сервера
        self.stats_manager.print_stats(force_refresh=True)
        
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
        """
        Загружает инвентарь пользователя.
        
        Returns:
            Список карт или None при ошибке
        """
        if self.args.skip_inventory:
            return []
        
        print(f"📦 Загрузка инвентаря пользователя {self.args.user_id}...")
        inventory = get_user_inventory(self.session, self.args.user_id)
        
        print_success(f"Всего загружено: {len(inventory)} карточек")
        
        # Сохраняем инвентарь
        if self.inventory_manager.save_inventory(inventory):
            inventory_path = self.inventory_manager.inventory_path
            print(f"💾 Инвентарь сохранен в: {inventory_path}\n")
        
        return inventory
    
    def load_boost_card(self) -> Optional[dict]:
        """
        Загружает информацию о буст-карте.
        
        Returns:
            Информация о карте или None
        """
        if not self.args.boost_url:
            return None
        
        boost_card = get_boost_card_info(self.session, self.args.boost_url)
        
        if not boost_card:
            print_error("Не удалось получить информацию о карте для буста")
            return None
        
        print_success("Карточка для вклада:")
        print(f"   {format_card_info(boost_card)}")
        
        # Проверяем, нужна ли автозамена
        if boost_card.get('needs_replacement', False):
            print_warning(f"\n⚠️  Карта требует замены!")
            print(f"   Владельцев: {boost_card.get('owners_count', '?')}")
            
            # Пытаемся заменить карту
            new_card = check_and_replace_if_needed(
                self.session,
                self.args.boost_url,
                boost_card,
                self.stats_manager
            )
            
            # Если замена успешна - используем новую карту
            if new_card:
                boost_card = new_card
        
        # Сохраняем
        boost_path = os.path.join(self.output_dir, BOOST_CARD_FILE)
        save_json(boost_path, boost_card)
        print(f"💾 Карточка для буста сохранена в: {boost_path}\n")
        
        return boost_card
    
    def start_monitoring(self, boost_card: dict):
        """
        Запускает мониторинг буста.
        
        Args:
            boost_card: Информация о буст-карте
        """
        if not self.args.enable_monitor:
            return
        
        self.monitor = start_boost_monitor(
            self.session,
            self.args.boost_url,
            self.stats_manager,
            self.output_dir
        )
        
        self.monitor.current_card_id = boost_card['card_id']
    
    def run_list_owners_mode(self, boost_card: dict):
        """
        Режим вывода списка владельцев.
        
        Args:
            boost_card: Информация о буст-карте
        """
        available_owners = find_all_available_owners(
            self.session,
            str(boost_card['card_id'])
        )
        
        if available_owners:
            print_success(f"Найдено {len(available_owners)} доступных владельцев")
        else:
            print_warning("Не найдено доступных владельцев онлайн без замка")
    
    def wait_for_boost_or_timeout(self, card_id: int, timeout: int = WAIT_AFTER_ALL_OWNERS) -> bool:
        """
        Ожидает буст или таймаут.
        
        Args:
            card_id: ID текущей карты
            timeout: Время ожидания в секундах
        
        Returns:
            True если произошел буст (карта изменилась), False если таймаут
        """
        if not self.monitor:
            return False
        
        print_section(
            f"⏳ ВСЕ ВЛАДЕЛЬЦЫ ОБРАБОТАНЫ - Ожидание буста {timeout // 60} минут",
            char="="
        )
        print(f"   Текущая карта: ID {card_id}")
        print(f"   Мониторинг продолжает работать...")
        print(f"   Если буст произойдет - автоматический переход на новую карту")
        print(f"   Если буст НЕ произойдет - перезапуск обработки с той же картой\n")
        
        start_time = time.time()
        check_count = 0
        
        while time.time() - start_time < timeout:
            check_count += 1
            
            # Проверяем изменение карты
            if self.monitor.card_changed:
                elapsed = int(time.time() - start_time)
                print(f"\n✅ БУСТ ПРОИЗОШЕЛ через {elapsed} секунд!")
                print("   Переход на новую карту...\n")
                return True
            
            # Выводим статус каждые 30 секунд
            if check_count % 15 == 0:
                elapsed = int(time.time() - start_time)
                remaining = timeout - elapsed
                print(f"⏳ Ожидание: прошло {elapsed}с, осталось {remaining}с")
            
            time.sleep(WAIT_CHECK_INTERVAL)
        
        print(f"\n⏱️  ТАЙМАУТ: прошло {timeout // 60} минут без буста")
        print("   Отменяем обмены и перезапускаем обработку с той же картой...\n")
        return False
    
    def run_processing_mode(self, boost_card: dict):
        """
        Режим обработки владельцев с отправкой обменов.
        
        Args:
            boost_card: Информация о буст-карте
        """
        # Инициализируем процессор один раз
        self.init_processor()
        
        while True:
            # Загружаем актуальную карту из файла
            current_boost_card = self._load_current_boost_card(boost_card)
            current_card_id = current_boost_card['card_id']
            
            # Проверяем автозамену перед началом обработки
            if current_boost_card.get('needs_replacement', False):
                print_warning(f"\n⚠️  Карта требует автозамены перед обработкой!")
                
                new_card = check_and_replace_if_needed(
                    self.session,
                    self.args.boost_url,
                    current_boost_card,
                    self.stats_manager
                )
                
                if new_card:
                    # Используем новую карту
                    current_boost_card = new_card
                    current_card_id = new_card['card_id']
                    
                    # Обновляем в мониторе
                    if self.monitor:
                        self.monitor.current_card_id = current_card_id
                    
                    # ВАЖНО: Сбрасываем состояние процессора при смене карты
                    self.processor.reset_state()
                else:
                    print_info("Продолжаем с текущей картой")
            
            # Сбрасываем флаг изменения карты ПЕРЕД началом обработки
            if self.monitor:
                self.monitor.card_changed = False
            
            print(f"\n🎯 Обработка карты: {current_boost_card['name']} "
                  f"(ID: {current_card_id})")
            
            # Обрабатываем владельцев (передаем processor для сохранения состояния)
            total = process_owners_page_by_page(
                session=self.session,
                card_id=str(current_card_id),
                boost_card=current_boost_card,
                output_dir=self.output_dir,
                select_card_func=select_trade_card,
                send_trade_func=send_trade_to_owner,
                monitor_obj=self.monitor,
                processor=self.processor,  # ВАЖНО: передаем существующий процессор
                dry_run=self.args.dry_run,
                debug=self.args.debug
            )
            
            if total > 0:
                print_success(f"Успешно обработано {total} владельцев")
            else:
                print_warning("Не найдено доступных владельцев для обработки")
            
            # Проверяем что произошло
            if self._should_restart():
                # Карта изменилась - сбрасываем состояние и перезапускаем с новой картой
                self.processor.reset_state()
                self._prepare_restart()
                time.sleep(1)
                continue
            
            # Если мониторинг включен и владельцы закончились
            if self.monitor and self.monitor.is_running() and total > 0:
                # Ждем 5 минут или пока не произойдет буст
                boost_happened = self.wait_for_boost_or_timeout(current_card_id)
                
                if boost_happened:
                    # Буст произошел - сбрасываем состояние и перезапускаем с новой картой
                    self.processor.reset_state()
                    self._prepare_restart()
                    time.sleep(1)
                    continue
                else:
                    # Таймаут без буста - отменяем обмены, сбрасываем состояние и перезапускаем
                    print("🔄 Отменяем все отправленные обмены...")
                    if not self.args.dry_run:
                        # Используем trade_manager из процессора
                        success = cancel_all_sent_trades(
                            self.session, 
                            self.processor.trade_manager,
                            self.args.debug
                        )
                        if success:
                            print_success("Все обмены отменены!")
                        else:
                            print_warning("Не удалось отменить обмены")
                    else:
                        print("[DRY-RUN] Отмена обменов пропущена")
                    
                    # ВАЖНО: Состояние уже сброшено в cancel_all_sent_trades
                    print_section(
                        "🔄 ПЕРЕЗАПУСК: Начинаем обработку ТОЙ ЖЕ карты заново",
                        char="="
                    )
                    time.sleep(1)
                    continue
            
            # Если мониторинг выключен или владельцев не было - выходим
            break
    
    def _load_current_boost_card(self, default_card: dict) -> dict:
        """Загружает актуальную информацию о буст-карте из файла."""
        boost_path = os.path.join(self.output_dir, BOOST_CARD_FILE)
        current_card = load_json(boost_path, default=default_card)
        return current_card if current_card else default_card
    
    def _should_restart(self) -> bool:
        """Проверяет, нужен ли перезапуск обработки."""
        # Перезапуск если монитор активен И карта изменилась
        return (
            self.monitor and
            self.monitor.is_running() and
            self.monitor.card_changed
        )
    
    def _prepare_restart(self):
        """Подготавливает перезапуск обработки."""
        print_section(
            "🔄 ПЕРЕЗАПУСК: Начинаем обработку новой карты с первой страницы",
            char="="
        )
    
    def wait_for_monitor(self):
        """Ожидает завершения мониторинга."""
        if not self.monitor or not self.monitor.is_running():
            return
        
        try:
            print_section(
                "Мониторинг активен. Нажмите Ctrl+C для выхода",
                char="="
            )
            
            while self.monitor.is_running():
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n\n⚠️  Получен сигнал прерывания")
            self.monitor.stop()
    
    def run(self) -> int:
        """
        Главный метод запуска приложения.
        
        Returns:
            Код завершения (0 - успех, 1 - ошибка)
        """
        # Настройка
        if not self.setup():
            return 1
        
        # Инициализация менеджера статистики (если есть boost_url)
        if self.args.boost_url:
            if not self.init_stats_manager():
                print_warning("Работа без менеджера статистики")
        
        # Загрузка инвентаря
        inventory = self.load_inventory()
        
        # Загрузка буст-карты
        boost_card = self.load_boost_card()
        
        if not boost_card:
            return 0  # Нет буст-карты, но это не ошибка
        
        # Запуск мониторинга
        self.start_monitoring(boost_card)
        
        # Выбор режима работы
        if self.args.only_list_owners:
            self.run_list_owners_mode(boost_card)
        else:
            self.run_processing_mode(boost_card)
        
        # Ожидание мониторинга
        self.wait_for_monitor()
        
        return 0


def create_argument_parser() -> argparse.ArgumentParser:
    """
    Создает парсер аргументов командной строки.
    
    Returns:
        Настроенный ArgumentParser
    """
    parser = argparse.ArgumentParser(
        description="MangaBuff - автоматизация обменов карт",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:

  # Загрузить инвентарь и обработать владельцев
  python main.py --email user@example.com --password pass123 \\
                 --user_id 12345 --boost_url https://mangabuff.ru/clubs/klub-taro-2/boost

  # Только вывести список владельцев
  python main.py --email user@example.com --password pass123 \\
                 --user_id 12345 --boost_url https://mangabuff.ru/clubs/klub-taro-2/boost \\
                 --only_list_owners

  # Тестовый режим (без реальных обменов)
  python main.py --email user@example.com --password pass123 \\
                 --user_id 12345 --boost_url https://mangabuff.ru/clubs/klub-taro-2/boost \\
                 --dry_run

  # С мониторингом буста и автозаменой карт
  python main.py --email user@example.com --password pass123 \\
                 --user_id 12345 --boost_url https://mangabuff.ru/clubs/klub-taro-2/boost \\
                 --enable_monitor
        """
    )
    
    # Обязательные аргументы
    parser.add_argument(
        "--email",
        required=True,
        help="Email для входа"
    )
    
    parser.add_argument(
        "--password",
        required=True,
        help="Пароль"
    )
    
    parser.add_argument(
        "--user_id",
        required=True,
        help="ID пользователя"
    )
    
    # Опциональные аргументы
    parser.add_argument(
        "--boost_url",
        help="URL страницы буста клуба"
    )
    
    parser.add_argument(
        "--skip_inventory",
        action="store_true",
        help="Пропустить загрузку инвентаря"
    )
    
    parser.add_argument(
        "--only_list_owners",
        action="store_true",
        help="Только вывести список владельцев без обработки"
    )
    
    parser.add_argument(
        "--enable_monitor",
        action="store_true",
        help="Включить мониторинг страницы буста"
    )
    
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Тестовый режим - не отправлять реальные обмены"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Режим отладки"
    )
    
    return parser


def main():
    """Точка входа приложения."""
    parser = create_argument_parser()
    args = parser.parse_args()
    
    app = MangaBuffApp(args)
    sys.exit(app.run())


if __name__ == "__main__":
    main()