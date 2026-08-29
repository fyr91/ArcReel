create schema if not exists arcreel_private;

revoke all on schema arcreel_private from public, anon, authenticated;
grant usage on schema arcreel_private to authenticated;

create or replace function arcreel_private.has_active_profile()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select (select auth.uid()) is not null
    and exists (
      select 1
      from public.arcreel_profiles p
      where p.id = (select auth.uid())
        and p.status = 'active'
    );
$$;

create or replace function arcreel_private.can_delete_shared_object(
  p_bucket_id text,
  p_object_path text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select p_bucket_id = 'arcreel-assets'
    and split_part(p_object_path, '/', 1) = 'shared'
    and split_part(p_object_path, '/', 2) = (select auth.uid())::text
    and arcreel_private.has_active_profile()
    and not exists (
      select 1
      from public.arcreel_asset_files f
      where f.bucket_id = p_bucket_id
        and f.object_path = p_object_path
    );
$$;

revoke all on function arcreel_private.has_active_profile()
  from public, anon, authenticated;
revoke all on function arcreel_private.can_delete_shared_object(text, text)
  from public, anon, authenticated;
grant execute on function arcreel_private.has_active_profile()
  to authenticated;
grant execute on function arcreel_private.can_delete_shared_object(text, text)
  to authenticated;

drop policy if exists arcreel_assets_active_read on storage.objects;
create policy arcreel_assets_active_read on storage.objects
for select to authenticated
using (
  bucket_id = 'arcreel-assets'
  and arcreel_private.has_active_profile()
);

drop policy if exists arcreel_assets_shared_insert on storage.objects;
create policy arcreel_assets_shared_insert on storage.objects
for insert to authenticated
with check (
  bucket_id = 'arcreel-assets'
  and (storage.foldername(name))[1] = 'shared'
  and (storage.foldername(name))[2] = (select auth.uid())::text
  and arcreel_private.has_active_profile()
);

drop policy if exists arcreel_assets_shared_delete on storage.objects;
create policy arcreel_assets_shared_delete on storage.objects
for delete to authenticated
using (
  arcreel_private.can_delete_shared_object(bucket_id, name)
);

comment on schema arcreel_private is
  'Non-exposed predicates used by ArcReel row-level security policies.';
comment on function arcreel_private.has_active_profile() is
  'Checks the current authenticated identity without exposing profile rows.';
comment on function arcreel_private.can_delete_shared_object(text, text) is
  'Allows an active user to delete only their own unreferenced shared upload.';
