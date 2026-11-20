# ProjectPulse

Локальный цифровой двойник программного проекта (Python 3.11+, только stdlib; для тестов — pytest + hypothesis).
Нужен установленный `git`. Интернет требуется только для `fetch` (клонирование).

## Быстрый старт
```bash
python -m projectpulse demo                      # создаёт два демо-репозитория (healthy / problem)
python -m projectpulse index /tmp/pp_demo/healthy --name healthy
python -m projectpulse index /tmp/pp_demo/problem --name problem
python -m projectpulse analyze problem           # метрики + правила + индекс здоровья
python -m projectpulse compare healthy problem   # 5 ключевых показателей
python -m projectpulse report problem out.html   # Сводка/Риски/Динамика/Граф/Рекомендации
python -m projectpulse research healthy problem  # мини-исследование (Спирмен/Пирсон)
python -m projectpulse bench /tmp/pp_demo/problem  # замеры + cProfile + 2 оптимизации
python -m projectpulse ui                        # Tkinter UI
```
Свои репозитории: заполните `repos.json`, затем `python -m projectpulse fetch`
(клонирует в `~/.projectpulse/repos/<name>`), потом `index` по этим путям.
Повторный `index` по тому же репозиторию — инкрементальный; `--rebuild` или кнопка в UI — с нуля.

## Тесты
`pytest -q` — 49 тестов (unit + интеграционные + property-based на hypothesis).
Мутационное тестирование (по желанию): `mutmut run --paths-to-mutate projectpulse/stats.py`.

## Структура
`gitio` (git CLI) → `indexer` (полный/инкрементальный) → `db` (SQLite) → `metrics`/`rules` (плагины) → `analysis` → `ui`/`report`.
Подробности — `docs/architecture.md`.
