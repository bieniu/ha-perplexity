"""AI Task integration for Perplexity."""

from homeassistant.components import ai_task, conversation
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.json import json_dumps
from homeassistant.util.json import JSON_DECODE_EXCEPTIONS, json_loads

from perplexity import AsyncPerplexity, PerplexityError
from perplexity.types import DecisionAnswer

from . import PerplexityConfigEntry
from .const import DOMAIN, SUBENTRY_TYPE_AI_TASK, SUBENTRY_TYPE_AI_TASK_EVALUATE
from .entity import PerplexityEntity, _prepare_files_for_prompt


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PerplexityConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI Task entities."""
    for subentry in config_entry.get_subentries_of_type(SUBENTRY_TYPE_AI_TASK):
        async_add_entities(
            [PerplexityAITaskEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )
    for subentry in config_entry.get_subentries_of_type(SUBENTRY_TYPE_AI_TASK_EVALUATE):
        async_add_entities(
            [PerplexityEvaluateEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


def _invalid_response(entry_title: str, error: str) -> HomeAssistantError:
    """Build the translated error for an evaluation response HA cannot use."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="invalid_evaluation_response",
        translation_placeholders={"entry": entry_title, "error": error},
    )


def _convert_answers(
    questions: dict[str, ai_task.EvaluationQuestion],
    answers: dict[str, DecisionAnswer],
    entry_title: str,
) -> dict[str, ai_task.EvaluationAnswer]:
    """Convert Decisions API answers to the HA answer types."""
    if unexpected := set(answers) - set(questions):
        raise _invalid_response(
            entry_title, f"unexpected answers: {', '.join(sorted(unexpected))}"
        )

    result: dict[str, ai_task.EvaluationAnswer] = {}
    for question_id, question in questions.items():
        if (answer := answers.get(question_id)) is None:
            raise _invalid_response(entry_title, f"missing answer for {question_id}")
        # The SDK does not validate responses strictly, so a malformed answer may
        # be a model of the wrong variant with the fields of this one missing
        try:
            result[question_id] = _convert_answer(question_id, question, answer)
        except (AttributeError, KeyError, TypeError) as err:
            raise _invalid_response(
                entry_title, f"malformed answer for {question_id}"
            ) from err
        except ValueError as err:
            raise _invalid_response(entry_title, str(err)) from err

    return result


def _convert_answer(
    question_id: str, question: ai_task.EvaluationQuestion, answer: DecisionAnswer
) -> ai_task.EvaluationAnswer:
    """Convert one answer, raising ValueError when it does not fit the question."""
    if question["type"] == "noul" and answer.type == "noul":
        return ai_task.NoulAnswer(noul=answer.noul)
    if question["type"] == "choice" and answer.type == "choice":
        if answer.choice not in question["criteria"] or set(
            answer.probabilities
        ) != set(question["criteria"]):
            raise ValueError(f"invalid choice for {question_id}")
        return ai_task.ChoiceAnswer(
            choice=answer.choice, probabilities=dict(answer.probabilities)
        )
    if question["type"] == "score" and answer.type == "score":
        # HA wants probabilities as a list ordered by level index, the API
        # keys them by the index as a string
        levels = [str(index) for index in range(len(question["criteria"]))]
        if set(answer.probabilities) != set(levels):
            raise ValueError(f"invalid score levels for {question_id}")
        return ai_task.ScoreAnswer(
            score=answer.score,
            probabilities=[answer.probabilities[level] for level in levels],
        )
    raise ValueError(f"answer type {answer.type} does not match question {question_id}")


class PerplexityAITaskEntity(
    ai_task.AITaskEntity,
    PerplexityEntity,
):
    """Perplexity AI Task entity."""

    _attr_name = None
    _attr_supported_features = (
        ai_task.AITaskEntityFeature.GENERATE_DATA
        | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
    )

    async def _async_generate_data(
        self,
        task: ai_task.GenDataTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenDataTaskResult:
        """Handle a generate data task."""
        await self._async_handle_chat_log(chat_log, task.name, task.structure)

        last_content = chat_log.content[-1]
        if not isinstance(last_content, conversation.AssistantContent):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="no_assistant_response",
            )

        text = last_content.content or ""

        if not task.structure:
            return ai_task.GenDataTaskResult(
                conversation_id=chat_log.conversation_id,
                data=text,
            )
        try:
            data = json_loads(text)
        except JSON_DECODE_EXCEPTIONS as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="structured_response_error",
                translation_placeholders={"error": str(err)},
            ) from err

        return ai_task.GenDataTaskResult(
            conversation_id=chat_log.conversation_id,
            data=data,
        )


class PerplexityEvaluateEntity(
    ai_task.AITaskEntity,
    PerplexityEntity,
):
    """Perplexity AI task evaluation entity backed by the Decisions API."""

    _attr_name = None
    _attr_supported_features = (
        ai_task.AITaskEntityFeature.EVALUATE
        | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
    )

    async def _async_evaluate(
        self, task: ai_task.EvaluationTask
    ) -> ai_task.EvaluationTaskResult:
        """Handle an evaluation task."""
        state = task.state
        # The API accepts only text, an object or an array as state
        if not isinstance(state, str | dict | list):
            state = json_dumps(state)

        if task.attachments:
            files = await self.hass.async_add_executor_job(
                _prepare_files_for_prompt,
                [
                    (attachment.path, attachment.mime_type)
                    for attachment in task.attachments
                ],
            )
            # The Decisions API takes OpenAI-style image parts, not Agent API ones
            images = [
                {"type": "image_url", "image_url": {"url": file["image_url"]}}
                for file in files
            ]
            if task.state is None:
                state = images
            elif isinstance(state, list):
                state = [*state, *images]
            else:
                state = [state, *images]

        client: AsyncPerplexity = self.entry.runtime_data
        try:
            response = await client.decisions.create(
                model=self.model, questions=task.questions, state=state
            )
        except PerplexityError as err:
            raise self._translate_api_error(err) from err

        return ai_task.EvaluationTaskResult(
            answers=_convert_answers(task.questions, response.answers, self.entry.title)
        )
