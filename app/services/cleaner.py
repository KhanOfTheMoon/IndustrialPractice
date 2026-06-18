import re
from urllib.parse import unquote


PROCUREMENT_STOP_WORDS = {
    "работы",
    "работа",
    "услуги",
    "услуга",
    "по",
    "для",
    "и",
    "или",
    "аналогичной",
    "аналогичных",
    "аналогичные",
    "изделий",
    "изделия",
    "систем",
    "системы",
    "техническому",
    "техническое",
    "обслуживанию",
    "обслуживание",
    "ремонту",
    "ремонт",
    "модернизации",
    "модернизация",
}

RELEVANCE_STOP_WORDS = PROCUREMENT_STOP_WORDS | {
    "в",
    "во",
    "на",
    "с",
    "со",
    "от",
    "до",
    "за",
    "из",
    "к",
    "ко",
    "у",
    "о",
    "об",
    "при",
}

SERVICE_QUERY_WORDS = {
    "услуга",
    "услуги",
    "работы",
    "работа",
    "ремонт",
    "обслуживание",
    "модернизация",
    "монтаж",
    "аренда",
    "установка",
}

SERVICE_QUERY_STEMS = (
    "услуг",
    "работ",
    "ремонт",
    "обслуживан",
    "модернизац",
    "монтаж",
    "аренд",
    "установ",
)

SERVICE_BANNED_WORDS = {
    "услуга",
    "ремонт",
    "аренда",
    "прокат",
}


def clean_price(price_text: str) -> float | None:
    if not price_text:
        return None

    cleaned = price_text.lower()
    cleaned = cleaned.replace("₸", "")
    cleaned = cleaned.replace("тг", "")
    cleaned = cleaned.replace("kzt", "")
    cleaned = cleaned.replace(",", "")
    cleaned = cleaned.replace(" ", "")
    cleaned = cleaned.replace("от", "")

    numbers = re.findall(r"\d+", cleaned)

    if not numbers:
        return None

    return float("".join(numbers))


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.lower()
    text = text.replace("ё", "е")
    text = text.replace("айфон", "iphone")
    text = text.replace("айфона", "iphone")
    text = text.replace("айфону", "iphone")
    text = text.replace("эппл", "apple")
    text = text.replace("самсунг", "samsung")

    return text.strip()


def clean_search_text(query: str) -> str:
    if not query:
        return ""

    query = unquote(str(query))
    query = query.replace("/", " ")
    query = normalize_text(query)
    query = query.replace("_", " ")
    query = re.sub(r"[^\w\s-]+", " ", query, flags=re.UNICODE)
    query = re.sub(r"(?<!\w)-|-(?!\w)", " ", query)
    query = re.sub(r"\s+", " ", query)

    return query.strip()


def _truncate_to_words(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    words = text.split()
    truncated_words = []
    current_length = 0

    for word in words:
        next_length = current_length + len(word) + (1 if truncated_words else 0)

        if next_length > max_chars:
            break

        truncated_words.append(word)
        current_length = next_length

    if truncated_words:
        return " ".join(truncated_words)

    return text[:max_chars].strip()


def _text_words(text: str) -> list[str]:
    cleaned = clean_search_text(text)
    return re.findall(r"[0-9a-zа-яё]+(?:-[0-9a-zа-яё]+)*", cleaned)


def _meaningful_words(text: str) -> list[str]:
    return [
        word for word in _text_words(text)
        if len(word) >= 2 and word not in RELEVANCE_STOP_WORDS
    ]


def simplify_query(query: str, max_chars: int = 90) -> str:
    cleaned_query = clean_search_text(query)
    words = [
        word for word in _text_words(cleaned_query)
        if word not in PROCUREMENT_STOP_WORDS
    ]
    simplified = " ".join(words)

    return _truncate_to_words(simplified, max_chars)


def build_query_variants(query: str) -> list[str]:
    cleaned_query = _truncate_to_words(clean_search_text(query), 120)
    simplified_query = simplify_query(query)
    variants = [cleaned_query, simplified_query]

    simplified_words = simplified_query.split()

    if len(simplified_words) >= 4:
        if len(simplified_words) >= 2 and "-" in simplified_words[-2]:
            variants.append(" ".join(simplified_words[-2:]))
        elif len(simplified_words) > 4:
            variants.append(" ".join(simplified_words[-5:]))
        else:
            variants.append(" ".join(simplified_words[-3:]))

    unique_variants = []
    seen = set()

    for variant in variants:
        variant = variant.strip()

        if not variant or variant in seen:
            continue

        seen.add(variant)
        unique_variants.append(variant)

    return unique_variants


def detect_service_query(query: str) -> bool:
    words = _text_words(query)

    for word in words:
        if word in SERVICE_QUERY_WORDS:
            return True

        if any(word.startswith(stem) for stem in SERVICE_QUERY_STEMS):
            return True

    return False


def _words_match(query_word: str, title_word: str) -> bool:
    if query_word == title_word:
        return True

    if query_word.startswith(title_word) or title_word.startswith(query_word):
        return True

    if len(query_word) > 6 and len(title_word) > 6:
        return query_word[:5] == title_word[:5]

    return False


def _count_matching_words(query_words: list[str], title_words: list[str]) -> int:
    matched_words = 0

    for query_word in query_words:
        if any(_words_match(query_word, title_word) for title_word in title_words):
            matched_words += 1

    return matched_words


def get_category_rules(category: str) -> dict:
    rules = {
        "smartphones": {
            "required_any": [
                "смартфон",
                "smartphone",
                "iphone",
                "samsung",
                "galaxy",
                "xiaomi",
                "redmi",
                "poco",
                "honor",
                "huawei",
                "oppo",
                "vivo",
                "realme",
                "tecno",
                "infinix",
                "oneplus",
                "телефон",
            ],
            "banned": [
                "чехол",
                "case",
                "cover",
                "стекло",
                "защитное стекло",
                "glass",
                "пленка",
                "плёнка",
                "кабель",
                "зарядка",
                "зарядное",
                "адаптер",
                "переходник",
                "держатель",
                "штатив",
                "монопод",
                "селфи",
                "наушники",
                "гарнитура",
                "power bank",
                "powerbank",
                "повербанк",
                "экран",
                "дисплей",
                "батарея",
                "аккумулятор",
                "корпус",
                "крышка",
                "шлейф",
                "ремонт",
                "брендирование",
                "нанесение",
                "печать",
                "флешка",
                "usb",
                "картридж",
                "лазерный",
                "принтер",
            ],
        },

        "stationery": {
            "required_any": [
                "ручка",
                "карандаш",
                "тетрадь",
                "блокнот",
                "бумага",
                "маркер",
                "ластик",
                "папка",
                "файл",
                "скрепки",
                "степлер",
                "канцтовары",
                "канцелярия",
            ],
            "banned": [
                "держатель",
                "органайзер для телефона",
                "ремонт",
                "услуга",
                "печать на",
                "брендирование",
            ],
        },

        "electronics": {
            "required_any": [
                "ноутбук",
                "принтер",
                "монитор",
                "клавиатура",
                "мышь",
                "роутер",
                "планшет",
                "наушники",
                "колонка",
                "камера",
            ],
            "banned": [
                "ремонт",
                "запчасть",
                "кабель для",
                "чехол",
                "сумка",
                "услуга",
            ],
        },

        "furniture": {
            "required_any": [
                "кресло",
                "стол",
                "стул",
                "шкаф",
                "диван",
                "полка",
                "тумба",
                "мебель",
            ],
            "banned": [
                "ремонт",
                "аренда",
                "чехол",
                "ткань",
                "запчасть",
            ],
        },

        "general": {
            "required_any": [],
            "banned": [
                "услуга",
                "ремонт",
                "аренда",
                "прокат",
                "нанесение",
                "брендирование",
                "печать на",
                "под заказ",
            ],
        },
    }

    return rules.get(category, rules["general"])


def is_relevant_product(title: str, query: str, category: str = "general",strict_title_match: bool = False,) -> bool:
    title_lower = normalize_text(title)
    service_query = detect_service_query(query)

    if not title_lower:
        return False

    rules = get_category_rules(category)

    # 1 Убираем запрещённые слова для категории
    for banned_word in rules["banned"]:
        if service_query and banned_word in SERVICE_BANNED_WORDS:
            continue

        if banned_word in title_lower:
            return False

    # 2 Если у категории есть обязательные признаки, проверяем их
    required_any = rules["required_any"]

    if required_any:
        has_required_word = any(word in title_lower for word in required_any)

        if not has_required_word:
            return False
        
    if strict_title_match:
        return title_matches_query_strict(title, query)
    
    # 3 Проверяем совпадение с запросом
    query_words = _meaningful_words(query)
    title_words = _text_words(title)

    if not query_words:
        return False

    matched_words = _count_matching_words(query_words, title_words)

    # Для короткого запроса достаточно одного совпадения
    if len(query_words) == 1:
        return matched_words >= 1

    if len(query_words) >= 5:
        return matched_words >= 2

    # Для длинного запроса достаточно примерно половины совпадений
    return matched_words >= max(1, len(query_words) // 2)


def remove_duplicates(products: list[dict]) -> list[dict]:
    seen = set()
    unique_products = []

    for product in products:
        url_key = product.get("url")
        title_key = normalize_text(product.get("title", ""))
        price_key = product.get("price")

        key = (url_key, title_key, price_key)

        if key in seen:
            continue

        seen.add(key)
        unique_products.append(product)

    return unique_products

def title_matches_query_strict(title: str, query: str) -> bool:
    """
    Строгий поиск по названию.
    Все важные слова из запроса должны быть в названии товара.
    """
    title_words = _text_words(title)
    query_words = _meaningful_words(query)

    if not query_words:
        return False

    for word in query_words:
        if not any(_words_match(word, title_word) for title_word in title_words):
            return False

    return True
