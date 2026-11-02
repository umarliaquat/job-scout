-- Run once in the Supabase SQL editor of the Free Job Scout project.
-- No passwords, private keys or personal records belong in this file.
begin;

create table if not exists public.scout_profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  baseline_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);
create table if not exists public.scout_activity (
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id text not null check (job_id ~ '^[a-f0-9]{20}$'),
  status text not null default 'new' check (status in ('new','saved','applied','dismissed')),
  notes text not null default '' check (length(notes)<=10000),
  viewed boolean not null default false,
  viewed_at timestamptz,
  marked_new boolean not null default false,
  job_snapshot jsonb not null default '{}'::jsonb check (jsonb_typeof(job_snapshot)='object' and octet_length(job_snapshot::text)<=12000),
  updated_at timestamptz not null default now(),
  primary key (user_id,job_id)
);

alter table public.scout_profiles enable row level security;
alter table public.scout_activity enable row level security;
revoke all on public.scout_profiles, public.scout_activity from anon, public;
grant select,insert,update,delete on public.scout_profiles, public.scout_activity to authenticated;

drop policy if exists profiles_own on public.scout_profiles;
create policy profiles_own on public.scout_profiles for all to authenticated
  using ((select auth.uid())=id) with check ((select auth.uid())=id);
drop policy if exists activity_own on public.scout_activity;
create policy activity_own on public.scout_activity for all to authenticated
  using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);

create or replace function public.scout_set_activity(p_job_id text,p_action text,p_snapshot jsonb default '{}'::jsonb,p_status text default null,p_notes text default null)
returns public.scout_activity language plpgsql security invoker set search_path='' as $$
declare result public.scout_activity;
begin
  if auth.uid() is null then raise exception 'Sign in first'; end if;
  if p_action not in ('view','save') then raise exception 'Invalid activity action'; end if;
  if p_action='save' and (p_status is null or p_notes is null) then raise exception 'Status and notes are required'; end if;
  insert into public.scout_activity(user_id,job_id,status,notes,viewed,viewed_at,job_snapshot)
  values(auth.uid(),p_job_id,coalesce(p_status,'new'),coalesce(p_notes,''),p_action='view',case when p_action='view' then now() else null end,p_snapshot)
  on conflict(user_id,job_id) do update set
    status=case when p_action='save' then p_status else scout_activity.status end,
    notes=case when p_action='save' then p_notes else scout_activity.notes end,
    viewed=scout_activity.viewed or p_action='view',
    viewed_at=case when p_action='view' then coalesce(scout_activity.viewed_at,now()) else scout_activity.viewed_at end,
    marked_new=case when p_action='view' then false else scout_activity.marked_new end,
    job_snapshot=case when p_snapshot='{}'::jsonb then scout_activity.job_snapshot else p_snapshot end,
    updated_at=now()
  returning * into result;
  return result;
end $$;
revoke all on function public.scout_set_activity(text,text,jsonb,text,text) from public,anon;
grant execute on function public.scout_set_activity(text,text,jsonb,text,text) to authenticated;

create or replace function public.scout_import_activity(p_items jsonb)
returns integer language plpgsql security invoker set search_path='' as $$
declare item jsonb; count_added integer:=0; affected integer;
begin
  if auth.uid() is null then raise exception 'Sign in first'; end if;
  if jsonb_typeof(p_items)<>'array' or jsonb_array_length(p_items)>500 then raise exception 'Import at most 500 records per request'; end if;
  for item in select * from jsonb_array_elements(p_items) loop
    insert into public.scout_activity(user_id,job_id,status,notes,viewed,viewed_at,marked_new,job_snapshot)
    values(auth.uid(),item->>'job_id',coalesce(item->>'status','new'),coalesce(item->>'notes',''),coalesce((item->>'viewed')::boolean,false),
      (item->>'viewed_at')::timestamptz,coalesce((item->>'marked_new')::boolean,false),coalesce(item->'job_snapshot','{}'::jsonb))
    on conflict(user_id,job_id) do nothing;
    get diagnostics affected=row_count; count_added=count_added+affected;
  end loop;
  return count_added;
end $$;
revoke all on function public.scout_import_activity(jsonb) from public,anon;
grant execute on function public.scout_import_activity(jsonb) to authenticated;

create or replace function public.scout_delete_account()
returns void language plpgsql security definer set search_path='' as $$
begin
  if auth.uid() is null then raise exception 'Sign in first'; end if;
  delete from auth.users where id=auth.uid();
end $$;
revoke all on function public.scout_delete_account() from public,anon;
grant execute on function public.scout_delete_account() to authenticated;

-- Configuration can check this public boolean without exposing any user data.
create or replace function public.scout_schema_health()
returns jsonb language sql stable security definer set search_path='' as $$
  select jsonb_build_object('version',1,'protected',
    (select count(*)=2 from pg_class c join pg_namespace n on c.relnamespace=n.oid
      where n.nspname='public' and c.relname in ('scout_profiles','scout_activity') and c.relrowsecurity)
    and (select count(*)=2 from pg_policies where schemaname='public' and policyname in ('profiles_own','activity_own')))
$$;
revoke all on function public.scout_schema_health() from public;
grant execute on function public.scout_schema_health() to anon,authenticated;

commit;
