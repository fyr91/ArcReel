begin;

create extension if not exists pgtap with schema extensions;

select plan(9);

insert into auth.users (id)
values ('11111111-1111-4111-8111-111111111112');

insert into public.arcreel_profiles (id, username, auth_email)
values (
  '11111111-1111-4111-8111-111111111112',
  'snapshot-test',
  'snapshot-test@internal.arcreel.local'
);

delete from public.arcreel_assets where asset_type = 'character';

insert into public.arcreel_asset_sync_sources (
  id, source_key, display_name, asset_type, adapter
) values (
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'snapshot-test',
  'Snapshot test',
  'character',
  'test'
);

insert into public.arcreel_assets (
  id, asset_type, origin, status, source_id, source_key,
  source_fingerprint, current_version, name
) values
  (
    '10000000-0000-4000-8000-000000000001',
    'character', 'official', 'published',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'croco-dad', repeat('a', 64), 1, '鳄鱼爸爸'
  ),
  (
    '20000000-0000-4000-8000-000000000002',
    'character', 'official', 'published',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'croco-mom', repeat('b', 64), 1, '鳄鱼妈妈'
  );

insert into public.arcreel_asset_versions (
  id, asset_id, version, name, description, voice_id, source_fingerprint
) values
  (
    '30000000-0000-4000-8000-000000000001',
    '10000000-0000-4000-8000-000000000001',
    1, '鳄鱼爸爸', '温和的父亲', 'voice-dad', repeat('a', 64)
  ),
  (
    '30000000-0000-4000-8000-000000000002',
    '20000000-0000-4000-8000-000000000002',
    1, '鳄鱼妈妈', '温和的母亲', 'voice-mom', repeat('b', 64)
  );

insert into public.arcreel_asset_aliases (asset_id, alias)
values ('10000000-0000-4000-8000-000000000001', 'Croco Dad');

insert into public.arcreel_asset_files (
  version_id, file_key, role, media_type, mime_type,
  object_path, byte_size, sha256, revision, sort_order, source_fields
) values
  (
    '30000000-0000-4000-8000-000000000001',
    'avatarUrl', 'primary_image', 'image', 'image/png',
    'official/snapshot-test/croco-dad/avatar.png', 6, repeat('a', 64), '1', 0, '["avatarUrl"]'
  ),
  (
    '30000000-0000-4000-8000-000000000001',
    'voice', 'reference_audio', 'audio', 'audio/wav',
    'official/snapshot-test/croco-dad/voice.wav', 5, repeat('b', 64), '1', 1, '["voice"]'
  );

insert into public.arcreel_asset_changes (revision, asset_id, asset_type, operation, asset_version)
overriding system value
values
  (900000000000001, '10000000-0000-4000-8000-000000000001', 'character', 'upsert', 1),
  (900000000000002, '20000000-0000-4000-8000-000000000002', 'character', 'upsert', 1);

select ok(
  has_function_privilege(
    'authenticated',
    'public.arcreel_pull_asset_snapshot(text[], uuid, bigint, integer)',
    'execute'
  ),
  'authenticated users can execute the snapshot RPC'
);

set local role authenticated;
select set_config(
  'request.jwt.claim.sub',
  '11111111-1111-4111-8111-111111111112',
  true
);

select is(
  jsonb_array_length(public.arcreel_pull_asset_snapshot(array['character'], null, null, 1)->'assets'),
  1,
  'the first snapshot page honors its limit'
);

select is(
  public.arcreel_pull_asset_snapshot(array['character'], null, null, 1)->>'has_more',
  'true',
  'the first snapshot page reports more assets'
);

select is(
  public.arcreel_pull_asset_snapshot(array['character'], null, null, 1)->>'next_page_token',
  '10000000-0000-4000-8000-000000000001',
  'the next page token is the last returned asset id'
);

select ok(
  (public.arcreel_pull_asset_snapshot(array['character'], null, null, 1)->>'snapshot_cursor')::bigint > 0,
  'the snapshot freezes a positive change cursor'
);

select is(
  jsonb_array_length(
    public.arcreel_pull_asset_snapshot(array['character'], null, null, 1)
      ->'assets'->0->'files'
  ),
  2,
  'the snapshot includes image and audio file metadata'
);

select is(
  public.arcreel_pull_asset_snapshot(array['character'], null, null, 1)
    ->'assets'->0->'aliases'->>0,
  'Croco Dad',
  'the snapshot includes alternate language names'
);

select is(
  jsonb_array_length(
    public.arcreel_pull_asset_snapshot(
      array['character'],
      '10000000-0000-4000-8000-000000000001',
      (public.arcreel_pull_asset_snapshot(array['character'], null, null, 1)->>'snapshot_cursor')::bigint,
      1
    )->'assets'
  ),
  1,
  'the frozen cursor can be reused for the second page'
);

select is(
  public.arcreel_pull_asset_snapshot(
    array['character'],
    '10000000-0000-4000-8000-000000000001',
    (public.arcreel_pull_asset_snapshot(array['character'], null, null, 1)->>'snapshot_cursor')::bigint,
    1
  )->>'has_more',
  'false',
  'the last snapshot page terminates pagination'
);

select * from finish();
rollback;
