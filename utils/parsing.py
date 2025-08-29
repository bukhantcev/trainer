import re

def parse_profile_update(text: str) -> dict:
    parts = re.split(r'[,\n]+', text)
    result = {}

    patterns = {
        'name': re.compile(r'имя\s+(.+)', re.I),
        'age': re.compile(r'возраст\s+(\d+)', re.I),
        'height': re.compile(r'рост\s+(\d+)', re.I),
        'weight': re.compile(r'вес\s+(\d+)', re.I),
        'goal': re.compile(r'цель\s+(.+)', re.I),
        'experience': re.compile(r'опыт\s+(.+)', re.I),
        'gender': re.compile(r'пол\s+(.+)', re.I),
    }

    goal_map = {'сила': 'сила','масса':'масса','сушка':'сушка','общая форма':'общая форма','общая':'общая форма'}
    exp_map = {'новичок':'новичок','средний':'средний','продвинутый':'продвинутый'}
    gender_map = {
        'м':'мужской','муж':'мужской','мужчина':'мужской','мужской':'мужской',
        'ж':'женский','жен':'женский','женщина':'женский','женский':'женский',
    }

    for part in parts:
        part = part.strip()
        for key, pattern in patterns.items():
            m = pattern.match(part)
            if m:
                val = m.group(1).strip()
                if key == 'goal':
                    lv = val.lower()
                    val = next((v for k,v in goal_map.items() if k in lv), lv)
                elif key == 'experience':
                    lv = val.lower()
                    val = next((v for k,v in exp_map.items() if k in lv), lv)
                elif key == 'gender':
                    lv = val.lower()
                    val = next((v for k,v in gender_map.items() if k == lv or k in lv), lv)
                elif key in ('age','height','weight'):
                    try: val = int(val)
                    except: continue
                else:
                    val = val.strip()
                result[key] = val
                break
    return result