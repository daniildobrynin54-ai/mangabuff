"""Конфигурация приложения MangaBuff с поддержкой прокси и rate limiting."""

# API настройки
BASE_URL = "https://mangabuff.ru"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0"

# Настройки прокси
PROXY_ENABLED = True  # Включить/выключить прокси
PROXY_URL = None  # Будет установлен из аргументов командной строки или переменной окружения

# Настройки пагинации
OWNERS_PER_PAGE = 36
WANTS_PER_PAGE = 60
CARDS_PER_BATCH = 10000  # Размер батча для availableCardsLoad (0-9999, 10000-19999, и т.д.)

# Пороги для приближенного подсчета
OWNERS_APPROXIMATE_THRESHOLD = 11
WANTS_APPROXIMATE_THRESHOLD = 5

# Оценки для последней страницы
OWNERS_LAST_PAGE_ESTIMATE = 18
WANTS_LAST_PAGE_ESTIMATE = 30

# Таймауты запросов (подключение, чтение) в секундах
REQUEST_TIMEOUT = (10, 20)  # Увеличены для работы через прокси

# Rate Limiting
RATE_LIMIT_PER_MINUTE = 66  # Максимум действий в минуту
RATE_LIMIT_RETRY_DELAY = 15  # Задержка перед повтором при 429 (секунды)
RATE_LIMIT_WINDOW = 60  # Окно для подсчета действий (секунды)

# Действия, которые считаются в rate limit
RATE_LIMITED_ACTIONS = {
    'send_trade',
    'load_owners_page',
    'load_wants_page',
    'load_user_cards',
}

# Задержки между запросами
DEFAULT_DELAY = 0.3
PAGE_DELAY = 0.6
PARSE_DELAY = 0.9
CARD_API_DELAY = 0.2

# Настройки обменов
MIN_TRADE_DELAY = 11.0
TRADE_RANDOM_DELAY_MIN = 0.5
TRADE_RANDOM_DELAY_MAX = 2.0

# Настройки мониторинга
MONITOR_CHECK_INTERVAL = 2
MONITOR_STATUS_INTERVAL = 30

# Настройки ожидания после обработки всех владельцев
WAIT_AFTER_ALL_OWNERS = 300
WAIT_CHECK_INTERVAL = 2

# Настройки кэша
CACHE_VALIDITY_HOURS = 24

# Настройки селектора карт
MAX_CARD_SELECTION_ATTEMPTS = 50

# Пропуск первых владельцев на первой странице
FIRST_PAGE_SKIP_OWNERS = 6

# Дневные лимиты
MAX_DAILY_DONATIONS = 50
MAX_DAILY_REPLACEMENTS = 10
MAX_CLUB_CARD_OWNERS = 50

# Настройки повторных попыток
MAX_RETRIES = 3  # Максимум попыток при ошибках сети
RETRY_DELAY = 2  # Базовая задержка между попытками

# Директории
OUTPUT_DIR = "created_files"

# Имена файлов
INVENTORY_FILE = "inventory.json"
PARSED_INVENTORY_FILE = "parsed_inventory.json"
BOOST_CARD_FILE = "boost_card.json"