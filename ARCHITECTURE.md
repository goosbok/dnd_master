# Архитектура MVP — AI-мастер для ван-шотов D&D 5e

## Цель MVP

Один игрок выбирает готовый ван-шот и играет его через веб-чат. Роль мастера выполняет LLM (Kimi / Moonshot), но все механики (кубы, проверки, бой, хиты) считает код. Сценарий — данные (JSON), написанные человеком.

## Главные принципы

1. **Код отвечает за правду, LLM — за слова.** LLM никогда не определяет исход действия. Она получает свершившийся факт («бросок 17, успех») и красиво его подаёт. Все `state_changes` от LLM валидируются движком; невалидные отбрасываются.
2. **Глубокие модули.** Маленький интерфейс — много поведения внутри. Клиент знает три метода оркестратора, и всё.
3. **Швы только там, где реально что-то меняется.** LLM (модель / фейк), случайность (RNG / seeded), сценарий (данные / код). У хранилища один адаптер — абстракция минимальная.

## Модули

### Orchestrator (оркестратор) — ядро, самый глубокий модуль

```python
class Orchestrator:
    def start_session(self, scenario_id: str, character: Character) -> SessionView
    def submit_action(self, session_id: str, text: str) -> TurnResult
    def get_state(self, session_id: str) -> SessionView
```

Цикл одного хода внутри `submit_action`:

1. Классификация намерения (через LLM, дешёвый вызов): свободное действие / требует проверки навыка / атака.
2. Если нужна проверка — вызов RulesEngine (детерминированно).
3. Обновление Scenario (триггеры перехода между сценами) и Memory (новые факты).
4. Сборка `DmContext` → вызов DungeonMaster.narrate.
5. Валидация `DmResponse.state_changes` через RulesEngine, применение валидных.
6. Переход сцены: валидный `scene_trigger` от LLM **или** автоматически — если записанный за ход факт (от проверки, боя или `state_changes`) совпадает с триггером одного из выходов сцены. LLM может ускорить переход, но не блокирует его молчанием.
7. Возврат `TurnResult` клиенту: текст для игрока, броски кубов, дельта состояния.

### RulesEngine (движок правил) — чистые функции

```python
def ability_check(char: Character, skill: Skill, dc: int, rng: Rng) -> CheckResult
def attack(attacker: Character, target: Character, rng: Rng) -> AttackResult
def start_combat(party: list[Character], enemies: list[Character], rng: Rng) -> CombatState
def combat_turn(combat: CombatState, action: CombatAction, rng: Rng) -> CombatState
```

- Никаких side effects: функции возвращают результаты, состояние применяет оркестратор.
- `rng` — параметр (шов): в тестах seeded RNG, броски воспроизводимы.
- Бой упрощённый: инициатива, бросок атаки vs AC, урон, хиты. Без сетки и позиционирования.
- Данные SRD (заклинания, монстры, классы) — статичный JSON в репозитории (`data/srd/`), не API-зависимость.

### Scenario (сценарный рантайм)

```python
class Scenario:
    @classmethod
    def load(cls, path: Path) -> Scenario
    def current_scene(self) -> Scene
    def advance(self, trigger: str) -> Scene | None
    def available_exits(self) -> list[Exit]
```

Сценарий — JSON-файл, шов «разработчики / контент». Формат:

```json
{
  "id": "curse-of-the-salted-goat",
  "title": "Проклятие солёной козы",
  "premise": "Краткий синопсис для DM-контекста",
  "scenes": [
    {
      "id": "tavern",
      "goal": "Получить контракт от старосты",
      "on_enter": "Шторм бьёт в ставни таверны...",
      "npcs": [{"id": "mayor", "name": "Староста", "personality": "...", "secrets": ["..."]}],
      "exits": [{"to": "docks", "trigger": "has_contract"}],
      "checks": [{"skill": "persuasion", "dc": 12, "grants_fact": "has_contract"}],
      "enemies": [{"id": "thug", "name": "Громила", "hp": 11, "ac": 12, "attack_bonus": 4, "damage": "1d6+2"}],
      "combat_reward_fact": "warehouse_cleared"
    }
  ]
}
```

Поля `enemies` и `combat_reward_fact` необязательны — сцена без них мирная. Победа над всеми врагами сцены выдаёт `combat_reward_fact`, который может быть триггером перехода.

Хауc-рулы MVP: натуральные 20 и 1 — авто-успех и авто-провал проверки; бой в игровом цикле атомарный (игрок атакует первого живого врага, выживший враг отвечает одной контратакой), поочерёдный `CombatState` с инициативой реализован в правилах, но в веб-цикле MVP не задействован.

### DungeonMaster (LLM) — настоящий шов, два адаптера

```python
class DungeonMaster(Protocol):
    def narrate(self, ctx: DmContext) -> DmResponse
    def classify_intent(self, text: str, scene: Scene) -> Intent
    def answer_question(self, ctx: DmContext) -> str
```

`answer_question` — канал «вопрос мастеру» (out-of-character): отвечает текстом, без бросков, `state_changes` и трат хода; промпт запрещает раскрывать секреты NPC и будущие сцены.

- **KimiDM** — Kimi Code API, OpenAI-совместимый клиент (`base_url` и `model` из env: `MOONSHOT_API_KEY`, `MOONSHOT_BASE_URL` (дефолт `https://api.kimi.ai/coding/v1`), `MOONSHOT_MODEL` (дефолт `kimi-for-coding`); для ключа Kimi Platform (pay-as-you-go) дефолты — `https://api.moonshot.ai/v1`). Ответы — строгий JSON (`response_format={"type": "json_object"}` + схема в системном промпте); `max_tokens` с запасом — модель reasoning-токены тратит из того же бюджета.
- **ScriptedDM** — детерминированный фейк для тестов и разработки без ключа.

`DmContext`: текущая сцена целиком, **текущее действие игрока (`player_action`)**, факты из Memory, исходы бросков этого хода, последние 3 хода диалога (`recent_turns` — только фон, не объект ответа). Никогда — вся история чата.

`DmResponse` (JSON):

```json
{
  "narration": "Дверь поддаётся беззвучно...",
  "npc_lines": [{"npc_id": "mayor", "line": "..."}],
  "state_changes": [{"type": "grant_fact", "fact": "has_contract"}],
  "scene_trigger": null
}
```

Допустимые типы `state_changes`: `grant_fact`, `remove_fact`, `damage`, `heal`, `add_item`, `remove_item`, `set_npc_disposition`. Всё остальное движок отбрасывает.

### Memory (память)

```python
class Memory:
    def record(self, fact: Fact) -> None
    def recall(self) -> list[Fact]
    def summarize_scene(self, scene_id: str, summary: str) -> None
```

Факты атомарны («у игрока ключ от башни»). Завершённые сцены сворачиваются в однострочные саммари. Служебные факты с префиксами (`met_npc:`, `npc_disposition:`) клиенту не показываются.

### Знакомства с NPC — уровень движка

Игрок не знает имён NPC, пока не познакомится. У NPC в сценарии есть `label` («Коренастый мужчина у окна») — то, что видит незнакомец. Движок отдаёт **разные представления сцены**: клиенту — `label` вместо имени и никаких `secrets`/`personality`; LLM — полные данные + флаг `known` с инструкцией не называть имя, пока `known=false`. Знакомство оформляется `state_change {"type": "meet_npc", "npc_id": ...}` → движок записывает факт `met_npc:<id>`, после чего имя открывается и клиенту, и модели. Знакомство живёт в памяти сессии, поэтому действует и в последующих сценах с тем же NPC.

### Хранилище

SQLite, тонкий репозиторий: сессии, ходы, факты. Один адаптер, без преждевременной абстракции.

### API-слой (FastAPI)

- `POST /sessions` — начать сессию (scenario_id + персонаж)
- `POST /sessions/{id}/actions` — ход игрока (текст) → `TurnResult`
- `POST /sessions/{id}/questions` — вопрос мастеру вне роли → `{"answer": ...}`; не тратит ход, не меняет мир
- `GET /sessions/{id}` — состояние (лист персонажа, сцена, лог)
- `GET /scenarios` — список доступных ван-шотов

Фронт в MVP: один статичный HTML с fetch — чат + лист персонажа. Отдаётся FastAPI напрямую.

## Структура каталогов

```
dnd/
├── ARCHITECTURE.md
├── pyproject.toml
├── app/
│   ├── main.py              # FastAPI, роуты, DI
│   ├── orchestrator.py      # игровой цикл
│   ├── rules/               # движок правил (чистые функции)
│   │   ├── dice.py          # RNG-шов, броски d20 и пр.
│   │   ├── checks.py
│   │   └── combat.py
│   ├── scenario.py          # загрузка и рантайм сценариев
│   ├── dm/
│   │   ├── base.py          # Protocol DungeonMaster, DmContext, DmResponse
│   │   ├── kimi.py          # адаптер Moonshot API
│   │   └── scripted.py      # детерминированный фейк
│   ├── memory.py
│   ├── models.py            # Character, Session, TurnResult, pydantic-схемы
│   ├── repo.py              # SQLite
│   └── static/index.html    # минимальный чат-UI
├── scenarios/
│   └── curse_of_the_salted_goat.json   # демо-ван-шот
├── data/srd/                # базовые данные SRD (классы, навыки)
└── tests/
    ├── test_rules.py        # seeded RNG
    ├── test_scenario.py
    └── test_orchestrator.py # полный ход через ScriptedDM
```

## Тестовая стратегия

- `rules`: юнит-тесты через seeded RNG — граничные случаи бросков и боя.
- `scenario`: загрузка демо-ван-шота, переходы по триггерам.
- `orchestrator`: весь игровой цикл через ScriptedDM — ни одного вызова нейронки.
- `kimi.py`: без автотестов против живого API; проверяется руками.

## Что НЕ входит в MVP

- Мультиплеер (но интерфейсы уже принимают `player_id`-совместимые идентификаторы — шов на будущее).
- Тактический бой на сетке.
- Генерация историй на лету (фаза 2 продукта).
- Голос, картинки, карты.
- Аккаунты и авторизация — одна сессия = одна ссылка.
