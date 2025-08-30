# --- Local planner -----------------------------------------------------------
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from datetime import date as _date

def generate_plan(payload: Dict, today: Optional[str] = None) -> List[Dict]:
    """
    Универсальный планировщик:
    - payload["режим"] in {"strength", "yoga", "pilates"} (по умолчанию "strength")
    - Вход: {"пользователь": {...}, "история": [...], "анкета": {...} (опционально)}
    - Выход: список словарей:
      {"Название упражнения", "Номер подхода", "Вес", "Количество повторений"}
      Для йоги/пилатеса: Вес=0, Количество повторений = длительность сета в секундах.
    """

    mode = (payload.get("режим") or "strength").strip().lower()
    if mode in ("йога", "yoga"):     mode = "yoga"
    if mode in ("пилатес", "pilates"): mode = "pilates"

    user = (payload.get("пользователь") or {}) | {}
    history = payload.get("история", []) or []
    anketa = payload.get("анкета", {}) or {}

    # ---------- helpers: normalize ----------
    def _norm_name(n: Optional[str]) -> str:
        return (n or "").strip().lower().replace("ё", "е")

    def _to_date(s: str) -> _date:
        return _date.fromisoformat(s)

    def _to_int(x):
        try:
            if x is None: return None
            if isinstance(x, (int, float)): return int(x)
            s = str(x).strip().replace(",", ".")
            return int(round(float(s)))
        except Exception:
            return None

    # ---------- strength-specific: aliases & 1RM machinery ----------
    def _norm_dict(src: Dict) -> Dict:
        nd = {}
        for k, v in (src or {}).items():
            kk = str(k).strip().lower()
            kk = kk.replace(" ", "_").replace("-", "_").replace("ё", "е")
            nd[kk] = v
        alias_map = {
            "жим_лежа_1пм": "жим_лежа_макс_кг",
            "жим_штанги_лежа_макс": "жим_лежа_макс_кг",
            "жим_штанги_лежа_макс_кг": "жим_лежа_макс_кг",
            "bench_1rm": "bench_max_kg",

            "жим_узким_хватом_макс_кг": "узкий_жим_макс_кг",
            "узкий_жим_лежа_макс_кг": "узкий_жим_макс_кг",
            "узкий_жим_1пм": "узкий_жим_макс_кг",

            "присед_1пм": "присед_макс_кг",
            "становая_1пм": "становая_макс_кг",
            "армейский_жим_1пм": "армейский_жим_макс_кг",
            "жим_штанги_стоя_макс_кг": "армейский_жим_макс_кг",
        }
        for a, b in alias_map.items():
            if a in nd and b not in nd:
                nd[b] = nd[a]
        return nd

    user_n = _norm_dict(user)
    anketa_n = _norm_dict(anketa)

    def _last_records_for_ex(ex_name: str) -> List[Dict]:
        ex = []
        for r in history:
            if _norm_name(r.get("упражнение")) == _norm_name(ex_name):
                ex.append(r)
        ex.sort(key=lambda x: (_to_date(x["дата"]), x.get("подход", 0)))
        return ex

    def last_weight_and_delta(ex_name: str, default_weight: Optional[int]=None, default_reps: Optional[int]=None):
        recs = _last_records_for_ex(ex_name)
        if recs:
            r = recs[-1]
            return r.get("вес"), r.get("целевые_повторения"), r.get("выполненные_повторения")
        return default_weight, default_reps, None

    # ---------- mode: STRENGTH ----------
    if mode == "strength":
        # группы и ротация
        CHEST = "chest"; TRIS = "tris"; SHOULD = "should"; LEGS = "legs"; BACK = "back"; BICEPS = "biceps"; ABS = "abs"
        PAIRS = [("chest","tris"), ("should","legs"), ("back","biceps")]  # порядок по ТЗ

        def muscle_group(name: str) -> Optional[str]:
            n = _norm_name(name)
            if any(k in n for k in ["жим штанги лежа", "жим гантелей", "жим штанги на наклонной", "сведение рук", "кроссовер"]):
                return CHEST
            if any(k in n for k in ["узкий жим", "разгибани", "трицепс", "французский жим"]):
                return TRIS
            if any(k in n for k in ["жим штанги стоя", "армейский жим", "жим стоя", "мах", "плеч"]):
                return SHOULD
            if any(k in n for k in ["присед", "жим ногами", "сгибания ног", "икр", "носки"]):
                return LEGS
            if any(k in n for k in ["становая", "тяга штанги в наклоне", "тяга горизонтального блока", "тяга вертикального блока", "подтягиван"]):
                return BACK
            if any(k in n for k in ["бицепс", "молотков"]):
                return BICEPS
            if any(k in n for k in ["скручивания", "подъем ног", "пресс"]):
                return ABS
            return None

        # старт: если истории нет — Ноги+Плечи (по твоему новому правилу)
        # Новый алгоритм определения следующей пары:
        # 1) Берем самую свежую дату из истории.
        # 2) На этой дате берём ПОСЛЕДНЕЕ упражнение (по наибольшему "подход"),
        #    игнорируем ABS.
        # 3) Определяем к какой группе относится это упражнение и, следовательно,
        #    к какой паре (chest+tris / should+legs / back+biceps) оно относится.
        # 4) Следующая пара — это следующая по циклу после найденной.
        next_pair_idx = 1  # default: ("should","legs") если истории нет
        if history:
            # сгруппируем по дате → возьмём самую свежую
            by_date: Dict[str, List[Dict]] = defaultdict(list)
            for r in history:
                if r.get("дата"):
                    by_date[r["дата"]].append(r)
            last_date = max(by_date.keys(), key=_to_date)

            # найдём последний (по номеру подхода) сет с распознаваемой группой (кроме ABS)
            day_records = by_date[last_date]
            # если где-то нет номера подхода — считаем 0, чтобы не ломаться
            day_records.sort(key=lambda x: (x.get("подход", 0)))

            last_group = None
            for r in reversed(day_records):
                g = muscle_group(r.get("упражнение", "") or "")
                if g in (CHEST, TRIS, SHOULD, LEGS, BACK, BICEPS):
                    last_group = g
                    break

            # маппинг группы → индекс пары
            if last_group is not None:
                # какая пара содержит эту группу
                if last_group in (CHEST, TRIS):
                    curr_pair = ("chest", "tris")
                elif last_group in (SHOULD, LEGS):
                    curr_pair = ("should", "legs")
                else:  # BACK, BICEPS
                    curr_pair = ("back", "biceps")

                idx_map = {("chest","tris"):0, ("should","legs"):1, ("back","biceps"):2}
                next_pair_idx = (idx_map[curr_pair] + 1) % 3

        target_pair = PAIRS[next_pair_idx]

        # 1ПМ извлечение
        def _last_record_for_any(names: List[str]) -> Optional[Dict]:
            cand = []
            for r in history:
                rn = _norm_name(r.get("упражнение"))
                if any(_norm_name(n) == rn for n in names):
                    if r.get("дата"):
                        cand.append(r)
            if not cand: return None
            cand.sort(key=lambda x: (_to_date(x["дата"]), x.get("подход", 0)))
            return cand[-1]

        def _estimate_1rm_from_history(names: List[str]) -> Optional[int]:
            r = _last_record_for_any(names)
            if not r: return None
            w = _to_int(r.get("вес"))
            reps = _to_int(r.get("выполненные_повторения")) or _to_int(r.get("целевые_повторения"))
            if w is None or reps is None or reps <= 0: return None
            return int(round(w * (1 + reps / 30.0)))

        def _extract_1rm(alias_keys: List[str], hist_names: List[str]) -> Optional[int]:
            for src in (anketa_n, user_n):
                for k in alias_keys:
                    v = src.get(k)
                    iv = _to_int(v)
                    if iv and iv > 0:
                        return iv
            return _estimate_1rm_from_history(hist_names)

        _BENCH_KEYS = ["жим_лежа_макс_кг", "bench_max_kg", "1пм_жим_лежа", "1rm_bench"]
        _BENCH_NAMES = ["жим штанги лежа", "жим лежа (штанга)"]

        _CGBP_KEYS = ["узкий_жим_макс_кг", "cgbp_max_kg", "узкий_жим_штанги_лежа_макс_кг", "жим_узким_хватом_макс_кг", "узкий_жим_лежа_макс_кг"]
        _CGBP_NAMES = ["узкий жим штанги лежа", "жим узким хватом"]

        _SQUAT_KEYS = ["присед_макс_кг", "squat_max_kg", "1rm_squat", "1пм_присед"]
        _SQUAT_NAMES = ["приседания со штангой"]

        _DL_KEYS = ["становая_макс_кг", "deadlift_max_kg", "1rm_deadlift", "1пм_становая"]
        _DL_NAMES = ["становая тяга", "становая тяга классическая (штанга)"]

        _OHP_KEYS = ["ohp_max_kg", "армейский_жим_макс_кг", "1rm_ohp"]
        _OHP_NAMES = ["жим штанги стоя", "армейский жим"]

        PCT_BY_REPS = {5:0.85, 6:0.83, 7:0.80, 8:0.78, 9:0.76, 10:0.74, 12:0.70, 15:0.60}

        def est_from_1rm(one_rm: Optional[int], reps: int) -> Optional[int]:
            if not one_rm: return None
            pct = PCT_BY_REPS.get(reps)
            if not pct:
                keys = sorted(PCT_BY_REPS.keys(), key=lambda k: abs(k-reps))
                pct = PCT_BY_REPS[keys[0]]
            return max(1, int(round(one_rm * pct)))

        def estimate_base_weight(ex_name: str, reps: int) -> Optional[int]:
            n = _norm_name(ex_name)
            w_last, _, _ = last_weight_and_delta(ex_name)
            if isinstance(w_last, (int, float)):
                return int(w_last)

            bench = _extract_1rm(_BENCH_KEYS, _BENCH_NAMES)
            squat = _extract_1rm(_SQUAT_KEYS, _SQUAT_NAMES)
            deadl = _extract_1rm(_DL_KEYS, _DL_NAMES)
            ohp   = _extract_1rm(_OHP_KEYS, _OHP_NAMES)
            cgbp  = _extract_1rm(_CGBP_KEYS, _CGBP_NAMES)
            if not cgbp and bench:
                cgbp = int(round(bench * 0.92))

            # грудь
            if "жим штанги лежа" in n and "узкий" not in n:
                return est_from_1rm(bench, reps)
            if "жим штанги на наклонной" in n or ("жим гантелей" in n and "наклон" in n):
                base = est_from_1rm(bench, reps)
                return int(base * 0.85) if base else None
            if "сведение рук" in n or "кроссовер" in n:
                base = est_from_1rm(bench, reps)
                return int(base * 0.55) if base else 45

            # трицепс
            if "узкий жим" in n:
                return est_from_1rm(cgbp or bench, reps) or (est_from_1rm(bench, reps) if bench else None)
            if "французский жим" in n:
                base = est_from_1rm(cgbp or bench, reps)
                return int(base * 0.55) if base else 30
            if "разгибания на трицепс" in n or ("трицепс" in n and "разгиб" in n):
                base = est_from_1rm(cgbp or bench, reps)
                return int(base * 0.50) if base else 25

            # ноги
            if "присед" in n:
                return est_from_1rm(squat, reps)
            if "жим ногами" in n:
                base = est_from_1rm(squat, reps)
                return int(base * 2.2) if base else 140
            if "сгибания ног" in n:
                base = est_from_1rm(squat, reps)
                return int(base * 0.55) if base else 35
            if "икр" in n or "носки" in n:
                base = est_from_1rm(squat, reps)
                return int(base * 0.9) if base else 80

            # спина
            if "становая" in n:
                return est_from_1rm(deadl, reps)
            if "тяга штанги в наклоне" in n:
                base = est_from_1rm(deadl, reps)
                return int(base * 0.6) if base else 60
            if "горизонтального блока" in n or "вертикального блока" in n:
                base = est_from_1rm(deadl, reps)
                return int(base * 0.5) if base else 60
            if "подтягиван" in n:
                bw = user.get("Вес") or anketa.get("Вес") or 70
                return int(_to_int(bw) or 70) + 10

            # плечи
            if "жим штанги стоя" in n or "армейский жим" in n or "жим стоя" in n:
                return est_from_1rm(ohp, reps)
            if "мах" in n:
                base = est_from_1rm(ohp, reps)
                return int(base * 0.25) if base else 8

            # бицепс
            if "бицепс" in n and "молотков" not in n:
                base = est_from_1rm(bench, reps)
                return int(base * 0.45) if base else 35
            if "молотков" in n:
                base = est_from_1rm(bench, reps)
                return int(base * 0.25) if base else 16

            # пресс
            if "скручивания" in n or "подъем ног" in n:
                return 0

            return None

        def adjust_weight(ex_name: str, target_reps: int, base_weight: Optional[int]) -> int:
            if base_weight is None:
                base_weight = estimate_base_weight(ex_name, target_reps) or 0
            w_last, t_last, a_last = last_weight_and_delta(ex_name)
            w = int(base_weight)
            if a_last is None or t_last is None or w_last is None:
                return max(0, w)
            diff = int(a_last) - int(t_last)
            if diff <= -2: w = int(round(w_last * 0.93))
            elif diff == -1: w = int(round(w_last * 0.97))
            elif diff == 0:  w = int(round(w_last))
            elif diff == 1:  w = int(round(w_last * 1.03))
            else:            w = int(round(w_last * 1.06))
            return max(0, w)

        def scheme_for_pair(pair: Tuple[str,str]) -> List[Tuple[str, List[int]]]:
            if pair == ("chest","tris"):
                used_dumb_incline = any("жим гантелей на наклонной" in _norm_name(r.get("упражнение","")) for r in history)
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
                    ("Приседания со штангой",            [8, 8, 7, 6]),
                    ("Жим ногами в тренажере",           [12, 11, 10]),
                    ("Сгибания ног лёжа в тренажере",    [12, 12, 10]),
                    ("Подъемы на носки стоя в тренажере",[15, 13, 12]),
                    ("Жим штанги стоя",                  [8, 8, 7, 6]),
                    ("Махи гантелями в стороны",         [12, 10, 10]),
                    ("Скручивания на канате",            [15, 15]),
                ]
            used_vert = any("тяга вертикального блока" in _norm_name(r.get("упражнение","")) for r in history)
            lat = "Тяга горизонтального блока" if used_vert else "Тяга вертикального блока"
            return [
                ("Становая тяга",                 [5, 5, 5, 5]),
                ("Тяга штанги в наклоне",        [8, 8, 7]),
                (lat,                             [10, 10, 9]),
                ("Подтягивания с весом",          [8, 8, 6]),
                ("Подъем штанги на бицепс",      [8, 8, 8]),
                ("Молотковые сгибания гантелей", [10, 9, 8]),
                ("Скручивания на канате",        [15, 15]),
            ]

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

    # ---------- mode: YOGA / PILATES ----------
    # ЛОГИКА:
    # - Храним те же поля (Вес=0). «Количество повторений» = длительность удержания/сета в секундах (или повторы).
    # - Прогрессия: если на прошлой сессии по позе/упражнению «выполненные_повторения» >= «целевые_повторения» + 5с,
    #   увеличиваем целевую длительность на 5–10%. Если меньше на ≥5с — уменьшаем на 5–10%.
    # - Ротация последовательностей, чтобы чередовать стимулы.

    # Базовые последовательности:
    SEQS_YOGA = [
        # Силовая хатха/виньяса акцент
        [
            ("Приветствие солнцу A (виньяса)", "sec", 60),
            ("Планка на предплечьях", "sec", 40),
            ("Собака мордой вниз", "sec", 45),
            ("Воин II (левая)", "sec", 35),
            ("Воин II (правая)", "sec", 35),
            ("Треугольник (левая)", "sec", 30),
            ("Треугольник (правая)", "sec", 30),
            ("Лодка (на корпус)", "sec", 35),
            ("Поза голубя (левая)", "sec", 40),
            ("Поза голубя (правая)", "sec", 40),
            ("Шавасана", "sec", 90),
        ],
        # Баланс/мобилити
        [
            ("Приветствие солнцу B (виньяса)", "sec", 60),
            ("Планка прямая", "sec", 40),
            ("Собака мордой вверх", "sec", 30),
            ("Дерево (левая)", "sec", 30),
            ("Дерево (правая)", "sec", 30),
            ("Воин I (левая)", "sec", 35),
            ("Воин I (правая)", "sec", 35),
            ("Поза лодки (вариация)", "sec", 35),
            ("Повороты сидя (левая)", "sec", 30),
            ("Повороты сидя (правая)", "sec", 30),
            ("Шавасана", "sec", 90),
        ],
    ]

    SEQS_PILATES = [
        # Мат-пилатес — базовый кор и стабилизация
        [
            ("Часы (дыхание + центрирование)", "sec", 45),
            ("Hundred (сотня)", "sec", 60),
            ("Roll-up (скрутка)", "reps", 10),
            ("Single Leg Stretch", "reps", 12),
            ("Double Leg Stretch", "reps", 10),
            ("Side Kicks (левая)", "reps", 12),
            ("Side Kicks (правая)", "reps", 12),
            ("Swimming (плавание)", "sec", 45),
            ("Shoulder Bridge (полумост)", "reps", 12),
            ("Spine Stretch Forward", "sec", 40),
        ],
        # Мат-пилатес — баланс/ягодичные/спина
        [
            ("Hundred (сотня) — вариация", "sec", 60),
            ("Half Roll Back", "reps", 10),
            ("Single Straight Leg Stretch", "reps", 12),
            ("Criss-Cross", "reps", 16),
            ("Leg Circles (левая)", "reps", 10),
            ("Leg Circles (правая)", "reps", 10),
            ("Swimming (плавание)", "sec", 50),
            ("Shoulder Bridge (вариация)", "reps", 12),
            ("Side Bend (боковая планка, левая)", "sec", 30),
            ("Side Bend (боковая планка, правая)", "sec", 30),
        ],
    ]

    # Выбор последовательности — крутим их по датам
    def _pick_seq(seq_bank: List[List[Tuple[str, str, int]]]) -> List[Tuple[str, str, int]]:
        if not history:
            return seq_bank[0]
        # Найдём последнюю дату и номер последовательности по числу упражнений (грубая метка)
        by_date: Dict[str, int] = {}
        for r in history:
            d = r.get("дата")
            if not d: continue
            by_date.setdefault(d, 0)
            by_date[d] += 1
        last_date = max(by_date.keys(), key=_to_date)
        # просто чередуем 0/1
        idx = 1 if sum(1 for _ in history if _.get("дата")==last_date) % 2 == 0 else 0
        return seq_bank[idx]

    if mode in ("yoga", "pilates"):
        seq_bank = SEQS_YOGA if mode == "yoga" else SEQS_PILATES
        seq = _pick_seq(seq_bank)

        # адаптация таргетов по истории: для каждой позы/упражнения смотрим последний сет
        def last_target_and_actual(name: str) -> Tuple[Optional[int], Optional[int]]:
            recs = _last_records_for_ex(name)
            if not recs: return None, None
            r = recs[-1]
            return _to_int(r.get("целевые_повторения")), _to_int(r.get("выполненные_повторения"))

        def adjust_duration(name: str, base: int) -> int:
            t_last, a_last = last_target_and_actual(name)
            t = int(base)
            if t_last is None or a_last is None:
                return t
            diff = a_last - t_last
            # Шаги в секундах/повторах, ограничим коридор ±10%
            if diff >= 5:
                t = int(round(t_last * 1.08))
            elif diff <= -5:
                t = int(round(t_last * 0.92))
            else:
                t = int(t_last)
            # минимумы
            if t < 15: t = 15
            return t

        plan: List[Dict] = []
        set_no = 1
        for name, unit, base_val in seq:
            # переведём всё к «Количество повторений» (секунды/повторы), Вес=0
            target = adjust_duration(name, base_val)
            # Для некоторых элементов логично делать 2 сета (кор/баланс), для растяжек — 1 сет
            sets = 2 if (("планк" in _norm_name(name)) or ("hundred" in _norm_name(name)) or ("лодк" in _norm_name(name)) or ("bridge" in _norm_name(name)) or ("side" in _norm_name(name))) else 1
            for i in range(sets):
                plan.append({
                    "Название упражнения": name,
                    "Номер подхода": set_no,
                    "Вес": 0,
                    "Количество повторений": int(target),
                })
                set_no += 1
        return plan

    # fallback (на случай неизвестного режима)
    return []
# --- /Local planner -----------------------------------------------------------