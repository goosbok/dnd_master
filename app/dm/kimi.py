import logging
import os
import time

import httpx
from pydantic import ValidationError

from app.dm.base import DungeonMaster
from app.dm.scripted import ScriptedDM
from app.models import DmContext, DmResponse, Intent
from app.scenario import Scene

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.kimi.ai/coding/v1"
DEFAULT_MODEL = "kimi-for-coding"

NARRATE_SYSTEM_PROMPT = """Ты — Мастер подземелий (DM) для одиночного ван-шота D&D 5e. Игра идёт на русском языке.

Главное правило: ты НИКОГДА не определяешь исход действий. Все броски кубов, проверки навыков и бой уже посчитаны движком — они переданы тебе в контексте как свершившиеся факты. Твоя задача — красиво и атмосферно озвучить их от лица мастера и оживить NPC.

Как писать narration:
- Отвечай ТОЛЬКО на действие игрока из поля player_action контекста: его результат и ближайшая реакция мира. Поле recent_turns — это прошлое, не отвечай на него. НЕ пересказывай обстановку сцены заново — игрок её уже видел.
- 2–4 предложения. Обращайся к игроку на «ты».
- Не выдумывай чисел, имён и фактов, которых нет в контексте (размер награды, названия мест, сроки). Если контекст молчит — обойдись без конкретики.

Как писать npc_lines:
- Только если NPC действительно произносит что-то НОВОЕ, чего нет в narration. Не дублируй и не пересказывай narration репликами.
- Не больше одной реплики на NPC. Если говорить нечего — пустой список.

Знакомства:
- У каждого NPC в контексте есть флаг known. Если known=false, игрок ЕЩЁ НЕ ЗНАЕТ его имени: не называй NPC по имени ни в narration, ни в репликах других персонажей — описывай его через label («коренастый мужчина у окна»).
- Когда NPC представляется сам, отвечает на вопрос «как тебя зовут» или игрок иным образом узнаёт имя — добавь state_change {"type": "meet_npc", "npc_id": "..."}. После этого флаг станет true и именем можно пользоваться.

Отвечай СТРОГО одним JSON-объектом без markdown-обёрток:
{
  "narration": "строка — художественное описание результата действия игрока (2–4 предложения)",
  "npc_lines": [{"npc_id": "id персонажа из сцены", "line": "реплика"}],
  "state_changes": [{"type": "grant_fact", "fact": "..."}],
  "scene_trigger": null
}

Допустимые типы state_changes (всё остальное движок отбросит):
- {"type": "grant_fact", "fact": "короткий атомарный факт"} — игрок узнал/получил нечто важное
- {"type": "remove_fact", "fact": "..."} — факт больше не актуален
- {"type": "meet_npc", "npc_id": "..."} — игрок познакомился с NPC и узнал его имя
- {"type": "damage", "target": "player", "amount": 5} — урон вне бросков движка (ловушка, падение)
- {"type": "heal", "target": "player", "amount": 5}
- {"type": "add_item", "item": "..."} / {"type": "remove_item", "item": "..."}
- {"type": "set_npc_disposition", "npc_id": "...", "disposition": "hostile|wary|neutral|friendly"}

scene_trigger — только один из триггеров перехода, перечисленных в контексте сцены (exits), и только если по сюжету сцена действительно завершена. Иначе — null.

Не выдумывай исходы, противоречащие переданным результатам бросков. Учитывай факты из памяти и саммари прошлых сцен."""

CLASSIFY_SYSTEM_PROMPT = """Ты классифицируешь действие игрока в ван-шоте D&D 5e. Ответь СТРОГО одним JSON-объектом:
{"kind": "free" | "check" | "attack", "skill": null | "id навыка"}
- "attack" — игрок явно атакует кого-либо.
- "check" — действие требует проверки навыка из списка проверок текущей сцены; укажи id навыка из этого списка.
- "free" — обычное действие или разговор без проверки."""

QUESTION_SYSTEM_PROMPT = """Ты — Мастер подземелий, и игрок задаёт тебе вопрос ВНЕ РОЛИ (вопрос мастеру, а не действие персонажа). Игра идёт на русском.

- Отвечай кратко (1–3 предложения), по существу вопроса, опираясь на контекст: сцену, факты, лист персонажа, последние ходы.
- Это может быть вопрос о правилах, состоянии персонажа, мире или уточнение происходящего.
- НИЧЕГО не меняй в игре: это разговор, не ход. Никаких бросков и событий.
- Не раскрывай секреты NPC и не подглядывай в будущие сцены: отвечай только тем, что персонаж уже знает или может знать. Секреты из контекста — только чтобы НЕ проболтаться.
- Отвечай просто текстом, без JSON."""


class KimiDM(DungeonMaster):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ["MOONSHOT_API_KEY"]
        self.base_url = (base_url or os.getenv("MOONSHOT_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.model = model or os.getenv("MOONSHOT_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self._fallback = ScriptedDM()

    def _chat(self, system: str, user: str, json_mode: bool = True) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 4096,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise
                logger.warning("KimiDM._chat attempt %d failed: %r", attempt + 1, exc)
                time.sleep(1 + attempt * 2)
        raise last_error

    def narrate(self, ctx: DmContext) -> DmResponse:
        try:
            content = self._chat(NARRATE_SYSTEM_PROMPT, ctx.model_dump_json())
            return DmResponse.model_validate_json(content)
        except (httpx.HTTPError, KeyError, ValueError, ValidationError) as exc:
            logger.warning("KimiDM.narrate failed: %r", exc)
            return DmResponse(
                narration=(
                    "Мастер на мгновение замолкает, шурша заметками. "
                    "Действие засчитано движком, но подробности пока остаются за кадром."
                )
            )

    def classify_intent(self, text: str, scene: Scene) -> Intent:
        payload = {
            "player_text": text,
            "checks": [c.model_dump() for c in scene.checks],
            "enemies": [e.name for e in scene.enemies if e.hp > 0],
        }
        try:
            content = self._chat(CLASSIFY_SYSTEM_PROMPT, str(payload))
            return Intent.model_validate_json(content)
        except (httpx.HTTPError, KeyError, ValueError, ValidationError) as exc:
            logger.warning("KimiDM.classify_intent failed: %r", exc)
            return self._fallback.classify_intent(text, scene)

    def answer_question(self, ctx: DmContext) -> str:
        try:
            return self._chat(QUESTION_SYSTEM_PROMPT, ctx.model_dump_json(), json_mode=False)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("KimiDM.answer_question failed: %r", exc)
            return self._fallback.answer_question(ctx)
