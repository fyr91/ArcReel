begin;

create extension if not exists pgtap with schema extensions;

select plan(15);

insert into auth.users (id)
values
  ('11111111-1111-4111-8111-111111111113'),
  ('11111111-1111-4111-8111-111111111114');

insert into public.arcreel_profiles (id, username, auth_email, role)
values
  (
    '11111111-1111-4111-8111-111111111113',
    'catalog-admin-test',
    'catalog-admin-test@internal.arcreel.local',
    'admin'
  ),
  (
    '11111111-1111-4111-8111-111111111114',
    'catalog-user-test',
    'catalog-user-test@internal.arcreel.local',
    'user'
  );

insert into public.arcreel_asset_sync_sources (
  id, source_key, display_name, asset_type, adapter
) values (
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaab',
  'admin-management-test',
  'Admin management test',
  'character',
  'test'
);

insert into public.arcreel_assets (
  id, asset_type, origin, status, source_id, source_key,
  source_fingerprint, current_version, name, description
) values (
  '10000000-0000-4000-8000-000000000011',
  'character', 'official', 'published',
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaab', 'test-character', repeat('a', 64), 1,
  '管理测试-人物', '待清理的官方测试资产'
);

insert into public.arcreel_assets (
  id, asset_type, origin, status, owner_id, client_asset_id,
  current_version, name, description
) values (
  '10000000-0000-4000-8000-000000000012',
  'prop', 'user_shared', 'published',
  '11111111-1111-4111-8111-111111111113',
  '20000000-0000-4000-8000-000000000012',
  1, '管理测试-共享道具', '保留的共享资产'
);

insert into public.arcreel_asset_versions (
  id, asset_id, version, name, description, source_fingerprint
) values
  (
    '30000000-0000-4000-8000-000000000011',
    '10000000-0000-4000-8000-000000000011',
    1, '管理测试-人物', '待清理的官方测试资产', repeat('a', 64)
  ),
  (
    '30000000-0000-4000-8000-000000000012',
    '10000000-0000-4000-8000-000000000012',
    1, '管理测试-共享道具', '保留的共享资产', null
  );

insert into public.arcreel_asset_aliases (asset_id, alias)
values ('10000000-0000-4000-8000-000000000011', 'Test Character');

insert into public.arcreel_asset_files (
  version_id, file_key, role, media_type, mime_type,
  object_path, byte_size, sha256, revision, sort_order, source_fields
) values (
  '30000000-0000-4000-8000-000000000011',
  'avatarUrl', 'primary_image', 'image', 'image/png',
  'official/admin-management-test/test-character/avatar.png',
  6, repeat('a', 64), '1', 0, '["avatarUrl"]'
);

insert into public.arcreel_asset_changes (asset_id, asset_type, operation, asset_version)
values ('10000000-0000-4000-8000-000000000011', 'character', 'upsert', 1);

select ok(
  has_function_privilege(
    'authenticated',
    'public.arcreel_admin_list_assets(text, text, text, integer, integer)',
    'execute'
  ),
  'authenticated users can execute the admin list RPC'
);

select ok(
  not has_function_privilege(
    'anon',
    'public.arcreel_admin_list_assets(text, text, text, integer, integer)',
    'execute'
  ),
  'anonymous users cannot execute the admin list RPC'
);

select ok(
  has_function_privilege(
    'authenticated',
    'public.arcreel_admin_delete_asset(uuid)',
    'execute'
  ),
  'authenticated users can reach the admin delete RPC'
);

set local role authenticated;
select set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111114', true);

select throws_ok(
  $$ select public.arcreel_admin_list_assets(null, null, null, 24, 0) $$,
  '42501',
  'ARCREEL_ADMIN_REQUIRED',
  'a non-admin profile cannot inspect the central catalog'
);

select set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111113', true);

select is(
  (public.arcreel_admin_list_assets(null, null, '管理测试-', 24, 0)->>'total')::integer,
  2,
  'the unfiltered admin list counts all central assets'
);

select is(
  jsonb_array_length(
    public.arcreel_admin_list_assets('character', 'official', '管理测试-', 24, 0)->'items'
  ),
  1,
  'type, origin, and name query filters are combined'
);

select is(
  public.arcreel_admin_list_assets(null, null, '管理测试-', 24, 0)->'totals'->>'character',
  '1',
  'the page includes character totals'
);

select is(
  jsonb_array_length(
    public.arcreel_admin_list_assets('character', null, null, 24, 0)->'items'->0->'files'
  ),
  1,
  'the current version file metadata is included'
);

select is(
  public.arcreel_admin_get_asset_preview('10000000-0000-4000-8000-000000000011')
    ->>'object_path',
  'official/admin-management-test/test-character/avatar.png',
  'the preview RPC selects the primary image'
);

select is(
  (
    public.arcreel_admin_delete_asset('10000000-0000-4000-8000-000000000011')
      ->>'queued_file_count'
  )::integer,
  1,
  'hard delete queues every cloud file for cleanup'
);

reset role;

select is(
  (select count(*)::integer from public.arcreel_assets where id = '10000000-0000-4000-8000-000000000011'),
  0,
  'hard delete removes the central asset row'
);

select is(
  (
    select count(*)::integer
    from public.arcreel_asset_versions
    where asset_id = '10000000-0000-4000-8000-000000000011'
  ),
  0,
  'hard delete cascades through version rows'
);

select is(
  (
    select count(*)::integer
    from public.arcreel_asset_file_deletions
    where object_path = 'official/admin-management-test/test-character/avatar.png'
  ),
  1,
  'the durable Storage cleanup record remains after metadata deletion'
);

set local role service_role;
select set_config('request.jwt.claim.role', 'service_role', true);

select is(
  public.arcreel_claim_asset_file_deletion('test-worker')->>'object_path',
  'official/admin-management-test/test-character/avatar.png',
  'the monitor worker can claim the queued Storage object'
);

select lives_ok(
  $$
    select public.arcreel_report_asset_file_deletion(
      (
        select id from public.arcreel_asset_file_deletions
        where object_path = 'official/admin-management-test/test-character/avatar.png'
      ),
      'test-worker',
      true,
      null
    )
  $$,
  'the monitor worker can finish the Storage cleanup task'
);

select * from finish();
rollback;
