begin;

create extension if not exists pgtap with schema extensions;

select plan(6);

insert into auth.users (id)
values ('11111111-1111-4111-8111-111111111111');

insert into public.arcreel_profiles (id, username, auth_email)
values (
  '11111111-1111-4111-8111-111111111111',
  'storage-policy-test',
  'storage-policy-test@internal.arcreel.local'
);

select ok(
  not has_table_privilege('authenticated', 'public.arcreel_profiles', 'select'),
  'authenticated cannot read cloud profiles directly'
);

select ok(
  not has_table_privilege('authenticated', 'public.arcreel_asset_files', 'select'),
  'authenticated cannot read catalog file rows directly'
);

set local role authenticated;
select set_config(
  'request.jwt.claim.sub',
  '11111111-1111-4111-8111-111111111111',
  true
);

select lives_ok(
  $$
    insert into storage.objects (bucket_id, name, owner_id)
    values (
      'arcreel-assets',
      'shared/11111111-1111-4111-8111-111111111111/test-asset/test-version/000-primary_image.png',
      '11111111-1111-4111-8111-111111111111'
    )
  $$,
  'active authenticated user can upload to their shared prefix'
);

select is(
  (
    select count(*)::integer
    from storage.objects
    where bucket_id = 'arcreel-assets'
      and name = 'shared/11111111-1111-4111-8111-111111111111/test-asset/test-version/000-primary_image.png'
  ),
  1,
  'active authenticated user can read company asset objects'
);

select set_config('storage.allow_delete_query', 'true', true);

select lives_ok(
  $$
    delete from storage.objects
    where bucket_id = 'arcreel-assets'
      and name = 'shared/11111111-1111-4111-8111-111111111111/test-asset/test-version/000-primary_image.png'
  $$,
  'owner can delete an unreferenced shared object'
);

reset role;

select is(
  (
    select count(*)::integer
    from storage.objects
    where bucket_id = 'arcreel-assets'
      and name = 'shared/11111111-1111-4111-8111-111111111111/test-asset/test-version/000-primary_image.png'
  ),
  0,
  'the unreferenced shared object was deleted'
);

select * from finish();
rollback;
