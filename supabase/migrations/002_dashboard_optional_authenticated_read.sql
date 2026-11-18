-- Optional alternative for a separately hosted Supabase-authenticated client.
-- The ChatGPT Site dashboard uses a server-side key and does not require this.
grant select on public.startup_companies, public.funding_rounds to authenticated;

drop policy if exists "authenticated users can read startup companies" on public.startup_companies;
create policy "authenticated users can read startup companies"
on public.startup_companies for select to authenticated using (true);

drop policy if exists "authenticated users can read funding rounds" on public.funding_rounds;
create policy "authenticated users can read funding rounds"
on public.funding_rounds for select to authenticated using (true);
