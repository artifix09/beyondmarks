-- =====================================================================
-- BeyondMarks — data model v3 (PostgreSQL 15+ on Supabase, with pgvector)
-- 21 Oct 2026 · multi-book ready · build-first MVP (templates, facts tables, no worker)
--
-- Design rules
--   1. Anything that varies by board, grade, subject or book is DATA
--      (books, chapters, topics, concepts, outcomes, prerequisites).
--   2. attempts is an append-only event log; skill_states is derived and
--      must be recomputable from attempts.
--   3. Items are immutable once live. An edit creates a new version
--      (supersedes_id) so old attempts keep the exact text they answered.
--   4. Every adaptive decision stores its reason, policy version and the
--      predicted probability of a correct answer (session_items).
--   5. Every AI output stores its prompt id + version; llm_calls stores
--      usage and cost, never prompt text or personal data.
--   6. The browser talks only to FastAPI (service role). RLS is ON for all
--      tables with no client policies = deny by default.
-- =====================================================================

create extension if not exists vector;      -- pgvector
create extension if not exists pgcrypto;    -- gen_random_uuid()

-- ---------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------
create type user_role        as enum ('student', 'editor', 'admin');
create type bloom_level      as enum ('remember', 'understand', 'apply', 'analyze');
create type item_format      as enum ('mcq', 'fill_blank', 'numerical', 'short_answer');
create type item_pool        as enum ('pretest', 'posttest', 'adaptive');
create type item_status      as enum ('draft', 'in_review', 'live', 'retired', 'superseded');
create type session_kind     as enum ('pretest', 'adaptive', 'posttest');
create type session_status   as enum ('active', 'completed', 'abandoned');
create type select_reason    as enum ('warmup', 'weak_level', 'next_weak_level',
                                      'stretch', 'retention', 'concept_repeat',
                                      'prerequisite', 'pretest_fixed', 'posttest_fixed',
                                      'fallback');
create type grader_kind      as enum ('local', 'llm', 'manual');
create type grading_status   as enum ('graded', 'pending', 'failed');
create type explain_style    as enum ('simple_examples', 'step_by_step', 'roman_urdu_mix');
create type explain_template as enum ('remember_keyterms', 'understand_why_chain',
                                      'apply_worked_example', 'analyze_compare',
                                      'fallback_textbook');
create type llm_purpose      as enum ('chat', 'explanation', 'notes', 'grade_short_answer',
                                      'draft_items', 'transcribe_page', 'embed', 'other');
create type flag_status      as enum ('open', 'fixed', 'rejected');
create type item_source      as enum ('template', 'facts', 'book_sentence', 'gemini', 'manual');
create type item_kind        as enum ('fixed', 'template');
create type quantity_type    as enum ('scalar', 'vector', 'other');

-- ---------------------------------------------------------------------
-- Users (students, editors, admins). id = Supabase auth.users.id
-- ---------------------------------------------------------------------
create table users (
    id                   uuid primary key references auth.users(id) on delete cascade,
    role                 user_role not null default 'student',
    display_name         text,                                  -- never sent to the LLM
    style                explain_style not null default 'simple_examples',
    language             text not null default 'en',
    consent_student_at   timestamptz,
    consent_guardian_at  timestamptz,
    cohort               text,                                  -- pilot grouping until orgs/classes exist
    referral_code        text unique,                           -- for the WhatsApp share loop
    referred_by          uuid references users(id),
    created_at           timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- Curriculum graph
-- ---------------------------------------------------------------------
create table books (
    id          uuid primary key default gen_random_uuid(),
    board       text not null,                                  -- 'FBISE', 'PBTB', ...
    grade       smallint not null check (grade between 1 and 16),
    subject     text not null,                                  -- 'physics'
    title       text not null,
    edition     text,                                           -- e.g. '2024'
    language    text not null default 'en',
    publisher   text,
    is_active   boolean not null default true,
    created_at  timestamptz not null default now(),
    unique (board, grade, subject, edition, language)
);

create table enrollments (
    student_id  uuid not null references users(id) on delete cascade,
    book_id     uuid not null references books(id) on delete cascade,
    created_at  timestamptz not null default now(),
    primary key (student_id, book_id)
);

create table chapters (
    id           uuid primary key default gen_random_uuid(),
    book_id      uuid not null references books(id) on delete cascade,
    number       smallint not null,
    title        text not null,
    in_adaptive  boolean not null default false,               -- adaptive bank meets minimum size
    unique (book_id, number)
);

create table topics (
    id          uuid primary key default gen_random_uuid(),
    chapter_id  uuid not null references chapters(id) on delete cascade,
    code        text not null unique,                           -- e.g. 'FBISE-P9-02-01'
    title       text not null,
    position    smallint not null,
    unique (chapter_id, position)
);

create table concepts (
    id          uuid primary key default gen_random_uuid(),
    topic_id    uuid not null references topics(id) on delete cascade,
    code        text not null unique,
    name        text not null
);

-- Prerequisite edges (may cross topics, chapters, books and grades)
create table concept_prereqs (
    concept_id  uuid not null references concepts(id) on delete cascade,
    prereq_id   uuid not null references concepts(id) on delete cascade,
    primary key (concept_id, prereq_id),
    check (concept_id <> prereq_id)
);

-- Board learning outcomes (SLOs)
create table learning_outcomes (
    id          uuid primary key default gen_random_uuid(),
    book_id     uuid not null references books(id) on delete cascade,
    code        text not null,
    text        text not null,
    bloom_hint  bloom_level,                                    -- from the outcome's verb
    unique (book_id, code)
);

create table topic_outcomes (
    topic_id    uuid not null references topics(id) on delete cascade,
    outcome_id  uuid not null references learning_outcomes(id) on delete cascade,
    primary key (topic_id, outcome_id)
);

-- RAG chunks (whole book can be ingested even if only some chapters are adaptive)
create table textbook_chunks (
    id               uuid primary key default gen_random_uuid(),
    book_id          uuid not null references books(id) on delete cascade,
    chapter_id       uuid references chapters(id) on delete cascade,
    topic_id         uuid references topics(id) on delete set null,
    heading          text,
    content          text not null,                             -- Markdown + LaTeX
    page_start       smallint,
    page_end         smallint,
    source           text not null default 'textbook',         -- 'textbook' | 'outcomes' | 'notes'
    embedding        vector(768),                               -- must match embedding_model
    embedding_model  text,
    tsv              tsvector generated always as
                     (to_tsvector('english', coalesce(heading, '') || ' ' || content)) stored,
    created_at       timestamptz not null default now()
);

-- Facts tables: reviewed once, then code turns rows into MCQs / blanks (items.source = 'facts')
create table facts (
    id             uuid primary key default gen_random_uuid(),
    chapter_id     uuid not null references chapters(id) on delete cascade,
    topic_id       uuid references topics(id) on delete set null,
    quantity       text not null,                               -- 'Acceleration'
    symbol         text,                                        -- 'a'
    si_unit        text,                                        -- 'm/s^2'
    quantity_type  quantity_type,                               -- scalar / vector
    formula        text,                                        -- 'Δv / t' (LaTeX allowed)
    definition     text,                                        -- 'rate of change of velocity'
    extra          jsonb not null default '{}',                 -- any other columns (e.g. instrument, example)
    source_pages   int4range,
    reviewed_by    text,
    created_at     timestamptz not null default now(),
    unique (chapter_id, quantity)
);

-- ---------------------------------------------------------------------
-- Question bank
-- answer jsonb by format:
--   mcq:          {"correct": "B"}            options: [{"key":"A","text":"..."}, ...]
--   fill_blank:   {"accepted": ["inertia"], "case_sensitive": false}
--   numerical:    {"value": 20, "abs_tol": 0.1, "rel_tol": 0.02, "unit": "m/s",
--                  "formula": "d / t", "params": {"d": 100, "t": 5}}   -- recomputed in Python
--   short_answer: {"model_answer": "..."}  with rubric {"points":[{"idea":"...","marks":1}],"max":3}
--
-- template jsonb (kind='template', numerical only). Values are drawn when the item is served,
-- stored in session_items.instance, and graded against the computed answer:
--   {"params": {"d": {"min": 50, "max": 500, "step": 10}, "t": {"min": 5, "max": 60, "step": 1}},
--    "answer_expr": "d / t", "unit": "m/s", "round": 2, "abs_tol": 0.05, "rel_tol": 0.01,
--    "constraints": ["d / t < 100"]}
-- ---------------------------------------------------------------------
create table items (
    id                     uuid primary key default gen_random_uuid(),
    topic_id               uuid not null references topics(id) on delete cascade,
    version                smallint not null default 1,
    supersedes_id          uuid references items(id),
    bloom                  bloom_level not null,
    difficulty             smallint not null check (difficulty between 1 and 3),
    format                 item_format not null,
    pool                   item_pool not null default 'adaptive',
    pair_id                uuid,                                -- matched pretest <-> posttest
    language               text not null default 'en',
    source                 item_source not null default 'manual',
    kind                   item_kind not null default 'fixed',
    template               jsonb,                               -- kind='template' only, see header comment
    stem                   text not null,                       -- Markdown + LaTeX (for templates: with {placeholders})
    options                jsonb,
    media                  jsonb,                               -- [{"key":"img/..","alt":".."}]
    answer                 jsonb not null,
    rubric                 jsonb,
    feedback               text not null,                       -- one line shown after answering
    worked_solution        text,                                -- also the AI fallback
    source_pages           int4range,
    status                 item_status not null default 'draft',
    -- provenance + verification
    generated_by           text,                                -- 'model/prompt-id@version' or 'human'
    verification           jsonb,                               -- automatic checks and results
    double_check           jsonb,                               -- 2nd Gemini call's blind answer (gemini items)
    reviewer_1             text,
    reviewer_2             text,
    reviewed_at            timestamptz,
    review_notes           text,
    -- research side track (never gates the live path)
    classifier_bloom       bloom_level,
    classifier_confidence  real,
    classifier_version     text,
    -- statistics (nightly job)
    stat_attempts          integer not null default 0,
    stat_p_correct         real,
    stat_discrimination    real,
    flag_count             integer not null default 0,
    created_at             timestamptz not null default now(),
    check ((format = 'mcq') = (options is not null)),
    check (format <> 'short_answer' or rubric is not null),
    check ((kind = 'template') = (template is not null)),
    check (kind = 'fixed' or format = 'numerical')
);

create table item_concepts (
    item_id     uuid not null references items(id) on delete cascade,
    concept_id  uuid not null references concepts(id) on delete cascade,
    primary key (item_id, concept_id)
);

create table item_outcomes (
    item_id     uuid not null references items(id) on delete cascade,
    outcome_id  uuid not null references learning_outcomes(id) on delete cascade,
    primary key (item_id, outcome_id)
);

-- ---------------------------------------------------------------------
-- Engine policies
-- ---------------------------------------------------------------------
create table engine_policies (
    version      text primary key,                              -- 'rules-v1.0'
    description  text not null,
    params       jsonb not null default '{}',                   -- decay, thresholds, session size...
    is_default   boolean not null default false,
    created_at   timestamptz not null default now()
);
create unique index one_default_policy on engine_policies (is_default) where is_default;

-- ---------------------------------------------------------------------
-- Sessions, plans, attempts
-- ---------------------------------------------------------------------
create table sessions (
    id              uuid primary key default gen_random_uuid(),
    student_id      uuid not null references users(id) on delete cascade,
    topic_id        uuid not null references topics(id),
    kind            session_kind not null,
    session_no      smallint not null check (session_no between 1 and 20),
    policy_version  text not null references engine_policies(version),
    status          session_status not null default 'active',
    style_used      explain_style,
    started_at      timestamptz not null default now(),
    completed_at    timestamptz,
    unique (student_id, topic_id, session_no)
);

create table session_items (
    session_id    uuid not null references sessions(id) on delete cascade,
    position      smallint not null,
    item_id       uuid not null references items(id),
    reason        select_reason not null,
    reason_bloom  bloom_level,
    tier          smallint check (tier between 1 and 3),
    predicted_p   real check (predicted_p between 0 and 1),   -- policy's P(correct) at serve time
    instance      jsonb,                                      -- template items: {"params":{...},"stem":"...","answer":{...}}
    primary key (session_id, position),
    unique (session_id, item_id)
);

create table attempts (
    id               uuid primary key default gen_random_uuid(),
    session_id       uuid not null references sessions(id) on delete cascade,
    student_id       uuid not null references users(id) on delete cascade,
    item_id          uuid not null references items(id),
    response         jsonb not null,
    dont_know        boolean not null default false,            -- "I don't know yet"
    attempt_no       smallint not null default 1,
    score            real check (score between 0 and 1),
    graded_by        grader_kind,
    grading_status   grading_status not null default 'pending',
    grading_detail   jsonb,
    time_ms          integer,                                   -- logged only, never scored
    idempotency_key  text not null unique,
    created_at       timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- Learner model (derived; recomputable from attempts)
-- ---------------------------------------------------------------------
create table skill_states (
    student_id          uuid not null references users(id) on delete cascade,
    topic_id            uuid not null references topics(id) on delete cascade,
    bloom               bloom_level not null,
    a                   real not null default 1,
    b                   real not null default 1,
    n_items             integer not null default 0,
    tier                smallint not null default 1 check (tier between 1 and 3),
    consecutive_correct smallint not null default 0,
    consecutive_wrong   smallint not null default 0,
    hard_streak         smallint not null default 0,
    mastered_at         timestamptz,
    last_session_no     smallint,
    policy_version      text references engine_policies(version),
    updated_at          timestamptz not null default now(),
    primary key (student_id, topic_id, bloom)
);

-- Future (policy v2+): per-concept ability (Elo / knowledge tracing)
create table concept_states (
    student_id      uuid not null references users(id) on delete cascade,
    concept_id      uuid not null references concepts(id) on delete cascade,
    ability         real not null default 0,                    -- theta
    n_items         integer not null default 0,
    policy_version  text references engine_policies(version),
    updated_at      timestamptz not null default now(),
    primary key (student_id, concept_id)
);

create table self_reports (
    id               uuid primary key default gen_random_uuid(),
    session_id       uuid not null unique references sessions(id) on delete cascade,
    student_id       uuid not null references users(id) on delete cascade,
    confidence       smallint check (confidence between 1 and 5),
    predicted_score  smallint check (predicted_score >= 0),
    skipped          boolean not null default false,
    created_at       timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- AI
-- ---------------------------------------------------------------------
create table llm_calls (
    id              uuid primary key default gen_random_uuid(),
    purpose         llm_purpose not null,
    model           text not null,
    prompt_id       text,
    prompt_version  text,
    student_id      uuid references users(id) on delete set null,
    input_tokens    integer,
    output_tokens   integer,
    cost_usd        numeric(10, 6),
    latency_ms      integer,
    ok              boolean not null,
    error           text,
    cache_hit       boolean not null default false,
    created_at      timestamptz not null default now()
);

create table explanations (
    id              uuid primary key default gen_random_uuid(),
    session_id      uuid not null references sessions(id) on delete cascade,
    student_id      uuid not null references users(id) on delete cascade,
    template        explain_template not null,
    focus_bloom     bloom_level,
    style           explain_style not null,
    content         text not null,
    chunk_ids       uuid[] not null default '{}',
    prompt_version  text,
    cache_key       text,
    llm_call_id     uuid references llm_calls(id),
    feedback        smallint check (feedback in (-1, 1)),
    created_at      timestamptz not null default now()
);

create table note_cache (
    topic_id        uuid not null references topics(id) on delete cascade,
    bloom           bloom_level not null,
    style           explain_style not null,
    language        text not null default 'en',
    content         text not null,
    chunk_ids       uuid[] not null default '{}',
    prompt_version  text,
    created_at      timestamptz not null default now(),
    primary key (topic_id, bloom, style, language)
);

create table chat_threads (
    id          uuid primary key default gen_random_uuid(),
    student_id  uuid not null references users(id) on delete cascade,
    book_id     uuid not null references books(id),
    topic_id    uuid references topics(id),                     -- null = whole-book chat
    created_at  timestamptz not null default now()
);

create table chat_messages (
    id              uuid primary key default gen_random_uuid(),
    thread_id       uuid not null references chat_threads(id) on delete cascade,
    role            text not null check (role in ('student', 'assistant')),
    content         text not null,
    chunk_ids       uuid[] not null default '{}',
    prompt_version  text,
    llm_call_id     uuid references llm_calls(id),
    moderation      jsonb,                                      -- input/output check results
    reported        boolean not null default false,
    created_at      timestamptz not null default now()
);

create table eval_runs (
    id              uuid primary key default gen_random_uuid(),
    eval_set        text not null,                              -- 'retrieval-50', 'explain-50', ...
    prompt_id       text,
    prompt_version  text,
    model           text,
    metrics         jsonb not null,
    created_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- Quality, analytics
-- ---------------------------------------------------------------------
create table item_flags (
    id          uuid primary key default gen_random_uuid(),
    item_id     uuid not null references items(id) on delete cascade,
    student_id  uuid references users(id) on delete set null,
    attempt_id  uuid references attempts(id) on delete set null,
    reason      text,
    status      flag_status not null default 'open',
    created_at  timestamptz not null default now()
);

create table events (
    id          bigserial primary key,
    user_id     uuid references users(id) on delete set null,
    name        text not null,                                  -- 'pretest_started', 'chat_opened', ...
    props       jsonb not null default '{}',
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------
create index on chapters (book_id);
create index on topics (chapter_id);
create index on concepts (topic_id);
create index on concept_prereqs (prereq_id);
create index on textbook_chunks (book_id, chapter_id, topic_id);
create index on textbook_chunks using gin (tsv);
create index on textbook_chunks using hnsw (embedding vector_cosine_ops);
create index items_select_idx on items (topic_id, pool, bloom, difficulty) where status = 'live';
create index on items (status);
create index on items (source);
create index on facts (chapter_id);
create index on item_concepts (concept_id);
create index on sessions (student_id, topic_id, session_no);
create index on attempts (student_id, created_at);
create index on attempts (session_id);
create index on attempts (item_id);
create index on llm_calls (created_at);
create index on llm_calls (student_id, created_at);
create index on chat_messages (thread_id, created_at);
create index on item_flags (status);
create index on events (name, created_at);

-- ---------------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------------
create view v_skill_summary as
select
    s.student_id, s.topic_id, s.bloom,
    round((s.a / (s.a + s.b))::numeric, 3) as mastery,
    s.n_items,
    case when s.n_items = 0 then 'none'
         when s.n_items < 3 then 'insufficient'
         when s.mastered_at is not null then 'mastered'
         when s.a / (s.a + s.b) < 0.5 then 'weak'
         when s.a / (s.a + s.b) < 0.8 then 'developing'
         else 'strong' end                  as status,
    case when s.n_items < 3 then 'not_enough_evidence'
         when s.n_items < 7 then 'early_signal'
         else 'consistent_pattern' end      as confidence_label,
    s.tier, s.updated_at
from skill_states s;

create view v_concept_errors as
select at.student_id, ic.concept_id,
       count(*) filter (where at.score < 0.5)                      as wrong_count,
       count(distinct at.session_id) filter (where at.score < 0.5) as wrong_sessions,
       max(at.created_at)                                          as last_seen
from attempts at
join item_concepts ic on ic.item_id = at.item_id
where at.grading_status = 'graded'
group by at.student_id, ic.concept_id;

-- Offline evaluation of the engine: prediction vs outcome per served item
create view v_prediction_log as
select se.policy_version, si.item_id, si.predicted_p, at.score, at.created_at
from session_items si
join sessions se on se.id = si.session_id
join attempts at on at.session_id = si.session_id and at.item_id = si.item_id
where at.grading_status = 'graded' and si.predicted_p is not null;

create view v_daily_ai_cost as
select date_trunc('day', created_at) as day, purpose, model,
       count(*) as calls, sum(cost_usd) as cost_usd,
       percentile_cont(0.95) within group (order by latency_ms) as p95_latency_ms,
       avg(case when ok then 0 else 1 end) as error_rate
from llm_calls
group by 1, 2, 3;

-- ---------------------------------------------------------------------
-- Planned for the teacher/school phase (not created yet):
--   organizations(id, name, type), classes(id, org_id, book_id, name),
--   class_members(class_id, user_id, role), with RLS by organization.
-- ---------------------------------------------------------------------

-- ---------------------------------------------------------------------
-- Row-level security: ON everywhere, no client policies (deny by default)
-- ---------------------------------------------------------------------
do $$
declare t text;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;

-- Seed the first engine policy
insert into engine_policies (version, description, params, is_default) values
('rules-v1.0', 'Decayed counts + staircase + mastery rule (PM review v1)',
 '{"decay":0.9,"session_size":6,"pretest_size":8,"label_min_items":3,"weak":0.5,"strong":0.8,
   "challenge_zone_wrong_weight":1.5,"mastered_hard_streak":2,"no_repeat_sessions":3}', true);
