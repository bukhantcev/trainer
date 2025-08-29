import sqlite3

def exercise_status_icon(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return ""
    all_have = True
    any_fail = False
    for r in rows:
        ar = r["actual_reps"]
        tr = r["target_reps"]
        if ar is None:
            all_have = False
            continue
        if tr is not None and ar < tr:
            any_fail = True
    if any_fail:
        return "❌"
    if all_have:
        return "✅"
    return ""

def format_profile_card(row: sqlite3.Row | None) -> str:
    if not row:
        return "Профиль не найден."
    name = row["name"] if row["name"] else "не указано"
    age = row["age"] if row["age"] is not None else "не указано"
    height = row["height"] if row["height"] is not None else "не указано"
    weight = row["weight"] if row["weight"] is not None else "не указано"
    gender = row["gender"] if row["gender"] else "не указано"
    goal = row["goal"] if row["goal"] else "не указано"
    exp = row["experience"] if row["experience"] else "не указано"
    return (
        f"<b>Профиль</b>\n"
        f"Имя: {name}\n"
        f"Возраст: {age}\n"
        f"Рост: {height}\n"
        f"Вес: {weight}\n"
        f"Пол: {gender}\n"
        f"Цель: {goal}\n"
        f"Опыт: {exp}"
    )