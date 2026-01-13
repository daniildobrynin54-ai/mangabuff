"""Конфигурация приложения MangaBuff."""

# API настройки
BASE_URL = "https://mangabuff.ru"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0"

# Настройки пагинации
OWNERS_PER_PAGE = 36
WANTS_PER_PAGE = 60

# Пороги для приближенного подсчета
OWNERS_APPROXIMATE_THRESHOLD = 11
WANTS_APPROXIMATE_THRESHOLD = 5

# Оценки для последней страницы
OWNERS_LAST_PAGE_ESTIMATE = 18
WANTS_LAST_PAGE_ESTIMATE = 30

# Таймауты запросов (подключение, чтение) в секундах
REQUEST_TIMEOUT = (4, 8)

# Задержки между запросами
DEFAULT_DELAY = 0.25
PAGE_DELAY = 0.5
PARSE_DELAY = 0.8
CARD_API_DELAY = 0.15

# Настройки обменов
MIN_TRADE_DELAY = 11.0  # Минимальная задержка между обменами в секундах
TRADE_RANDOM_DELAY_MIN = 0.5
TRADE_RANDOM_DELAY_MAX = 2.0

# Настройки мониторинга
MONITOR_CHECK_INTERVAL = 2  # Проверка каждые 2 секунды
MONITOR_STATUS_INTERVAL = 30  # Вывод статуса каждые N проверок

# Настройки ожидания после обработки всех владельцев
WAIT_AFTER_ALL_OWNERS = 300  # 5 минут (300 секунд)
WAIT_CHECK_INTERVAL = 2  # Проверка каждые 2 секунды во время ожидания

# Настройки кэша
CACHE_VALIDITY_HOURS = 24

# Настройки селектора карт
MAX_CARD_SELECTION_ATTEMPTS = 50

# Пропуск первых владельцев на первой странице
FIRST_PAGE_SKIP_OWNERS = 6

# Дневные лимиты (значения по умолчанию, реальные парсятся с сайта)
MAX_DAILY_DONATIONS = 50  # Максимум пожертвований в день
MAX_DAILY_REPLACEMENTS = 10  # Максимум замен карты в день
MAX_CLUB_CARD_OWNERS = 50  # Порог владельцев для автозамены

# Директории
OUTPUT_DIR = "created_files"

# Имена файлов
INVENTORY_FILE = "inventory.json"
PARSED_INVENTORY_FILE = "parsed_inventory.json"
BOOST_CARD_FILE = "boost_card.json"