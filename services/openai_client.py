import json
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL

def get_openai_client() -> OpenAI | None:
    if not OPENAI_API_KEY:
        return None
    return OpenAI(api_key=OPENAI_API_KEY)

def ask_openai(payload: dict, prompt: str) -> tuple[str, list[dict]]:
    """
    Возвращает (raw_text, items_list). items_list — это распарсенный JSON-массив с планом.
    """
    client = get_openai_client()
    if not client:
        return "[OpenAI] ERROR: OPENAI_API_KEY is not set", []

    content = (
        "Ниже данные пользователя и история за 30 дней в формате JSON (на русском). "
        "Ответ присылай в чистом json без пояснений и лишних слов, сухая информация. Поля - Название упражнения, Номер подхода, Вес, Количество повторений"
        "Используй мой промпт после данных.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\nПромпт:\n"
        + (prompt or "")
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