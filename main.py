import argparse
import json
import os
import time
from auth import login
from inventory import get_user_inventory
from boost import get_boost_card_info
from card_selector import select_trade_card
from owners_parser import process_owners_page_by_page, find_all_available_owners
from monitor import start_boost_monitor
from trade import send_trade_to_owner


def main():
    parser = argparse.ArgumentParser(
        description="MangaBuff - автоматизация обменов карт"
    )
    parser.add_argument("--email", required=True, help="Email для входа")
    parser.add_argument("--password", required=True, help="Пароль")
    parser.add_argument("--user_id", required=True, help="ID пользователя")
    parser.add_argument("--boost_url", help="URL страницы буста клуба")
    parser.add_argument("--skip_inventory", action="store_true", help="Пропустить загрузку инвентаря")
    parser.add_argument("--only_list_owners", action="store_true", help="Только вывести список владельцев без обработки")
    parser.add_argument("--enable_monitor", action="store_true", help="Включить мониторинг страницы буста")
    parser.add_argument("--dry_run", action="store_true", help="Тестовый режим - не отправлять реальные обмены")
    parser.add_argument("--debug", action="store_true", help="Режим отладки")
    
    args = parser.parse_args()
    
    # Создаем папку для файлов
    output_dir = "created_files"
    os.makedirs(output_dir, exist_ok=True)
    
    inventory_output = os.path.join(output_dir, "inventory.json")
    boost_output = os.path.join(output_dir, "boost_card.json")
    
    # Вход в аккаунт
    print("🔑 Вход в аккаунт...")
    session = login(args.email, args.password)
    if not session:
        print("❌ Ошибка авторизации")
        return
    
    print("✅ Авторизация успешна")
    
    # Получение инвентаря (опционально)
    if not args.skip_inventory:
        print(f"📦 Загрузка инвентаря пользователя {args.user_id}...")
        inventory = get_user_inventory(session, args.user_id)
        
        print(f"✅ Всего загружено: {len(inventory)} карточек")
        
        # Сохраняем инвентарь
        with open(inventory_output, "w", encoding="utf-8") as f:
            json.dump(inventory, f, ensure_ascii=False, indent=2)
        print(f"💾 Инвентарь сохранен в: {inventory_output}")
    
    # Получение карточки для буста (если указан URL)
    monitor = None
    
    if args.boost_url:
        boost_card = get_boost_card_info(session, args.boost_url)
        if not boost_card:
            print("\n❌ Не удалось получить информацию о карте для буста")
            return
        
        print("✅ Карточка для вклада:")
        print(f"   Название: {boost_card['name'] or '(не удалось получить)'}")
        print(f"   ID карты: {boost_card['card_id']} | Instance ID: {boost_card['id']} | Ранг: {boost_card['rank'] or '(не удалось получить)'}")
        print(f"   Владельцев: {boost_card['owners_count']} | Желающих: {boost_card['wanters_count']}")
        
        with open(boost_output, "w", encoding="utf-8") as f:
            json.dump(boost_card, f, ensure_ascii=False, indent=2)
        print(f"💾 Карточка для буста сохранена в: {boost_output}")
        print()
        
        # Запускаем мониторинг если включен
        if args.enable_monitor:
            monitor = start_boost_monitor(session, args.boost_url, output_dir)
            monitor.current_card_id = boost_card['card_id']
        
        # Режим работы
        if args.only_list_owners:
            # Простой вывод всех владельцев
            available_owners = find_all_available_owners(session, str(boost_card['card_id']))
            
            if available_owners:
                print(f"\n✅ Найдено {len(available_owners)} доступных владельцев")
            else:
                print("\n⚠️  Не найдено доступных владельцев онлайн без замка")
        else:
            # Постраничная обработка с подбором карт и отправкой обменов
            while True:
                # Загружаем актуальную карту из файла
                try:
                    with open(boost_output, "r", encoding="utf-8") as f:
                        current_boost_card = json.load(f)
                except:
                    current_boost_card = boost_card
                
                print(f"\n🎯 Обработка карты: {current_boost_card['name']} (ID: {current_boost_card['card_id']})")
                
                total = process_owners_page_by_page(
                    session=session,
                    card_id=str(current_boost_card['card_id']),
                    boost_card=current_boost_card,
                    output_dir=output_dir,
                    select_card_func=select_trade_card,
                    send_trade_func=send_trade_to_owner,
                    monitor_obj=monitor,
                    dry_run=args.dry_run,
                    debug=args.debug
                )
                
                if total > 0:
                    print(f"\n✅ Успешно обработано {total} владельцев")
                else:
                    print("\n⚠️  Не найдено доступных владельцев для обработки")
                
                # Если карта не изменилась или монитор не включен - выходим
                if not monitor or not monitor.card_changed:
                    break
                
                # Сбрасываем флаг и перезапускаем с новой картой
                monitor.card_changed = False
                print("\n" + "="*60)
                print("🔄 ПЕРЕЗАПУСК: Начинаем обработку новой карты с первой страницы")
                print("="*60)
                time.sleep(1)
    
    # Если мониторинг запущен, ждем его завершения
    if monitor and monitor.is_running():
        try:
            print("\n" + "="*60)
            print("Мониторинг активен. Нажмите Ctrl+C для выхода")
            print("="*60)
            while monitor.is_running():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n⚠️  Получен сигнал прерывания")
            monitor.stop()


if __name__ == "__main__":
    main()