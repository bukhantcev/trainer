import json
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL
from prompt import PROMPT, PROMPT_YOGA

def get_openai_client() -> OpenAI | None:
    if not OPENAI_API_KEY:
        return None
    return OpenAI(api_key=OPENAI_API_KEY)

def _detect_mode(payload: dict) -> str | None:
    """
    Возвращает режим из payload, если он есть. Ищет в:
    - payload["пользователь"]
    - корне payload
    Поддерживает ключи: 'режим', 'Режим', 'training_type', 'training_mode', 'mode'
    """
    try:
        # источники для поиска
        sources = []
        sources.append((payload or {}).get("пользователь") or {})
        sources.append(payload or {})
        # перебираем ключи
        for src in sources:
            for k in ("режим", "Режим", "training_type", "training_mode", "mode"):
                if k in src and src[k]:
                    return str(src[k]).strip().lower()
    except Exception:
        pass
    return None


# Helper: Проверка на пустой промпт
def _is_empty_prompt(p) -> bool:
    """Возвращает True, если промпт отсутствует или является маркером пустого значения.
    Принимаем как пустые: None, "", "none", "null", "nil", "default", "/default", "auto" (в любом регистре).
    """
    if p is None:
        return True
    try:
        s = str(p).strip()
    except Exception:
        return True
    if not s:
        return True
    if s.lower() in {"none", "null", "nil", "default", "/default", "auto"}:
        return True
    return False

def _resolve_prompt(payload: dict, user_prompt: str | None) -> str:
    """
    Возвращает итоговый промпт: приоритет user_prompt, но:
    - если user_prompt пустой/маркер пустоты -> берём по режиму
    - если user_prompt равен одному из дефолтных шаблонов (PROMPT или PROMPT_YOGA),
      считаем это "дефолтным" и подменяем согласно текущему режиму.
    """
    # 0) Отладка входных параметров
    try:
        print(f"[PROMPT] _resolve_prompt: user_prompt={'EMPTY' if _is_empty_prompt(user_prompt) else 'SET'}")
    except Exception:
        pass

    # 1) Нормализация набора алиасов режима
    power_aliases = {"силовая", "силовые", "силовые тренировки", "power", "strength"}
    yoga_aliases = {"йога", "пилатес", "йога/пилатес", "yoga", "pilates", "yoga/pilates"}

    # 2) Если пользователь явно задал свой промпт
    if not _is_empty_prompt(user_prompt):
        up = str(user_prompt).strip()

        # Если пользовательский промпт фактически равен одному из дефолтных шаблонов,
        # трактуем его как "дефолт" и выбираем по текущему режиму.
        if up == PROMPT or up == PROMPT_YOGA:
            mode_dbg = _detect_mode(payload)
            try:
                print(f"[PROMPT] Кастомный промпт совпадает с дефолтным шаблоном. Режим='{mode_dbg}'. Выбираю по режиму.")
            except Exception:
                pass
            if mode_dbg in yoga_aliases:
                return PROMPT_YOGA
            # силовой по умолчанию
            return PROMPT

        # Иначе это реально кастом — отдаём как есть
        try:
            mode_dbg = _detect_mode(payload)
            print(f"[PROMPT] Использую реальный кастомный user_prompt. Обнаруженный режим='{mode_dbg}' (игнорируется).")
        except Exception:
            pass
        return up

    # 3) user_prompt пуст — определяем режим
    mode = _detect_mode(payload)

    # 4) Выбор промпта по режиму
    if mode in yoga_aliases:
        try:
            print(f"[PROMPT] Режим детектирован как 'yoga/pilates' ('{mode}') → выбираю PROMPT_YOGA.")
        except Exception:
            pass
        return PROMPT_YOGA

    try:
        print(f"[PROMPT] Режим детектирован как 'силовой' ('{mode}') или отсутствует → выбираю базовый PROMPT.")
    except Exception:
        pass
    return PROMPT

def ask_openai(payload: dict, prompt: str) -> tuple[str, list[dict]]:
    """
    Возвращает (raw_text, items_list). items_list — это распарсенный JSON-массив с планом.
    """
    client = get_openai_client()
    if not client:
        return "[OpenAI] ERROR: OPENAI_API_KEY is not set", []

    final_prompt = _resolve_prompt(payload, prompt)

    try:
        detected_mode = _detect_mode(payload)
        if final_prompt == PROMPT_YOGA:
            chosen = "YOGA"
        elif final_prompt == PROMPT:
            chosen = "STRENGTH"
        else:
            chosen = "CUSTOM"
        print(f"[PROMPT] Детектированный режим='{detected_mode}' → выбран промпт: {chosen}")
    except Exception:
        pass

    if _is_empty_prompt(final_prompt):
        # Резерв: если по какой-то причине пришёл пустой промпт — используем силовой по умолчанию
        final_prompt = PROMPT

    content = (
        "Ниже данные пользователя и история за 30 дней в формате JSON (на русском). "
        "Ответ присылай в чистом json без пояснений и лишних слов, сухая информация. Поля - Название упражнения, Номер подхода, Вес, Количество повторений"
        "Используй мой промпт после данных.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\nПромпт:\n"
        + final_prompt
    )

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "Ты умный тренер-ассистент. Отвечай кратко и по делу."},
            {"role": "user", "content": content},
        ],
    )
    text = resp.choices[0].message.content if resp and resp.choices else "(пустой ответ)"
    print(text)
    items = []
    try:
        s, e = text.find('['), text.rfind(']')
        if s != -1 and e != -1 and e > s:
            items = json.loads(text[s:e+1])
        else:
            items = json.loads(text)
    except Exception:
        items = []
    return text, items