begin;

alter table public.arcreel_profiles
  add column if not exists creation_request_id uuid,
  add column if not exists creation_request_fingerprint text;

alter table public.arcreel_profiles
  add constraint arcreel_profiles_creation_request_pair_check
  check (
    (creation_request_id is null and creation_request_fingerprint is null)
    or (
      creation_request_id is not null
      and creation_request_fingerprint ~ '^[0-9a-f]{64}$'
    )
  );

create unique index if not exists arcreel_profiles_creation_request_id_unique
  on public.arcreel_profiles (creation_request_id)
  where creation_request_id is not null;

comment on column public.arcreel_profiles.creation_request_id is
  'Stable request identity used to safely replay cloud account creation.';
comment on column public.arcreel_profiles.creation_request_fingerprint is
  'HMAC fingerprint used to reject reuse of a creation request ID with different input.';

commit;
