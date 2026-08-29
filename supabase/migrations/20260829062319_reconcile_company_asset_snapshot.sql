create index if not exists arcreel_assets_type_id_idx
  on public.arcreel_assets (asset_type, id);

create index if not exists arcreel_asset_changes_asset_revision_idx
  on public.arcreel_asset_changes (asset_id, revision);

create or replace function public.arcreel_pull_asset_snapshot(
  p_asset_types text[],
  p_after_id uuid default null,
  p_snapshot_cursor bigint default null,
  p_limit integer default 100
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_limit integer := least(greatest(coalesce(p_limit, 100), 1), 500);
  v_current_cursor bigint;
  v_snapshot_cursor bigint;
  v_assets jsonb;
  v_next_page_token uuid;
  v_has_more boolean;
begin
  perform public.arcreel_require_active_profile();
  if p_asset_types is null or cardinality(p_asset_types) = 0
     or exists (select 1 from unnest(p_asset_types) t where t not in ('character', 'scene', 'prop')) then
    raise exception 'ARCREEL_ASSET_TYPE_INVALID' using errcode = '22023';
  end if;

  select coalesce(max(c.revision), 0)
  into v_current_cursor
  from public.arcreel_asset_changes c
  where c.asset_type = any (p_asset_types);

  if p_snapshot_cursor is null then
    v_snapshot_cursor := v_current_cursor;
  elsif p_snapshot_cursor < 0 or p_snapshot_cursor > v_current_cursor then
    raise exception 'ARCREEL_ASSET_SNAPSHOT_CURSOR_INVALID' using errcode = '22023';
  else
    v_snapshot_cursor := p_snapshot_cursor;
  end if;

  with candidate_assets as (
    select a.id
    from public.arcreel_assets a
    where a.asset_type = any (p_asset_types)
      and (p_after_id is null or a.id > p_after_id)
      and exists (
        select 1
        from public.arcreel_asset_changes c
        where c.asset_id = a.id and c.revision <= v_snapshot_cursor
      )
    order by a.id
    limit v_limit + 1
  ), selected_assets as (
    select candidate.id
    from candidate_assets candidate
    order by candidate.id
    limit v_limit
  ), payloads as (
    select
      a.id,
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
    from selected_assets selected
    join public.arcreel_assets a on a.id = selected.id
    left join public.arcreel_asset_versions v
      on v.asset_id = a.id and v.version = a.current_version
    left join public.arcreel_profiles p on p.id = a.owner_id
    order by a.id
  )
  select
    coalesce(jsonb_agg(payloads.asset order by payloads.id), '[]'::jsonb),
    (array_agg(payloads.id order by payloads.id desc))[1],
    (select count(*) > v_limit from candidate_assets)
  into v_assets, v_next_page_token, v_has_more
  from payloads;

  if not v_has_more then
    v_next_page_token := null;
  end if;

  return jsonb_build_object(
    'assets', v_assets,
    'snapshot_cursor', v_snapshot_cursor,
    'next_page_token', v_next_page_token,
    'has_more', v_has_more
  );
end;
$$;

revoke all on function public.arcreel_pull_asset_snapshot(text[], uuid, bigint, integer)
  from public, anon;
grant execute on function public.arcreel_pull_asset_snapshot(text[], uuid, bigint, integer)
  to authenticated;

comment on function public.arcreel_pull_asset_snapshot(text[], uuid, bigint, integer) is
  'Returns a stable, paginated current company asset manifest followed by incremental catch-up from snapshot_cursor.';
