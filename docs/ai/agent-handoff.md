> **What this file is.** The briefing I wrote for the coding agent before the
> session started — the assignment terms, the architectural decisions I had
> already made and did not want re-litigated, the hour-by-hour plan, the commit
> sequence, and an explicit list of things *not* to build with the reason for
> each. Committed verbatim (in Russian, the language I work in) because the
> assignment asks for the actual instruction files rather than a summary. It is
> a historical document: where the build later diverged from it — most
> importantly the relevance threshold — the divergence and its measured reason
> are recorded in [AI_NOTES.md](../../AI_NOTES.md), SPEC.md and ADR-002.

---

# Handoff: Taxdome Take-Home — Recipe Q&A Service

Ты — агент-исполнитель. Это полный контекст задачи; предыдущей переписки у тебя нет, всё нужное — здесь. Работаешь в новом пустом каталоге проекта. Пользователь — Иван Манько, Senior Python Backend / AI Engineer. Общение с ним — по-русски, **все артефакты репозитория — на английском** (код, коммиты, SPEC, ADR, README, комментарии).

---

## 1. Что это и как это оценивают

Тестовое задание на позицию AI Automation Engineer в Taxdome. Бюджет: 6–8 часов сфокусированной работы. Сдача: приватный GitHub-репозиторий (доступ ревьюерам Artem Kashuta и Anton Snitavets) + живой задеплоенный URL.

**Ключевая фраза ТЗ:** «How you design, decide, specify, verify, and ship is more important to us than the code». Оценивают процесс, код — повод на него посмотреть.

Шесть критериев оценки (каждый — реальный пункт чек-листа ревьюера):

1. **SPEC.md** — превращён ли размытый запрос в проверяемые требования ДО кода.
2. **ADR** — понимание «почему», trade-offs с цифрами, условия пересмотра решения.
3. **Eval-харнесс** — измеряется ли качество LLM-пайплайна автоматически.
4. **Тесты + гранулярная история коммитов** — дисциплина; для части функций тест закоммичен раньше реализации.
5. **Cost & latency** — мышление владельца: цена вопроса, узкие места.
6. **Деплой** — работает end-to-end у них; IaC, секреты, воспроизводимость, идемпотентность.

Важные оговорки ТЗ:
- «Extra features get credit only on a core that is complete, deployed, and evaluated» — фичи сверх ядра не компенсируют дыры в ядре.
- «Cut scope consciously and record what you cut» — честно названный пропуск это плюс.
- «Hidden hardcoded behavior is the only incorrect option» — любая эвристика/допущение фиксируется в SPEC.
- «If you stop before production grade, write this in the README. Write what is necessary to close the gap.»
- UI не оценивается по внешнему виду, только по работоспособности.
- После сдачи будет живая защита 1–2 ADR + новое требование вживую. Всё в репо должно быть защищаемо построчно.

## 2. Функциональные требования (из ТЗ, сжато)

**Корпус:** 40–60 рецептов из Wikibooks Cookbook (https://en.wikibooks.org/wiki/Cookbook) через MediaWiki API. Несколько категорий, разнообразие: разные кухни, пересекающиеся блюда (нужны минимум 2 рецепта одного блюда с расхождениями), разная структурированность. Скрипт загрузки коммитится; корпус должен пересобираться из одного скрипта.

**`POST /ask`** — вопрос на естественном языке → структурированный JSON (схема ниже). Ответы ТОЛЬКО из корпуса (не из памяти модели). Соблюдение ограничений вопроса (время, диета, ингредиент). Отказы — машиночитаемые (флаг + enum, не вежливый текст в answer).

**UI:** одна страница, TypeScript обязателен. Вопрос → ответ, цитаты, отказы.

**Схема ответа (минимум по ТЗ, наше расширение — recipe_id и request_id):**

```json
{
  "answer": "string | null",
  "citations": [{ "title": "...", "url": "...", "recipe_id": "..." }],
  "refused": false,
  "refusal_reason": "out_of_corpus | out_of_domain | safety | null",
  "request_id": "..."
}
```

Полная схема определяется в SPEC.md. Pydantic-модель — единственный источник истины: из неё OpenAPI, structured output модели, валидация в eval-харнессе.

**Deliverables (все обязательны):** SPEC.md (до кода), 2–3 ADR, eval-харнесс (12–15 вопросов + автопрогон + проверка контракта), тесты не-LLM логики + гранулярные коммиты, README (Cost & Latency; Deployment; абзац «плохой ответ в проде — как найти причину»), AI usage notes файлами (CLAUDE.md, промпты, заметки что принято/переписано — использование агентов разрешено и рекомендовано, но это тоже артефакт сдачи).

## 3. Архитектурные решения — ПРИНЯТЫ, не пересматривать без согласования с Иваном

| # | Решение | Обоснование (кратко — для ADR развернёшь) |
|---|---|---|
| 1 | Рецепт = одна единица корпуса, без чанкинга | Рецепты 200–400 токенов; резка ломает целостность ингредиенты↔шаги. ADR-001 |
| 2 | Retrieval: BM25 (`rank-bm25`) + локальные эмбеддинги `BAAI/bge-small-en-v1.5`, слияние RRF, поверх — жёсткие метафильтры (время/диета/исключённые ингредиенты). Всё in-memory, индексы строятся при старте из corpus.json | 50 документов; векторная БД — карго-культ: +сервис, +состояние, +способ сломать деплой. Условие пересмотра: >10k документов или обновление корпуса без передеплоя → pgvector. ADR-002 |
| 3 | Порог релевантности ДО вызова LLM: лучший score ниже порога → `refused: true, refusal_reason: "out_of_corpus"`, LLM не вызывается | Дёшево, детерминированно, тестируемо pytest'ом. Отказы стоят $0 |
| 4 | Извлечение ограничений из вопроса — детерминированный парсер (regex + словарь): `max_time`, `diet`, `exclude_ingredients` | Тестируется без LLM; метафильтры работают от него |
| 5 | Safety-гейт до retrieval: словарь триггеров (nut-free, allergy, allergic, safe for, pregnant, raw egg, gluten intolerance...) → ветка safety | Политика: сервис НИКОГДА не подтверждает отсутствие аллергена. Ответ: `refused: true, refusal_reason: "safety"`, citations заполнены, в answer — список ингредиентов + дисклеймер, что открытый корпус не источник данных о безопасности (следовые количества, примеси). ADR-003 |
| 6 | Генерация: ОДИН вызов LLM на вопрос, structured output строго по схеме, в промпте только найденные топ-5 рецептов + инструкция «только из контекста» + право модели вернуть refused | Никаких агентных графов, self-correction циклов, реранкеров — это «unnecessary polish» по ТЗ, умножает cost/latency в 7–20× |
| 7 | LLM-провайдер за тонким адаптером (OpenAI-совместимый интерфейс, base_url/model/key через env) | Провайдер — свободный выбор по ТЗ; адаптер делает его обратимым. Дефолт — дешёвая модель одного вендора; актуальные цены ПРОВЕРИТЬ на сайте вендора, не из памяти. Условия смены модели — в ADR/README |
| 8 | Противоречащие рецепты: если в топе два рецепта одного блюда с расхождениями — ответ называет обе версии с отдельными цитатами, не выбирает молча одну | Явный edge case ТЗ; зафиксировать в SPEC |
| 9 | Сервис stateless: corpus.json + индексы в образе/памяти, никакой БД | Идемпотентный деплой по построению |
| 10 | Фронтенд: Vite + vanilla TypeScript, без фреймворка. Одна форма, fetch('/ask'), три состояния (ответ+цитаты / отказ / ошибка). Статику отдаёт FastAPI — один контейнер, один URL, нет CORS | «We do not grade appearance». Не полировать |
| 11 | Логирование: одна структурированная JSON-строка на запрос: request_id, question, extracted_constraints, retrieved[{id,scores}], threshold_passed, model, tokens, latency_ms{retrieval,llm,total}, refused, refusal_reason, citation_ids. request_id возвращается в заголовке | Это готовый ответ на README-вопрос «плохой ответ в проде — как найти причину» |
| 12 | Стек: Python 3.12, FastAPI, uv, ruff, pytest; Docker multi-stage (сборка фронта → python-образ) | |

## 4. Деплой: Northflank + IaC (указание от компании)

Рекрутер Taxdome явно назвал направление: «Amazon либо Northflank». Выбираем **Northflank**: AWS с Terraform съест 2–3 часа бюджета на ECS/IAM, Northflank даёт git-driven деплой контейнера + IaC-шаблоном + дашборд для ревьюеров. Это решение записать в ADR-004 (альтернатива AWS — честно описать trade-off: полнота контроля vs время; условие пересмотра: требования VPC/приватной сети/managed-инфраструктуры).

Требования, которые деплой обязан закрыть:
- Публичный URL и для UI, и для API (у нас один контейнер — один URL, `/` фронт, `/ask` и `/health` API).
- IaC: файлы деплоя в репозитории, новый деплой из репо без ручных кликов в UI. У Northflank это template-файл (проверь актуальный формат в их документации — не пиши по памяти) + GitHub Actions: тесты → линт → сборка → деплой → smoke по `/health` → прогон evals против прода.
- Секреты: только в environment (Northflank secrets / GitHub Secrets), в репо — `.env.example`.
- Идемпотентность: повторный деплой той же ревизии — no-op (stateless-сервис даёт это бесплатно; проверить и заявить в README).
- Доступ на уровне контейнера: пригласить ревьюеров в Northflank-проект (у них есть роли) ЛИБО дать доступ к логам/статусу. Выбранный вариант записать в README.

⚠️ Образ с torch (sentence-transformers) — 2–3 ГБ, загрузка модели требует ~1–2 ГБ RAM. Взять план Northflank с достаточной памятью (цена не критерий: «we examine practices, not infrastructure costs»). Fallback, если образ неподъёмен: адаптер эмбеддингов уже умеет API-провайдера через env — переключить и записать в ADR-002.

## 5. Шаблон-донор: ~/projects/rag-agent

Готовый pet-проект Ивана. Из него **копировать выборочно** (перенос, не подключение):

- `src/rag_agent/config.py` — pydantic-settings; вырезать DATABASE_URL, reranker, graph-каппы.
- `src/rag_agent/generation/llm.py` — OpenAI-совместимый LLM-адаптер (base_url/key/model через env). Берётся почти как есть.
- `src/rag_agent/generation/prompt.py` — структура (нумерованные сниппеты, citation_label); текст промпта переписать под рецепты и structured output.
- `src/rag_agent/embedding/embedder.py` — только huggingface-ветка.
- `Dockerfile` — основа (uv, слои); переделать в multi-stage с фронтом.
- `pyproject.toml` — каркас; зависимости проредить: оставить fastapi, uvicorn, pydantic(+settings), openai, sentence-transformers, tenacity, httpx; добавить rank-bm25, numpy; dev: pytest, pytest-asyncio, ruff, httpx.

**НЕ брать:** `graph/` (LangGraph), `store/` (pgvector, alembic, миграции), `retrieval/reranker.py`, RAGAS/`eval/run_ragas.py`, `chunking/splitter.py` (чанкинга нет), langchain-зависимости, историю коммитов. Репозиторий создаётся с нуля, история чистая.

## 6. План: ~7:45 с буфером

Деплой намеренно в середине, не в конце: это единственный бинарный критерий (URL либо открывается, либо нет), риски платформы должны всплыть, пока есть буфер.

| Время | Блок | Выход |
|---|---|---|
| 0:00–0:45 | **SPEC.md + каркасы ADR.** SPEC — самый первый коммит (история должна показывать spec-first). Полная схема ответа, критерии приёмки по каждой причине отказа, edge cases (пустой вопрос, out-of-domain, противоречащие рецепты, аллергии, длинный ввод), допущения, NFR: p95 < 4 c, цена 1000 вопросов (TODO до замера). ADR 001–004: решение + альтернативы + «когда неверно», детали позже | SPEC.md, docs/adr/*.md |
| 0:45–1:05 | **Скелет.** Структура, перенос файлов из донора, uv sync, /health, ruff+pytest. Сразу CLAUDE.md проекта (артефакт сдачи!): контракт, правило «тест раньше реализации для детерминированных модулей», «не выдумывай поля схемы» | собирается, тесты зелёные |
| 1:05–2:05 | **Ingest, test-first.** Тест на фикстурах: wikitext → {time_minutes, diet_tags, allergen_flags, ingredients[], steps[]} — красный коммит, потом реализация. scripts/ingest.py: MediaWiki API, категории soups + desserts + vegetarian + одна пересекающаяся (обеспечить 2+ рецепта одного блюда), ~50 страниц. corpus.json коммитится. ⏱ Таймбокс парсинга вики-разметки 40 мин; fallback: plain-text extracts + грубые эвристики, допущение в SPEC | corpus.json |
| 2:05–3:05 | **Retrieval, test-first.** Тесты: constraint parser; метафильтры отсекают; порог → out_of_corpus. Реализация: BM25 + numpy-матрица эмбеддингов, RRF, фильтры, порог. Ноль вызовов LLM | покрытый retrieval |
| 3:05–4:05 | **/ask + генерация.** Pydantic-контракт = SPEC. Тесты с mock LLM: safety-регулярки, пустой вопрос, out-of-domain, порог, валидность схемы. Потом LLM-вызов со structured output. JSON-лог на запрос | рабочий /ask |
| 4:05–4:45 | **Деплой + CI.** Northflank template + GH Actions (tests→lint→build→deploy→smoke). Задеплоить скелет | живой публичный URL |
| 4:45–5:25 | **Фронтенд.** Vite + vanilla TS, одна страница, сборка в статику, отдача из FastAPI, редеплой | UI на проде |
| 5:25–6:25 | **Eval-харнесс.** evals/golden_set.yaml (15 вопросов, состав ниже) + run_evals.py: бьёт по URL (флаг local/prod), валидирует каждый ответ Pydantic-схемой, проверяет ожидаемые свойства, pass/fail-таблица + JSON-отчёт. Прогнать против прода, отчёт закоммитить | отчёт evals |
| 6:25–7:15 | **README + финал ADR + AI_NOTES.** Cost & Latency из реального прогона (латентности из харнесса, токены из ответов), условия смены модели, bottleneck, debugging-абзац (= описание JSON-лога), Deployment, «что вырезано и как закрыть разрыв». ADR дополнить цифрами. AI_NOTES.md: что принято от агента, что переписано | полный README |
| 7:15–7:45 | **Буфер.** Полный прогон evals, вычитка git log, проверка утечки секретов | — |

**Golden set (15):** 3 прямой поиск рецепта (нашёл нужный источник) · 3 с ограничениями время/диета (ограничение соблюдено) · 2 out_of_corpus — блюдо существует, но не в корпусе (не сочинил из памяти) · 2 out_of_domain (не про еду) · 2 safety (аллергены) · 1 пустой/мусорный ввод · 2 противоречащие рецепты (названы обе версии).

**Если время горит, резать в порядке:** буфер → фронт до голого минимума → golden set 15→12. **Никогда не резать:** SPEC, деплой, eval-харнесс, README с цифрами — это 4 из 6 критериев.

## 7. Порядок коммитов (~20, English, мелкие)

```
1.  docs: SPEC.md — API contract, acceptance criteria, edge cases, NFR targets
2.  docs: ADR skeletons 001-004 with decisions taken
3.  chore: project scaffold (config, LLM adapter, tooling) + CLAUDE.md
4.  test: recipe metadata parser (time, diet, allergens) — failing
5.  feat: MediaWiki ingest script, metadata parser green
6.  data: corpus.json — 50 recipes across 4 categories
7.  test: query constraint extraction — failing
8.  feat: constraint parser
9.  test: hybrid retrieval, metadata filters, relevance threshold — failing
10. feat: in-memory BM25+vector retrieval with filters and threshold
11. test: /ask contract — refusal branches, safety gate (mocked LLM)
12. feat: POST /ask deterministic pipeline
13. feat: LLM generation with structured output
14. ci: GitHub Actions — test, lint, build, deploy, smoke
15. deploy: Northflank template, first deployment
16. feat: single-page TS frontend
17. feat: serve frontend static from FastAPI
18. eval: golden set (15 questions) + automated harness, prod report
19. docs: README — Cost & Latency (measured), Deployment, debugging
20. docs: finalize ADRs with measured numbers, AI_NOTES.md
```

Пары 4→5, 7→8, 9→10, 11→12 — видимый в истории «тест раньше реализации» (прямое требование ТЗ). Коммитить строго по ходу, не одним махом в конце.

## 8. Чего НЕ делать (с обоснованием — не отменять решение, не прочитав причину)

**LangGraph / self-correction / реранкер / любые агентные циклы.** Корректирующий граф стоит 7 вызовов LLM на вопрос в лучшем случае (4 grade_documents + 1 generate + 2 grade_generation) и до ~20 с переписываниями запроса — против одного вызова у нас. Это 7–20× по цене и latency на корпусе из 50 документов, а cost & latency — отдельный критерий оценки. ТЗ прямо говорит «do not add unnecessary polish». Плюс runtime-судья (grounded/addresses) конкурирует с eval-харнессом: ТЗ требует оффлайн-проверок с утверждениями, а не недетерминированной самооценки в проде. Реранкер отдельно: кросс-энкодер поверх горстки документов после метафильтра — +400 МБ образа и +latency без измеримого выигрыша. **Всё это упомянуть в ADR-002 как рассмотренные и отклонённые альтернативы с условием пересмотра** (корпус вырос / precision на golden set просел) — «рассмотрел и отклонил с обоснованием» засчитывается, «не подумал» нет.

**Векторные БД, любые БД вообще.** 50 рецептов = матрица 50×384 ≈ 75 КБ, полный перебор — микросекунды. БД добавляет второй сервис, состояние, том, миграции и второй режим отказа. Главное: statelessness делает «safe to deploy twice» истинным *по построению*, а не за счёт аккуратных идемпотентных миграций и ingest-джобы — а идемпотентность повторного деплоя это требование ТЗ. С БД ingest становится отдельным шагом в проде, что конфликтует с «new deployment without manual steps». Условие пересмотра в ADR-002: >10k документов, обновление корпуса без передеплоя, или несколько инстансов с общим состоянием → pgvector.

**RAGAS как основной eval.** RAGAS выдаёт непрерывные оценки качества (faithfulness, answer_relevancy, context_precision/recall), считаемые LLM-судьёй. ТЗ требует другого: утверждений о свойствах — нашёл ли нужный источник, отказал ли где надо, соблюдено ли ограничение, валиден ли ответ по JSON-контракту. Pass/fail, не среднее. RAGAS структурно не умеет выразить «ожидается refused=true, reason=out_of_corpus» — у него нет понятия отказа. И он недетерминирован: измерять LLM-пайплайн другим LLM-пайплайном без ground truth. Плюс он дорог по времени и вызовам, а харнесс должен гоняться часто и дёшево. Бонусом в самом конце — можно, если ядро готово («extra features get credit only on a complete core»).

**Аутентификация, rate limiting, стриминг, мультиязычность, история диалога.** Не в требованиях, съедают часы, приносят ноль баллов. Но: **молча пропустить — минус, явно назвать — плюс.** ТЗ: «If you stop before production grade, write this in the README. Write what is necessary to close the gap» и «cut scope consciously and record what you cut». То есть задача не «игнорировать», а «превратить работу в документацию»: строка на пункт + что нужно для закрытия, ~10 минут, кормит оценочный критерий и показывает, что ты знаешь, чем production-grade отличается от демо.

**Полировка UI.** Дословно из ТЗ: «The UI must function. We do not grade its appearance» и «we do not grade UI polish or the quantity of code». Время отсюда — время, не потраченное на шесть оцениваемых критериев. Вылизанный UI может даже навредить: сигнализирует, что оптимизировал не то, вопреки явному указанию. Что в UI действительно важно — чтобы рендерились все три состояния (ответ+цитаты / отказ с причиной / ошибка) и отказ был визуально отличим: это демонстрация машиночитаемого контракта, а не украшательство.

**Не выдумывать цены моделей из памяти.** Прайсинг вендоров двигается, у модели есть срез знаний — любая вспомненная цифра может быть протухшей. Cost & latency — оцениваемый критерий, и неверное число там хуже отсутствующего: оно проверяется за десять секунд и обесценивает все остальные цифры в документе. На живой защите «откуда эта цифра?» — самый простой вопрос к разделу про стоимость. Проверять на страницах вендоров. То же правило для latency: брать из реального прогона харнесса, не из оценок.

**Не хардкодить поведение без записи в SPEC.** Дословно и самым сильным образом в ТЗ: «record your assumption in SPEC.md. **Hidden hardcoded behavior is the only incorrect option**» — единственная формулировка во всём задании со словом «incorrect». Конкретно в нашей сборке под это подпадают: значение порога релевантности, список safety-триггеров, эвристики парсинга времени и диеты, отсечка топ-5, поведение на противоречащих рецептах, лимит длины вопроса, реакция на пустой ввод. Каждое из этого разработчик принимает молча в коде — каждое должно быть в SPEC как заявленное правило. Иначе eval-харнесс теряет смысл (утверждать можно только против описанного поведения), а на follow-up, где дают новое требование и смотрят spec-first, выяснится, что SPEC не описывает систему.

## 9. Что нужно от Ивана (спросить в начале, не выдумывать)

1. GitHub: создать приватный репозиторий (пригласить Artem Kashuta и Anton Snitavets — можно в конце).
2. Northflank: аккаунт, API-токен для CI, выбор плана с RAM ≥ 2 ГБ.
3. LLM: какой провайдер/ключ использовать (адаптер OpenAI-совместимый; нужен ключ в env и в Northflank secrets).
4. Подтвердить выбор дешёвой модели-дефолта после проверки актуальных цен.

## 10. Definition of Done

- [ ] Публичный URL: UI работает, /ask отвечает по контракту, /health зелёный
- [ ] `run_evals.py --target prod` — все 15 проходят, отчёт в репо
- [ ] Тесты и линт зелёные в CI; деплой из репо без ручных шагов
- [ ] SPEC.md, 3–4 ADR (с ценами/латентностью и условиями пересмотра), README (Cost & Latency с замерами, Deployment, debugging-абзац, cut scope), CLAUDE.md, AI_NOTES.md
- [ ] git log: ~20 мелких коммитов, SPEC первый, тест-раньше-реализации виден
- [ ] Секретов в репо нет; `.env.example` есть
- [ ] Повторный деплой той же ревизии безопасен (проверено)
- [ ] Ревьюерам: доступ к репо + доступ к Northflank-проекту (или логам), записано в README
