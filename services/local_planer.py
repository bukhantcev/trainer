# --- Local planner -----------------------------------------------------------

from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from datetime import date as _date

def generate_plan(payload: Dict, today: Optional[str] = None) -> List[Dict]:
    """
    Делает то же самое, что промпт к OpenAI: строит план на 1 день.
    Вход: payload = {"пользователь": {...}, "история": [...], "анкета": {...} (опционально)}
    Выход: список словарей с ключами: Название упражнения, Номер подхода, Вес, Количество повторений.
    """

    user = payload.get("пользователь", {}) or {}
    history = payload.get("история", []) or []
    anketa = payload.get("анкета", {}) or {}
    print(anketa)

    # --- normalize anketa/user keys: lowercased, spaces->'_', 'ё'->'е', plus alias map
    def _norm_dict(src: Dict) -> Dict:
        nd = {}
        for k, v in (src or {}).items():
            kk = str(k).strip().lower()
            kk = kk.replace(" ", "_").replace("-", "_").replace("ё", "е")
            nd[kk] = v
        # aliases -> canonical keys
        alias_map = {
            # bench
            "жим_лежа_1пм": "жим_лежа_макс_кг",
            "жим_штанги_лежа_макс": "жим_лежа_макс_кг",
            "жим_штанги_лежа_макс_кг": "жим_лежа_макс_кг",
            "bench_1rm": "bench_max_kg",
            # close-grip bench (triceps 1RM proxy)
            "жим_узким_хватом_макс_кг": "узкий_жим_макс_кг",
            "узкий_жим_лежа_макс_кг": "узкий_жим_макс_кг",
            "узкий_жим_1пм": "узкий_жим_макс_кг",
            # squat
            "присед_1пм": "присед_макс_кг",
            # deadlift
            "становая_1пм": "становая_макс_кг",
            # ohp
            "армейский_жим_1пм": "армейский_жим_макс_кг",
            "жим_штанги_стоя_макс_кг": "армейский_жим_макс_кг",
        }
        for a, b in alias_map.items():
            if a in nd and b not in nd:
                nd[b] = nd[a]
        return nd

    user = _norm_dict(user)
    anketa = _norm_dict(anketa)

    # --- numeric coercion
    def _to_int(x):
        try:
            if x is None:
                return None
            if isinstance(x, (int, float)):
                return int(x)
            s = str(x).strip().replace(",", ".")
            f = float(s)
            return int(round(f))
        except Exception:
            return None

    # --- last record util already defined below, but we need a lightweight name list search here
    def _last_record_for_any(names: List[str]) -> Optional[Dict]:
        cand = []
        for r in history:
            rn = (r.get("упражнение") or "").lower()
            if any(n.lower() == rn for n in names):
                if r.get("дата"):
                    cand.append(r)
        if not cand:
            return None
        cand.sort(key=lambda x: (_to_date(x["дата"]), x.get("подход", 0)))
        return cand[-1]

    # --- estimate 1RM from history using Epley (w * (1 + reps/30))
    def _estimate_1rm_from_history(names: List[str]) -> Optional[int]:
        r = _last_record_for_any(names)
        if not r:
            return None
        w = _to_int(r.get("вес"))
        reps = _to_int(r.get("выполненные_повторения")) or _to_int(r.get("целевые_повторения"))
        if w is None or reps is None or reps <= 0:
            return None
        return int(round(w * (1 + reps / 30.0)))

    # --- Extract 1RM from anketa/user by aliases with history fallback
    def _extract_1rm(alias_keys: List[str], hist_names: List[str]) -> Optional[int]:
        # try anketa then user
        for src in (anketa, user):
            for k in alias_keys:
                v = src.get(k)
                iv = _to_int(v)
                if iv is not None and iv > 0:
                    return iv
        # fallback from history
        return _estimate_1rm_from_history(hist_names)

    # aliases and canonical exercise names for history lookup
    _BENCH_KEYS = ["жим_лежа_макс_кг", "bench_max_kg", "1пм_жим_лежа", "1rm_bench"]
    _BENCH_NAMES = [
        "жим штанги лежа",
        "жим лежа (штанга)",
    ]

    _CGBP_KEYS = [
        "узкий_жим_макс_кг",
        "cgbp_max_kg",
        "узкий_жим_штанги_лежа_макс_кг",
        "жим_узким_хватом_макс_кг",
        "узкий_жим_лежа_макс_кг",
    ]
    _CGBP_NAMES = [
        "узкий жим штанги лежа",
        "жим узким хватом",
    ]

    _SQUAT_KEYS = ["присед_макс_кг", "squat_max_kg", "1rm_squat", "1пм_присед"]
    _SQUAT_NAMES = ["приседания со штангой"]

    _DL_KEYS = ["становая_макс_кг", "deadlift_max_kg", "1rm_deadlift", "1пм_становая"]
    _DL_NAMES = ["становая тяга", "становая тяга классическая (штанга)"]

    _OHP_KEYS = ["ohp_max_kg", "армейский_жим_макс_кг", "1rm_ohp"]
    _OHP_NAMES = ["жим штанги стоя", "армейский жим"]

    # --- утилиты даты
    def _to_date(s: str) -> _date:
        return _date.fromisoformat(s)

    # --- классификация упражнений по группам
    CHEST = "chest"; TRIS = "tris"; SHOULD = "should"; LEGS = "legs"; BACK = "back"; BICEPS = "biceps"; ABS = "abs"
    PAIRS = [("chest","tris"), ("should","legs"), ("back","biceps")]

    def _norm_name(n: Optional[str]) -> str:
        return (n or "").strip().lower().replace("ё", "е")

    def muscle_group(name: str) -> Optional[str]:
        n = _norm_name(name)
        # грудь
        if any(k in n for k in ["жим штанги лежа", "жим гантелей", "жим штанги на наклонной", "сведение рук"]):
            return CHEST
        # трицепс
        if any(k in n for k in ["узкий жим", "разгибани", "трицепс", "французский жим"]):
            return TRIS
        # плечи
        if any(k in n for k in ["жим штанги стоя", "армейский жим", "жим стоя", "мах", "плеч"]):
            return SHOULD
        # ноги
        if any(k in n for k in ["присед", "жим ногами", "сгибания ног", "икр", "носки"]):
            return LEGS
        # спина
        if any(k in n for k in ["становая", "тяга штанги в наклоне", "тяга горизонтального блока", "тяга вертикального блока", "подтягиван"]):
            return BACK
        # бицепс
        if any(k in n for k in ["бицепс", "молотков"]):
            return BICEPS
        # пресс
        if any(k in n for k in ["скручивания", "подъем ног", "пресс"]):
            return ABS
        return None

    # --- найти последнюю дату в истории и доминирующую пару групп на ней
    next_pair_idx = 1  # if history is empty, start with Legs+Shoulders ("should","legs")
    if history:
        # сгруппируем по дате
        by_date: Dict[str, List[Dict]] = defaultdict(list)
        for r in history:
            if r.get("дата"): by_date[r["дата"]].append(r)
        last_date = max(by_date.keys(), key=_to_date)
        groups_count = defaultdict(int)
        for r in by_date[last_date]:
            g = muscle_group(r.get("упражнение","") or "")
            if g in (CHEST, TRIS, SHOULD, LEGS, BACK, BICEPS):
                groups_count[g] += 1
        # определить пару, которая преобладала
        def _pair_of(groups: Dict[str,int]) -> Tuple[str,str]:
            # суммируем chest+tris, should+legs, back+biceps
            sums = [
                (groups.get(BACK,0)+groups.get(BICEPS,0), ("back","biceps")),
                (groups.get(CHEST,0)+groups.get(TRIS,0), ("chest","tris")),
                (groups.get(SHOULD,0)+groups.get(LEGS,0), ("should","legs")),
            ]
            sums.sort(key=lambda x: x[0], reverse=True)
            return sums[0][1]
        last_pair = _pair_of(groups_count)
        # выбрать следующую в цикле
        idx_map = {("chest","tris"):0, ("should","legs"):1, ("back","biceps"):2}
        next_pair_idx = (idx_map.get(last_pair, 0) + 1) % 3
    target_pair = PAIRS[next_pair_idx]  # кортеж из ('back','biceps') и т.п.

    # --- быстрый доступ к последним подходам по упражнению
    def last_records_for_ex(ex_name: str) -> List[Dict]:
        ex = []
        for r in history:
            if _norm_name(r.get("упражнение")) == _norm_name(ex_name):
                ex.append(r)
        ex.sort(key=lambda x: (_to_date(x["дата"]), x.get("подход", 0)))
        return ex

    def last_weight_and_delta(ex_name: str, default_weight: Optional[int]=None, default_reps: Optional[int]=None) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        """
        Возвращает (last_weight, last_target_reps, last_actual_reps).
        Берёт самый свежий подход по этому упражнению, у которого есть target; actual может быть None.
        """
        recs = last_records_for_ex(ex_name)
        if recs:
            r = recs[-1]
            return r.get("вес"), r.get("целевые_повторения"), r.get("выполненные_повторения")
        return default_weight, default_reps, None

    # --- проценты от 1ПМ для прикидки веса (если нет истории)
    PCT_BY_REPS = {5:0.85, 6:0.83, 7:0.80, 8:0.78, 9:0.76, 10:0.74, 12:0.70, 15:0.60}

    def est_from_1rm(one_rm: Optional[int], reps: int) -> Optional[int]:
        if not one_rm: return None
        pct = PCT_BY_REPS.get(reps)
        if not pct:  # ближайшее значение
            keys = sorted(PCT_BY_REPS.keys(), key=lambda k: abs(k-reps))
            pct = PCT_BY_REPS[keys[0]]
        return max(1, int(round(one_rm * pct)))

    # --- оценка стартового веса для конкретного упражнения
    def estimate_base_weight(ex_name: str, reps: int) -> Optional[int]:
        n = _norm_name(ex_name)

        # если в истории уже есть вес — используем его
        w_last, _, _ = last_weight_and_delta(ex_name)
        if isinstance(w_last, (int, float)):
            return int(w_last)

        # 1ПМ из анкеты / профиля
        bench = _extract_1rm(_BENCH_KEYS, _BENCH_NAMES)
        squat = _extract_1rm(_SQUAT_KEYS, _SQUAT_NAMES)
        deadl = _extract_1rm(_DL_KEYS, _DL_NAMES)
        ohp   = _extract_1rm(_OHP_KEYS, _OHP_NAMES)

        # НОВОЕ: используем 1ПМ узкого жима как якорь для трицепса
        cgbp  = _extract_1rm(_CGBP_KEYS, _CGBP_NAMES)
        if not cgbp and bench:
            cgbp = int(round(bench * 0.92))  # эвристика: узкий жим ≈ 92% от обычного жима

        # --- DEBUG: print detected 1RMs from anketa/user/history
        try:
            print("[1RM] bench=", bench, "kg; cgbp=", cgbp, "kg; squat=", squat, "kg; deadlift=", deadl, "kg; ohp=", ohp, "kg")
        except Exception:
            pass

        # DEBUG: uncomment if you need to trace missing 1RMs
        # print({
        #     "bench": bench, "squat": squat, "deadlift": deadl, "ohp": ohp, "cgbp": cgbp,
        #     "anketa_keys": list(anketa.keys()),
        # })

        # --- грудь
        if "жим штанги лежа" in n and "узкий" not in n:
            return est_from_1rm(bench, reps)
        if "жим штанги на наклонной" in n or ("жим гантелей" in n and "наклон" in n):
            base = est_from_1rm(bench, reps)
            return int(base * 0.85) if base else None  # наклон обычно ~85% от плоской
        if "сведение рук" in n or "кроссовер" in n:
            # изолирующее относительно жима
            base = est_from_1rm(bench, reps)
            return int(base * 0.55) if base else 45

        # --- трицепс
        if "узкий жим" in n:
            return est_from_1rm(cgbp or bench, reps) or (est_from_1rm(bench, reps) if bench else None)

        if "французский жим" in n:
            base = est_from_1rm(cgbp or bench, reps)
            return int(base * 0.55) if base else 30

        if "разгибания на трицепс" in n or ("трицепс" in n and "разгиб" in n):
            base = est_from_1rm(cgbp or bench, reps)
            return int(base * 0.50) if base else 25

        # --- ноги
        if "присед" in n:
            return est_from_1rm(squat, reps)
        if "жим ногами" in n:
            base = est_from_1rm(squat, reps)
            return int(base * 2.2) if base else 140  # тренажер обычно сильно больше
        if "сгибания ног" in n:
            base = est_from_1rm(squat, reps)
            return int(base * 0.55) if base else 35
        if "икр" in n or "носки" in n:
            base = est_from_1rm(squat, reps)
            return int(base * 0.9) if base else 80

        # --- спина
        if "становая" in n:
            return est_from_1rm(deadl, reps)
        if "тяга штанги в наклоне" in n:
            base = est_from_1rm(deadl, reps)
            return int(base * 0.6) if base else 60
        if "горизонтального блока" in n or "вертикального блока" in n:
            base = est_from_1rm(deadl, reps)
            return int(base * 0.5) if base else 60
        if "подтягиван" in n:
            # оставим последний или ориентир по массе тела
            bw = user.get("Вес") or anketa.get("Вес") or 70
            return int(bw + 10)  # "вес" как масса/нагрузка в твоей схеме

        # --- плечи
        if "жим штанги стоя" in n or "армейский жим" in n or "жим стоя" in n:
            return est_from_1rm(ohp, reps)
        if "мах" in n:
            base = est_from_1rm(ohp, reps)
            return int(base * 0.25) if base else 8

        # --- бицепс
        if "бицепс" in n and "молотков" not in n:
            base = est_from_1rm(bench, reps)
            return int(base * 0.45) if base else 35
        if "молотков" in n:
            base = est_from_1rm(bench, reps)
            return int(base * 0.25) if base else 16

        # --- пресс
        if "скручивания" in n or "подъем ног" in n:
            return 0

        return None

    # --- корректировка веса по разнице целевых/выполненных
    def adjust_weight(ex_name: str, target_reps: int, base_weight: Optional[int]) -> int:
        if base_weight is None:
            base_weight = estimate_base_weight(ex_name, target_reps) or 0
        w_last, t_last, a_last = last_weight_and_delta(ex_name)
        w = int(base_weight)

        if a_last is None or t_last is None or w_last is None:
            return max(0, w)

        diff = int(a_last) - int(t_last)
        if diff <= -2:
            w = int(round(w_last * 0.93))  # -7%
        elif diff == -1:
            w = int(round(w_last * 0.97))  # -3%
        elif diff == 0:
            w = int(round(w_last))         # 0%
        elif diff == 1:
            w = int(round(w_last * 1.03))  # +3%
        else:  # >= +2
            w = int(round(w_last * 1.06))  # +6%
        return max(0, w)

    # --- выбор упражнений & схемы повторений по паре групп
    def scheme_for_pair(pair: Tuple[str,str]) -> List[Tuple[str, List[int]]]:
        if pair == ("chest","tris"):
            # немного вариативности: если в истории был "жим гантелей на наклонной" — ставим штангу, и наоборот
            used_dumb_incline = any("жим гантелей на наклонной" in (r.get("упражнение","").lower()) for r in history)
            incline = "Жим штанги на наклонной скамье" if used_dumb_incline else "Жим гантелей на наклонной скамье"
            return [
                ("Жим штанги лежа",                 [8, 8, 7, 6]),
                (incline,                            [10, 9, 8]),
                ("Сведение рук в тренажере",        [12, 12, 10]),
                ("Узкий жим штанги лежа",           [8, 8, 7]),
                ("Разгибания на трицепс на канате", [12, 12, 10]),
                ("Скручивания на канате",           [15, 15]),
                ("Подъем ног в висе",               [12, 12]),
            ]
        if pair == ("should","legs"):
            return [
                ("Приседания со штангой",           [8, 8, 7, 6]),
                ("Жим ногами в тренажере",          [12, 11, 10]),
                ("Сгибания ног лёжа в тренажере",   [12, 12, 10]),
                ("Подъемы на носки стоя в тренажере",[15, 13, 12]),
                ("Жим штанги стоя",                 [8, 8, 7, 6]),
                ("Махи гантелями в стороны",        [12, 10, 10]),
                ("Скручивания на канате",           [15, 15]),
            ]
        # ("back","biceps")
        # небольшая вариативность по вертикальной/горизонтальной тяге
        used_vert = any("тяга вертикального блока" in (r.get("упражнение","").lower()) for r in history)
        lat = "Тяга горизонтального блока" if used_vert else "Тяга вертикального блока"
        return [
            ("Становая тяга",                      [5, 5, 5, 5]),
            ("Тяга штанги в наклоне",             [8, 8, 7]),
            (lat,                                  [10, 10, 9]),
            ("Подтягивания с весом",               [8, 8, 6]),
            ("Подъем штанги на бицепс",           [8, 8, 8]),
            ("Молотковые сгибания гантелей",      [10, 9, 8]),
            ("Скручивания на канате",             [15, 15]),
        ]

    # --- собрать план
    plan: List[Dict] = []
    for ex_name, reps_list in scheme_for_pair(target_pair):
        for i, reps in enumerate(reps_list, start=1):
            w0 = estimate_base_weight(ex_name, reps)
            w = adjust_weight(ex_name, reps, w0)
            plan.append({
                "Название упражнения": ex_name,
                "Номер подхода": i,
                "Вес": int(w),
                "Количество повторений": int(reps),
            })
    return plan
# --- /Local planner -----------------------------------------------------------