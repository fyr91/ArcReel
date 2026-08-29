create extension if not exists pgcrypto with schema extensions;

create table if not exists public.arcreel_assets (
  id uuid primary key default extensions.gen_random_uuid(),
  asset_type text not null check (asset_type in ('character', 'scene', 'prop')),
  origin text not null check (origin in ('official', 'user_shared')),
  status text not null default 'published' check (status in ('published', 'archived')),
  source_id uuid,
  source_key text,
  source_fingerprint text,
  owner_id uuid references public.arcreel_profiles(id) on delete set null,
  client_asset_id uuid,
  current_version bigint not null default 0 check (current_version >= 0),
  name text not null check (char_length(name) between 1 and 200),
  description text not null default '',
  voice_style text not null default '',
  voice_id text,
  metadata jsonb not null default '{}'::jsonb,
  published_at timestamptz,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint arcreel_assets_origin_owner_check check (
    (origin = 'official' and source_id is not null and source_key is not null and owner_id is null)
    or (origin = 'user_shared' and owner_id is not null and client_asset_id is not null and source_id is null)
  )
);

create table if not exists public.arcreel_asset_sync_sources (
  id uuid primary key default extensions.gen_random_uuid(),
  source_key text not null unique check (source_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
  display_name text not null,
  asset_type text not null check (asset_type in ('character', 'scene', 'prop')),
  adapter text not null,
  enabled boolean not null default false,
  paused boolean not null default false,
  interval_seconds integer not null default 300 check (interval_seconds between 30 and 86400),
  source_config jsonb not null default '{}'::jsonb,
  cursor jsonb not null default '{}'::jsonb,
  next_run_at timestamptz,
  last_run_at timestamptz,
  last_success_at timestamptz,
  last_status text,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.arcreel_assets
  add constraint arcreel_assets_source_id_fkey
  foreign key (source_id) references public.arcreel_asset_sync_sources(id) on delete restrict;

create unique index if not exists arcreel_assets_official_identity_unique
  on public.arcreel_assets (source_id, source_key) where origin = 'official';
create unique index if not exists arcreel_assets_shared_identity_unique
  on public.arcreel_assets (owner_id, client_asset_id) where origin = 'user_shared';
create index if not exists arcreel_assets_type_status_idx
  on public.arcreel_assets (asset_type, status, updated_at desc);

create table if not exists public.arcreel_asset_versions (
  id uuid primary key,
  asset_id uuid not null references public.arcreel_assets(id) on delete cascade,
  version bigint not null check (version > 0),
  name text not null check (char_length(name) between 1 and 200),
  description text not null default '',
  voice_style text not null default '',
  voice_id text,
  metadata jsonb not null default '{}'::jsonb,
  source_fingerprint text,
  created_by uuid references public.arcreel_profiles(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (asset_id, version)
);

create table if not exists public.arcreel_asset_files (
  id uuid primary key default extensions.gen_random_uuid(),
  version_id uuid not null references public.arcreel_asset_versions(id) on delete cascade,
  file_key text not null check (char_length(file_key) between 1 and 300),
  role text not null,
  media_type text not null check (media_type in ('image', 'audio')),
  mime_type text,
  bucket_id text not null default 'arcreel-assets' check (bucket_id = 'arcreel-assets'),
  object_path text not null,
  byte_size bigint check (byte_size between 0 and 209715200),
  sha256 text check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$'),
  revision text,
  sort_order integer not null default 0,
  source_fields jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (version_id, file_key),
  unique (bucket_id, object_path)
);

create index if not exists arcreel_asset_files_version_order_idx
  on public.arcreel_asset_files (version_id, sort_order, file_key);

create table if not exists public.arcreel_asset_aliases (
  id uuid primary key default extensions.gen_random_uuid(),
  asset_id uuid not null references public.arcreel_assets(id) on delete cascade,
  alias text not null check (char_length(alias) between 1 and 200),
  created_at timestamptz not null default now()
);

create unique index if not exists arcreel_asset_aliases_identity_unique
  on public.arcreel_asset_aliases (asset_id, lower(alias));

create table if not exists public.arcreel_asset_changes (
  revision bigint generated always as identity primary key,
  asset_id uuid not null references public.arcreel_assets(id) on delete cascade,
  asset_type text not null check (asset_type in ('character', 'scene', 'prop')),
  operation text not null check (operation in ('upsert', 'archive')),
  asset_version bigint not null check (asset_version >= 0),
  changed_at timestamptz not null default now()
);

create index if not exists arcreel_asset_changes_type_revision_idx
  on public.arcreel_asset_changes (asset_type, revision);

create table if not exists public.arcreel_asset_sync_runs (
  id uuid primary key default extensions.gen_random_uuid(),
  source_id uuid not null references public.arcreel_asset_sync_sources(id) on delete cascade,
  trigger_kind text not null check (trigger_kind in ('schedule', 'manual', 'retry')),
  status text not null default 'queued'
    check (status in ('queued', 'running', 'cancelling', 'cancelled', 'succeeded', 'failed')),
  requested_by uuid references public.arcreel_profiles(id) on delete set null,
  worker_id text,
  cursor_before jsonb not null default '{}'::jsonb,
  cursor_after jsonb not null default '{}'::jsonb,
  seen_source_keys jsonb not null default '[]'::jsonb,
  imported_count integer not null default 0,
  updated_count integer not null default 0,
  unchanged_count integer not null default 0,
  archived_count integer not null default 0,
  error_code text,
  error_detail text,
  queued_at timestamptz not null default now(),
  started_at timestamptz,
  heartbeat_at timestamptz,
  finished_at timestamptz,
  updated_at timestamptz not null default now()
);

create unique index if not exists arcreel_asset_sync_runs_one_active_per_source
  on public.arcreel_asset_sync_runs (source_id)
  where status in ('queued', 'running', 'cancelling');
create index if not exists arcreel_asset_sync_runs_recent_idx
  on public.arcreel_asset_sync_runs (queued_at desc);

drop trigger if exists arcreel_assets_set_updated_at on public.arcreel_assets;
create trigger arcreel_assets_set_updated_at before update on public.arcreel_assets
for each row execute function public.arcreel_set_updated_at();
drop trigger if exists arcreel_asset_sync_sources_set_updated_at on public.arcreel_asset_sync_sources;
create trigger arcreel_asset_sync_sources_set_updated_at before update on public.arcreel_asset_sync_sources
for each row execute function public.arcreel_set_updated_at();
drop trigger if exists arcreel_asset_sync_runs_set_updated_at on public.arcreel_asset_sync_runs;
create trigger arcreel_asset_sync_runs_set_updated_at before update on public.arcreel_asset_sync_runs
for each row execute function public.arcreel_set_updated_at();

insert into public.arcreel_asset_sync_sources
  (source_key, display_name, asset_type, adapter, enabled, paused, interval_seconds, source_config, next_run_at)
values
  (
    'existing-character-catalog',
    '现有角色资产数据源',
    'character',
    'character_catalog_v1',
    true,
    false,
    300,
    jsonb_build_object(
      'endpoint',
      'https://sbwaergjomvcmtivcxer.supabase.co/functions/v1/character-catalog-export'
    ),
    now()
  ),
  ('scene-catalog', '场景资产数据源（待配置）', 'scene', 'unconfigured', false, true, 300, '{}'::jsonb, null),
  ('prop-catalog', '道具资产数据源（待配置）', 'prop', 'unconfigured', false, true, 300, '{}'::jsonb, null)
on conflict (source_key) do nothing;

alter table public.arcreel_assets enable row level security;
alter table public.arcreel_asset_versions enable row level security;
alter table public.arcreel_asset_files enable row level security;
alter table public.arcreel_asset_aliases enable row level security;
alter table public.arcreel_asset_changes enable row level security;
alter table public.arcreel_asset_sync_sources enable row level security;
alter table public.arcreel_asset_sync_runs enable row level security;

revoke all on public.arcreel_assets from anon, authenticated;
revoke all on public.arcreel_asset_versions from anon, authenticated;
revoke all on public.arcreel_asset_files from anon, authenticated;
revoke all on public.arcreel_asset_aliases from anon, authenticated;
revoke all on public.arcreel_asset_changes from anon, authenticated;
revoke all on public.arcreel_asset_sync_sources from anon, authenticated;
revoke all on public.arcreel_asset_sync_runs from anon, authenticated;
grant all on public.arcreel_assets to service_role;
grant all on public.arcreel_asset_versions to service_role;
grant all on public.arcreel_asset_files to service_role;
grant all on public.arcreel_asset_aliases to service_role;
grant all on public.arcreel_asset_changes to service_role;
grant all on public.arcreel_asset_sync_sources to service_role;
grant all on public.arcreel_asset_sync_runs to service_role;
grant usage, select on all sequences in schema public to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'arcreel-assets',
  'arcreel-assets',
  false,
  209715200,
  array[
    'image/png', 'image/jpeg', 'image/webp', 'image/gif',
    'audio/mpeg', 'audio/wav', 'audio/x-wav', 'audio/mp4',
    'audio/aac', 'audio/flac', 'audio/ogg', 'application/octet-stream'
  ]
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists arcreel_assets_active_read on storage.objects;
create policy arcreel_assets_active_read on storage.objects
for select to authenticated
using (
  bucket_id = 'arcreel-assets'
  and exists (
    select 1 from public.arcreel_profiles p
    where p.id = (select auth.uid()) and p.status = 'active'
  )
);

drop policy if exists arcreel_assets_shared_insert on storage.objects;
create policy arcreel_assets_shared_insert on storage.objects
for insert to authenticated
with check (
  bucket_id = 'arcreel-assets'
  and (storage.foldername(name))[1] = 'shared'
  and (storage.foldername(name))[2] = (select auth.uid())::text
  and exists (
    select 1 from public.arcreel_profiles p
    where p.id = (select auth.uid()) and p.status = 'active'
  )
);

drop policy if exists arcreel_assets_shared_delete on storage.objects;
create policy arcreel_assets_shared_delete on storage.objects
for delete to authenticated
using (
  bucket_id = 'arcreel-assets'
  and (storage.foldername(name))[1] = 'shared'
  and (storage.foldername(name))[2] = (select auth.uid())::text
  and not exists (
    select 1 from public.arcreel_asset_files f
    where f.bucket_id = storage.objects.bucket_id and f.object_path = storage.objects.name
  )
);

create or replace function public.arcreel_require_active_profile()
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid := auth.uid();
begin
  if v_user_id is null or not exists (
    select 1 from public.arcreel_profiles p where p.id = v_user_id and p.status = 'active'
  ) then
    raise exception 'ARCREEL_PROFILE_INACTIVE' using errcode = '42501';
  end if;
  return v_user_id;
end;
$$;

create or replace function public.arcreel_require_admin_profile()
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid := auth.uid();
begin
  if v_user_id is null or not exists (
    select 1 from public.arcreel_profiles p
    where p.id = v_user_id and p.status = 'active' and p.role = 'admin'
  ) then
    raise exception 'ARCREEL_ADMIN_REQUIRED' using errcode = '42501';
  end if;
  return v_user_id;
end;
$$;

create or replace function public.arcreel_pull_asset_changes(
  p_asset_types text[],
  p_after bigint default 0,
  p_limit integer default 100
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid;
  v_limit integer := least(greatest(coalesce(p_limit, 100), 1), 500);
  v_changes jsonb;
  v_next bigint := greatest(coalesce(p_after, 0), 0);
  v_has_more boolean := false;
begin
  v_user_id := public.arcreel_require_active_profile();
  if p_asset_types is null or cardinality(p_asset_types) = 0
     or exists (select 1 from unnest(p_asset_types) t where t not in ('character', 'scene', 'prop')) then
    raise exception 'ARCREEL_ASSET_TYPE_INVALID' using errcode = '22023';
  end if;

  with selected_changes as (
    select c.*
    from public.arcreel_asset_changes c
    where c.revision > greatest(coalesce(p_after, 0), 0)
      and c.asset_type = any (p_asset_types)
    order by c.revision
    limit v_limit
  ), payloads as (
    select
      c.revision,
      c.operation,
      jsonb_build_object(
        'id', a.id,
        'asset_type', a.asset_type,
        'origin', a.origin,
        'status', a.status,
        'version', a.current_version,
        'name', coalesce(v.name, a.name),
        'description', coalesce(v.description, a.description),
        'voice_style', coalesce(v.voice_style, a.voice_style),
        'voice_id', coalesce(v.voice_id, a.voice_id),
        'owner_id', a.owner_id,
        'owner_name', p.display_name,
        'aliases', coalesce((
          select jsonb_agg(aa.alias order by lower(aa.alias))
          from public.arcreel_asset_aliases aa where aa.asset_id = a.id
        ), '[]'::jsonb),
        'files', coalesce((
          select jsonb_agg(jsonb_build_object(
            'id', f.id,
            'key', f.file_key,
            'role', f.role,
            'media_type', f.media_type,
            'mime_type', f.mime_type,
            'bucket_id', f.bucket_id,
            'object_path', f.object_path,
            'byte_size', f.byte_size,
            'sha256', f.sha256,
            'revision', f.revision,
            'sort_order', f.sort_order,
            'source_fields', f.source_fields
          ) order by f.sort_order, f.file_key)
          from public.arcreel_asset_files f where f.version_id = v.id
        ), '[]'::jsonb)
      ) as asset
    from selected_changes c
    join public.arcreel_assets a on a.id = c.asset_id
    left join public.arcreel_asset_versions v
      on v.asset_id = a.id and v.version = a.current_version
    left join public.arcreel_profiles p on p.id = a.owner_id
    order by c.revision
  )
  select
    coalesce(jsonb_agg(jsonb_build_object(
      'revision', revision,
      'operation', operation,
      'asset', asset
    ) order by revision), '[]'::jsonb),
    coalesce(max(revision), v_next)
  into v_changes, v_next
  from payloads;

  select exists (
    select 1 from public.arcreel_asset_changes c
    where c.revision > v_next and c.asset_type = any (p_asset_types)
  ) into v_has_more;

  return jsonb_build_object('changes', v_changes, 'next_cursor', v_next, 'has_more', v_has_more);
end;
$$;

create or replace function public.arcreel_publish_asset(
  p_asset_id uuid,
  p_version_id uuid,
  p_client_asset_id uuid,
  p_asset_type text,
  p_name text,
  p_description text default '',
  p_voice_style text default '',
  p_voice_id text default null,
  p_aliases text[] default '{}'::text[],
  p_metadata jsonb default '{}'::jsonb,
  p_files jsonb default '[]'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid;
  v_asset public.arcreel_assets%rowtype;
  v_version bigint;
  v_file jsonb;
  v_expected_prefix text;
begin
  v_user_id := public.arcreel_require_active_profile();
  if p_asset_id is null or p_version_id is null or p_client_asset_id is null
     or p_asset_type not in ('character', 'scene', 'prop')
     or char_length(btrim(coalesce(p_name, ''))) not between 1 and 200
     or jsonb_typeof(coalesce(p_files, '[]'::jsonb)) <> 'array'
     or jsonb_array_length(coalesce(p_files, '[]'::jsonb)) > 20 then
    raise exception 'ARCREEL_ASSET_PAYLOAD_INVALID' using errcode = '22023';
  end if;

  select * into v_asset from public.arcreel_assets a
  where a.id = p_asset_id or (a.owner_id = v_user_id and a.client_asset_id = p_client_asset_id)
  order by (a.id = p_asset_id) desc
  limit 1
  for update;

  if found and (v_asset.origin <> 'user_shared' or v_asset.owner_id <> v_user_id) then
    raise exception 'ARCREEL_ASSET_NOT_OWNED' using errcode = '42501';
  end if;
  if found and (v_asset.asset_type <> p_asset_type or v_asset.client_asset_id <> p_client_asset_id) then
    raise exception 'ARCREEL_ASSET_IDENTITY_MISMATCH' using errcode = '22023';
  end if;

  if not found then
    insert into public.arcreel_assets (
      id, asset_type, origin, status, owner_id, client_asset_id, current_version,
      name, description, voice_style, voice_id, metadata, published_at
    ) values (
      p_asset_id, p_asset_type, 'user_shared', 'published', v_user_id, p_client_asset_id, 0,
      btrim(p_name), coalesce(p_description, ''),
      case when p_asset_type = 'character' then coalesce(p_voice_style, '') else '' end,
      case when p_asset_type = 'character' then p_voice_id else null end,
      coalesce(p_metadata, '{}'::jsonb), now()
    ) returning * into v_asset;
  end if;

  v_version := v_asset.current_version + 1;
  v_expected_prefix := 'shared/' || v_user_id::text || '/' || v_asset.id::text || '/' || p_version_id::text || '/';
  for v_file in select value from jsonb_array_elements(coalesce(p_files, '[]'::jsonb)) loop
    if coalesce(v_file->>'bucket_id', '') <> 'arcreel-assets'
       or coalesce(v_file->>'object_path', '') not like v_expected_prefix || '%'
       or coalesce(v_file->>'media_type', '') not in ('image', 'audio')
       or char_length(coalesce(v_file->>'key', '')) not between 1 and 300
       or not exists (
         select 1 from storage.objects o
         where o.bucket_id = 'arcreel-assets' and o.name = v_file->>'object_path'
       ) then
      raise exception 'ARCREEL_ASSET_FILE_INVALID' using errcode = '22023';
    end if;
  end loop;

  insert into public.arcreel_asset_versions (
    id, asset_id, version, name, description, voice_style, voice_id, metadata, created_by
  ) values (
    p_version_id, v_asset.id, v_version, btrim(p_name), coalesce(p_description, ''),
    case when p_asset_type = 'character' then coalesce(p_voice_style, '') else '' end,
    case when p_asset_type = 'character' then p_voice_id else null end,
    coalesce(p_metadata, '{}'::jsonb), v_user_id
  );

  insert into public.arcreel_asset_files (
    version_id, file_key, role, media_type, mime_type, bucket_id, object_path,
    byte_size, sha256, revision, sort_order, source_fields
  )
  select
    p_version_id,
    item->>'key',
    coalesce(item->>'role', 'attachment'),
    item->>'media_type',
    nullif(item->>'mime_type', ''),
    item->>'bucket_id',
    item->>'object_path',
    nullif(item->>'byte_size', '')::bigint,
    nullif(lower(item->>'sha256'), ''),
    nullif(item->>'revision', ''),
    coalesce((item->>'sort_order')::integer, 0),
    coalesce(item->'source_fields', '[]'::jsonb)
  from jsonb_array_elements(coalesce(p_files, '[]'::jsonb)) item;

  delete from public.arcreel_asset_aliases where asset_id = v_asset.id;
  insert into public.arcreel_asset_aliases (asset_id, alias)
  select v_asset.id, btrim(alias)
  from unnest(coalesce(p_aliases, '{}'::text[])) alias
  where char_length(btrim(alias)) between 1 and 200
    and lower(btrim(alias)) <> lower(btrim(p_name))
  on conflict do nothing;

  update public.arcreel_assets set
    current_version = v_version,
    status = 'published',
    name = btrim(p_name),
    description = coalesce(p_description, ''),
    voice_style = case when p_asset_type = 'character' then coalesce(p_voice_style, '') else '' end,
    voice_id = case when p_asset_type = 'character' then p_voice_id else null end,
    metadata = coalesce(p_metadata, '{}'::jsonb),
    published_at = now(),
    archived_at = null
  where id = v_asset.id;

  insert into public.arcreel_asset_changes (asset_id, asset_type, operation, asset_version)
  values (v_asset.id, p_asset_type, 'upsert', v_version);

  return jsonb_build_object('asset_id', v_asset.id, 'version_id', p_version_id, 'version', v_version);
end;
$$;

create or replace function public.arcreel_archive_shared_asset(p_asset_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid;
  v_asset public.arcreel_assets%rowtype;
begin
  v_user_id := public.arcreel_require_active_profile();
  select * into v_asset from public.arcreel_assets a where a.id = p_asset_id for update;
  if not found or v_asset.origin <> 'user_shared' or v_asset.owner_id <> v_user_id then
    raise exception 'ARCREEL_ASSET_NOT_OWNED' using errcode = '42501';
  end if;
  if v_asset.status <> 'archived' then
    update public.arcreel_assets set status = 'archived', archived_at = now() where id = p_asset_id;
    insert into public.arcreel_asset_changes (asset_id, asset_type, operation, asset_version)
    values (v_asset.id, v_asset.asset_type, 'archive', v_asset.current_version);
  end if;
  return jsonb_build_object('asset_id', v_asset.id, 'status', 'archived');
end;
$$;

create or replace function public.arcreel_asset_sync_dashboard()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid;
  v_sources jsonb;
  v_runs jsonb;
begin
  v_user_id := public.arcreel_require_admin_profile();
  select coalesce(jsonb_agg(to_jsonb(s) order by s.asset_type, s.source_key), '[]'::jsonb)
    into v_sources from public.arcreel_asset_sync_sources s;
  select coalesce(jsonb_agg(to_jsonb(r) order by r.queued_at desc), '[]'::jsonb)
    into v_runs from (
      select runs.*, sources.source_key, sources.display_name, sources.asset_type
      from public.arcreel_asset_sync_runs runs
      join public.arcreel_asset_sync_sources sources on sources.id = runs.source_id
      order by runs.queued_at desc
      limit 100
    ) r;
  return jsonb_build_object('sources', v_sources, 'runs', v_runs);
end;
$$;

create or replace function public.arcreel_request_asset_sync_run(
  p_source_key text,
  p_trigger_kind text default 'manual'
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid;
  v_source public.arcreel_asset_sync_sources%rowtype;
  v_run public.arcreel_asset_sync_runs%rowtype;
begin
  v_user_id := public.arcreel_require_admin_profile();
  if p_trigger_kind not in ('manual', 'retry') then
    raise exception 'ARCREEL_SYNC_TRIGGER_INVALID' using errcode = '22023';
  end if;
  select * into v_source from public.arcreel_asset_sync_sources where source_key = p_source_key;
  if not found or v_source.adapter = 'unconfigured' then
    raise exception 'ARCREEL_SYNC_SOURCE_UNAVAILABLE' using errcode = '22023';
  end if;
  select * into v_run from public.arcreel_asset_sync_runs
  where source_id = v_source.id and status in ('queued', 'running', 'cancelling')
  order by queued_at desc limit 1;
  if not found then
    insert into public.arcreel_asset_sync_runs (source_id, trigger_kind, requested_by, cursor_before)
    values (v_source.id, p_trigger_kind, v_user_id, v_source.cursor)
    returning * into v_run;
  end if;
  return to_jsonb(v_run);
end;
$$;

create or replace function public.arcreel_update_asset_sync_source(
  p_source_key text,
  p_action text,
  p_interval_seconds integer default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid;
  v_source public.arcreel_asset_sync_sources%rowtype;
begin
  v_user_id := public.arcreel_require_admin_profile();
  if p_action = 'pause' then
    update public.arcreel_asset_sync_sources set paused = true where source_key = p_source_key returning * into v_source;
  elsif p_action = 'resume' then
    update public.arcreel_asset_sync_sources
    set paused = false, next_run_at = case when enabled then now() else next_run_at end
    where source_key = p_source_key returning * into v_source;
  elsif p_action = 'set_interval' and p_interval_seconds between 30 and 86400 then
    update public.arcreel_asset_sync_sources set interval_seconds = p_interval_seconds
    where source_key = p_source_key returning * into v_source;
  else
    raise exception 'ARCREEL_SYNC_ACTION_INVALID' using errcode = '22023';
  end if;
  if not found then
    raise exception 'ARCREEL_SYNC_SOURCE_NOT_FOUND' using errcode = '22023';
  end if;
  return to_jsonb(v_source);
end;
$$;

create or replace function public.arcreel_cancel_asset_sync_run(p_run_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid;
  v_run public.arcreel_asset_sync_runs%rowtype;
begin
  v_user_id := public.arcreel_require_admin_profile();
  update public.arcreel_asset_sync_runs set
    status = case when status = 'queued' then 'cancelled' else 'cancelling' end,
    finished_at = case when status = 'queued' then now() else finished_at end
  where id = p_run_id and status in ('queued', 'running')
  returning * into v_run;
  if not found then
    select * into v_run from public.arcreel_asset_sync_runs where id = p_run_id;
  end if;
  if not found then raise exception 'ARCREEL_SYNC_RUN_NOT_FOUND' using errcode = '22023'; end if;
  return to_jsonb(v_run);
end;
$$;

create or replace function public.arcreel_retry_asset_sync_run(p_run_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid;
  v_source_key text;
begin
  v_user_id := public.arcreel_require_admin_profile();
  select s.source_key into v_source_key
  from public.arcreel_asset_sync_runs r
  join public.arcreel_asset_sync_sources s on s.id = r.source_id
  where r.id = p_run_id and r.status in ('cancelled', 'succeeded', 'failed');
  if not found then raise exception 'ARCREEL_SYNC_RUN_NOT_RETRYABLE' using errcode = '22023'; end if;
  return public.arcreel_request_asset_sync_run(v_source_key, 'retry');
end;
$$;

create or replace function public.arcreel_claim_asset_sync_run(p_worker_id text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_run public.arcreel_asset_sync_runs%rowtype;
  v_source public.arcreel_asset_sync_sources%rowtype;
begin
  if auth.role() <> 'service_role' then
    raise exception 'ARCREEL_SERVICE_ROLE_REQUIRED' using errcode = '42501';
  end if;

  insert into public.arcreel_asset_sync_runs (source_id, trigger_kind, cursor_before)
  select s.id, 'schedule', s.cursor
  from public.arcreel_asset_sync_sources s
  where s.enabled and not s.paused and s.adapter <> 'unconfigured'
    and coalesce(s.next_run_at, now()) <= now()
    and not exists (
      select 1 from public.arcreel_asset_sync_runs r
      where r.source_id = s.id and r.status in ('queued', 'running', 'cancelling')
    )
  on conflict do nothing;

  select * into v_run from public.arcreel_asset_sync_runs
  where status = 'queued'
  order by queued_at
  limit 1
  for update skip locked;
  if not found then return null; end if;

  update public.arcreel_asset_sync_runs set
    status = 'running', worker_id = p_worker_id, started_at = now(), heartbeat_at = now()
  where id = v_run.id returning * into v_run;
  select * into v_source from public.arcreel_asset_sync_sources where id = v_run.source_id;
  return jsonb_build_object('run', to_jsonb(v_run), 'source', to_jsonb(v_source));
end;
$$;

create or replace function public.arcreel_heartbeat_asset_sync_run(p_run_id uuid, p_worker_id text)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare v_status text;
begin
  if auth.role() <> 'service_role' then raise exception 'ARCREEL_SERVICE_ROLE_REQUIRED' using errcode = '42501'; end if;
  update public.arcreel_asset_sync_runs set heartbeat_at = now()
  where id = p_run_id and worker_id = p_worker_id and status in ('running', 'cancelling')
  returning status into v_status;
  return v_status;
end;
$$;

create or replace function public.arcreel_report_asset_sync_run(
  p_run_id uuid,
  p_worker_id text,
  p_status text,
  p_cursor jsonb default '{}'::jsonb,
  p_imported_count integer default 0,
  p_updated_count integer default 0,
  p_unchanged_count integer default 0,
  p_archived_count integer default 0,
  p_seen_source_keys jsonb default '[]'::jsonb,
  p_error_code text default null,
  p_error_detail text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_run public.arcreel_asset_sync_runs%rowtype;
begin
  if auth.role() <> 'service_role' then raise exception 'ARCREEL_SERVICE_ROLE_REQUIRED' using errcode = '42501'; end if;
  if p_status not in ('cancelled', 'succeeded', 'failed') then
    raise exception 'ARCREEL_SYNC_STATUS_INVALID' using errcode = '22023';
  end if;
  update public.arcreel_asset_sync_runs set
    status = p_status,
    cursor_after = coalesce(p_cursor, '{}'::jsonb),
    seen_source_keys = coalesce(p_seen_source_keys, '[]'::jsonb),
    imported_count = greatest(p_imported_count, 0),
    updated_count = greatest(p_updated_count, 0),
    unchanged_count = greatest(p_unchanged_count, 0),
    archived_count = greatest(p_archived_count, 0),
    error_code = p_error_code,
    error_detail = left(p_error_detail, 2000),
    heartbeat_at = now(),
    finished_at = now()
  where id = p_run_id and worker_id = p_worker_id and status in ('running', 'cancelling')
  returning * into v_run;
  if not found then raise exception 'ARCREEL_SYNC_RUN_NOT_OWNED' using errcode = '42501'; end if;

  update public.arcreel_asset_sync_sources set
    cursor = case when p_status = 'succeeded' then coalesce(p_cursor, '{}'::jsonb) else cursor end,
    last_run_at = now(),
    last_success_at = case when p_status = 'succeeded' then now() else last_success_at end,
    last_status = p_status,
    last_error = case when p_status = 'failed' then left(coalesce(p_error_detail, p_error_code), 2000) else null end,
    next_run_at = case when enabled and not paused then now() + make_interval(secs => interval_seconds) else next_run_at end
  where id = v_run.source_id;
  return to_jsonb(v_run);
end;
$$;

create or replace function public.arcreel_import_official_asset(
  p_source_key text,
  p_source_asset_key text,
  p_asset_id uuid,
  p_version_id uuid,
  p_source_fingerprint text,
  p_snapshot jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_source public.arcreel_asset_sync_sources%rowtype;
  v_asset public.arcreel_assets%rowtype;
  v_version bigint;
  v_file jsonb;
  v_prefix text;
begin
  if auth.role() <> 'service_role' then raise exception 'ARCREEL_SERVICE_ROLE_REQUIRED' using errcode = '42501'; end if;
  select * into v_source from public.arcreel_asset_sync_sources where source_key = p_source_key;
  if not found or v_source.asset_type <> p_snapshot->>'asset_type' then
    raise exception 'ARCREEL_SYNC_SOURCE_INVALID' using errcode = '22023';
  end if;
  select * into v_asset from public.arcreel_assets
  where source_id = v_source.id and source_key = p_source_asset_key for update;
  if found and v_asset.source_fingerprint = p_source_fingerprint and v_asset.status = 'published' then
    return jsonb_build_object('outcome', 'unchanged', 'asset_id', v_asset.id, 'version', v_asset.current_version);
  end if;
  if not found then
    insert into public.arcreel_assets (
      id, asset_type, origin, status, source_id, source_key, source_fingerprint,
      current_version, name, description, voice_style, voice_id, metadata, published_at
    ) values (
      p_asset_id, v_source.asset_type, 'official', 'published', v_source.id, p_source_asset_key,
      p_source_fingerprint, 0, p_snapshot->>'name', coalesce(p_snapshot->>'description', ''),
      coalesce(p_snapshot->>'voice_style', ''), nullif(p_snapshot->>'voice_id', ''),
      coalesce(p_snapshot->'metadata', '{}'::jsonb), now()
    ) returning * into v_asset;
  end if;
  v_version := v_asset.current_version + 1;
  v_prefix := 'official/' || v_source.source_key || '/' || v_asset.id::text || '/' || p_version_id::text || '/';
  for v_file in select value from jsonb_array_elements(coalesce(p_snapshot->'files', '[]'::jsonb)) loop
    if coalesce(v_file->>'bucket_id', '') <> 'arcreel-assets'
       or coalesce(v_file->>'object_path', '') not like v_prefix || '%'
       or not exists (
         select 1 from storage.objects o
         where o.bucket_id = 'arcreel-assets' and o.name = v_file->>'object_path'
       ) then
      raise exception 'ARCREEL_ASSET_FILE_INVALID' using errcode = '22023';
    end if;
  end loop;

  insert into public.arcreel_asset_versions (
    id, asset_id, version, name, description, voice_style, voice_id, metadata, source_fingerprint
  ) values (
    p_version_id, v_asset.id, v_version, p_snapshot->>'name', coalesce(p_snapshot->>'description', ''),
    coalesce(p_snapshot->>'voice_style', ''), nullif(p_snapshot->>'voice_id', ''),
    coalesce(p_snapshot->'metadata', '{}'::jsonb), p_source_fingerprint
  );
  insert into public.arcreel_asset_files (
    version_id, file_key, role, media_type, mime_type, bucket_id, object_path,
    byte_size, sha256, revision, sort_order, source_fields
  ) select
    p_version_id, item->>'key', coalesce(item->>'role', 'attachment'), item->>'media_type',
    nullif(item->>'mime_type', ''), item->>'bucket_id', item->>'object_path',
    nullif(item->>'byte_size', '')::bigint, nullif(lower(item->>'sha256'), ''),
    nullif(item->>'revision', ''), coalesce((item->>'sort_order')::integer, 0),
    coalesce(item->'source_fields', '[]'::jsonb)
  from jsonb_array_elements(coalesce(p_snapshot->'files', '[]'::jsonb)) item;

  delete from public.arcreel_asset_aliases where asset_id = v_asset.id;
  insert into public.arcreel_asset_aliases (asset_id, alias)
  select v_asset.id, btrim(value)
  from jsonb_array_elements_text(coalesce(p_snapshot->'aliases', '[]'::jsonb)) value
  where char_length(btrim(value)) between 1 and 200
  on conflict do nothing;

  update public.arcreel_assets set
    status = 'published', current_version = v_version, source_fingerprint = p_source_fingerprint,
    name = p_snapshot->>'name', description = coalesce(p_snapshot->>'description', ''),
    voice_style = coalesce(p_snapshot->>'voice_style', ''), voice_id = nullif(p_snapshot->>'voice_id', ''),
    metadata = coalesce(p_snapshot->'metadata', '{}'::jsonb), published_at = now(), archived_at = null
  where id = v_asset.id;
  insert into public.arcreel_asset_changes (asset_id, asset_type, operation, asset_version)
  values (v_asset.id, v_source.asset_type, 'upsert', v_version);
  return jsonb_build_object(
    'outcome', case when v_version = 1 then 'added' else 'updated' end,
    'asset_id', v_asset.id,
    'version', v_version
  );
end;
$$;

create or replace function public.arcreel_official_asset_state(
  p_source_key text,
  p_source_asset_key text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare v_result jsonb;
begin
  if auth.role() <> 'service_role' then raise exception 'ARCREEL_SERVICE_ROLE_REQUIRED' using errcode = '42501'; end if;
  select jsonb_build_object(
    'asset_id', a.id,
    'source_fingerprint', a.source_fingerprint,
    'status', a.status,
    'version', a.current_version
  ) into v_result
  from public.arcreel_assets a
  join public.arcreel_asset_sync_sources s on s.id = a.source_id
  where s.source_key = p_source_key and a.source_key = p_source_asset_key;
  return v_result;
end;
$$;

create or replace function public.arcreel_archive_missing_official_assets(
  p_source_key text,
  p_seen_source_keys text[]
)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_source_id uuid;
  v_count integer := 0;
begin
  if auth.role() <> 'service_role' then raise exception 'ARCREEL_SERVICE_ROLE_REQUIRED' using errcode = '42501'; end if;
  select id into v_source_id from public.arcreel_asset_sync_sources where source_key = p_source_key;
  if not found then raise exception 'ARCREEL_SYNC_SOURCE_NOT_FOUND' using errcode = '22023'; end if;
  with archived as (
    update public.arcreel_assets set status = 'archived', archived_at = now()
    where source_id = v_source_id and status = 'published'
      and not (source_key = any(coalesce(p_seen_source_keys, '{}'::text[])))
    returning id, asset_type, current_version
  ), changes as (
    insert into public.arcreel_asset_changes (asset_id, asset_type, operation, asset_version)
    select id, asset_type, 'archive', current_version from archived
    returning 1
  ) select count(*) into v_count from changes;
  return v_count;
end;
$$;

revoke all on function public.arcreel_require_active_profile() from public, anon, authenticated;
revoke all on function public.arcreel_require_admin_profile() from public, anon, authenticated;
revoke all on function public.arcreel_pull_asset_changes(text[], bigint, integer) from public, anon;
revoke all on function public.arcreel_publish_asset(uuid, uuid, uuid, text, text, text, text, text, text[], jsonb, jsonb) from public, anon;
revoke all on function public.arcreel_archive_shared_asset(uuid) from public, anon;
revoke all on function public.arcreel_asset_sync_dashboard() from public, anon;
revoke all on function public.arcreel_request_asset_sync_run(text, text) from public, anon;
revoke all on function public.arcreel_update_asset_sync_source(text, text, integer) from public, anon;
revoke all on function public.arcreel_cancel_asset_sync_run(uuid) from public, anon;
revoke all on function public.arcreel_retry_asset_sync_run(uuid) from public, anon;
revoke all on function public.arcreel_claim_asset_sync_run(text) from public, anon, authenticated;
revoke all on function public.arcreel_heartbeat_asset_sync_run(uuid, text) from public, anon, authenticated;
revoke all on function public.arcreel_report_asset_sync_run(uuid, text, text, jsonb, integer, integer, integer, integer, jsonb, text, text) from public, anon, authenticated;
revoke all on function public.arcreel_import_official_asset(text, text, uuid, uuid, text, jsonb) from public, anon, authenticated;
revoke all on function public.arcreel_official_asset_state(text, text) from public, anon, authenticated;
revoke all on function public.arcreel_archive_missing_official_assets(text, text[]) from public, anon, authenticated;
grant execute on function public.arcreel_pull_asset_changes(text[], bigint, integer) to authenticated;
grant execute on function public.arcreel_publish_asset(uuid, uuid, uuid, text, text, text, text, text, text[], jsonb, jsonb) to authenticated;
grant execute on function public.arcreel_archive_shared_asset(uuid) to authenticated;
grant execute on function public.arcreel_asset_sync_dashboard() to authenticated;
grant execute on function public.arcreel_request_asset_sync_run(text, text) to authenticated;
grant execute on function public.arcreel_update_asset_sync_source(text, text, integer) to authenticated;
grant execute on function public.arcreel_cancel_asset_sync_run(uuid) to authenticated;
grant execute on function public.arcreel_retry_asset_sync_run(uuid) to authenticated;
grant execute on function public.arcreel_claim_asset_sync_run(text) to service_role;
grant execute on function public.arcreel_heartbeat_asset_sync_run(uuid, text) to service_role;
grant execute on function public.arcreel_report_asset_sync_run(uuid, text, text, jsonb, integer, integer, integer, integer, jsonb, text, text) to service_role;
grant execute on function public.arcreel_import_official_asset(text, text, uuid, uuid, text, jsonb) to service_role;
grant execute on function public.arcreel_official_asset_state(text, text) to service_role;
grant execute on function public.arcreel_archive_missing_official_assets(text, text[]) to service_role;

comment on table public.arcreel_assets is
  'Unified company catalog for source-imported and user-shared character, scene, and prop assets.';
comment on table public.arcreel_asset_sync_sources is
  'Monitored upstream asset sources. The worker runs separately from Supabase but on the same server.';
